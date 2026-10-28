package online.cosger.jarvis.phone

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.Display
import android.view.Gravity
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.annotation.RequiresApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.io.ByteArrayOutputStream
import kotlin.coroutines.resume

/**
 * ADR-077: JARVIS operates an app the owner approved (first Gojek). jarvis-core sends one instruction at a time over the socket
 * ([PhoneOps]); this service reads the app's screen (accessibility tree) and taps / types / scrolls in it.
 *
 * Safety, enforced HERE as well as on the server: nothing is read or done outside an active run, nothing is read or done in any
 * other app than the run's packages (Back is the only exception), a password field is never typed into, and a banner shows while
 * JARVIS works — its "Hentikan" stops the run.
 */
class PhoneAgentService : AccessibilityService() {
    @Volatile private var lastEventAt = 0L
    @Volatile var runId: Long = 0L
        private set
    private var allowed: Set<String> = emptySet()
    private var appLabel = ""
    private val nodes = mutableListOf<AccessibilityNodeInfo>()
    private var banner: LinearLayout? = null

    override fun onServiceConnected() {
        instance = this
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        lastEventAt = SystemClock.uptimeMillis()
    }

    override fun onInterrupt() = Unit

    override fun onUnbind(intent: Intent?): Boolean {
        end()
        instance = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        end()
        instance = null
        super.onDestroy()
    }

    // ---------- a run ----------

    fun begin(run: Long, label: String, packages: Set<String>, onStop: () -> Unit) {
        runId = run
        appLabel = label
        allowed = packages
        showBanner(onStop)
    }

    fun end() {
        runId = 0L
        allowed = emptySet()
        nodes.clear()
        hideBanner()
    }

    /**
     * The approved app's window. Another window may be in front of it (the phone's screenshot overlay, a system dialog, a floating
     * widget) and then `rootInActiveWindow` is THAT window: look through all windows for the approved app's own.
     */
    private fun appRoot(): AccessibilityNodeInfo? {
        val active = rootInActiveWindow
        if ((active?.packageName?.toString() ?: "") in allowed) return active
        val all = runCatching { windows }.getOrNull().orEmpty().sortedByDescending { it.layer }
        for (w in all) {
            val r = w.root ?: continue
            if ((r.packageName?.toString() ?: "") in allowed) return r
        }
        return active
    }

    private fun foreground(): String = appRoot()?.packageName?.toString().orEmpty()

    private fun requireRun() {
        if (runId == 0L) throw PhoneOpException("tidak ada operasi yang disetujui")
    }

    private fun requireInApp() {
        requireRun()
        val pkg = foreground()
        if (pkg !in allowed) throw PhoneOpException("layar yang terbuka bukan $appLabel ($pkg)")
    }

    /** Wait until the screen stops changing (no accessibility event for 450 ms; at most 3 s). */
    private suspend fun settle() {
        delay(350)
        val end = SystemClock.uptimeMillis() + 3_000
        while (SystemClock.uptimeMillis() < end && SystemClock.uptimeMillis() - lastEventAt < 450) delay(100)
    }

    private fun keyboardOpen(): Boolean = runCatching { windows.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD } }.getOrDefault(false)

    /** The screen as numbered elements. Another app's screen is never read: only its package name is told. */
    suspend fun observe(): JsonObject {
        requireRun()
        settle()
        val root = appRoot()
        val pkg = root?.packageName?.toString().orEmpty()
        nodes.clear()
        val dm = resources.displayMetrics
        return buildJsonObject {
            put("package", pkg)
            put("keyboard", keyboardOpen())
            put("w", dm.widthPixels)
            put("h", dm.heightPixels)
            put("nodes", buildJsonArray {
                if (root != null && pkg in allowed) walk(root, 0) { add(it) }
            })
        }
    }

    private fun walk(n: AccessibilityNodeInfo, depth: Int, emit: (JsonObject) -> Unit) {
        if (nodes.size >= MAX_NODES || depth > 40 || !n.isVisibleToUser) return
        val text = n.text?.toString()?.trim().orEmpty()
        val desc = n.contentDescription?.toString()?.trim().orEmpty()
        val hint = n.hintText?.toString()?.trim().orEmpty()
        val useful = text.isNotEmpty() || desc.isNotEmpty() || hint.isNotEmpty() || n.isClickable || n.isEditable || n.isScrollable || n.isCheckable
        if (useful) {
            val i = nodes.size
            nodes += n
            val r = Rect().also { n.getBoundsInScreen(it) }
            emit(buildJsonObject {
                put("i", i)
                put("c", n.className?.toString()?.substringAfterLast('.').orEmpty())
                if (n.isPassword) put("p", 1) else if (text.isNotEmpty()) put("t", text.take(160))
                if (desc.isNotEmpty() && desc != text) put("d", desc.take(120))
                if (hint.isNotEmpty() && hint != text) put("h", hint.take(80))
                if (n.isClickable || n.isLongClickable) put("k", 1)
                if (n.isEditable) put("e", 1)
                if (n.isScrollable) put("s", 1)
                if (n.isCheckable && n.isChecked) put("ch", 1)
                if (n.isSelected) put("sel", 1)
                put("b", buildJsonArray { listOf(r.left, r.top, r.right, r.bottom).forEach { v -> add(JsonPrimitive(v)) } })
            })
        }
        for (c in 0 until n.childCount) n.getChild(c)?.let { walk(it, depth + 1, emit) }
    }

    private fun nodeAt(index: Int?): AccessibilityNodeInfo =
        index?.let { nodes.getOrNull(it) } ?: throw PhoneOpException("elemen nomor $index tidak ada — lihat layar lagi")

    // ---------- actions ----------

    private suspend fun clickNode(n: AccessibilityNodeInfo) {
        var target: AccessibilityNodeInfo? = n
        while (target != null && !target.isClickable) target = target.parent
        if (target?.performAction(AccessibilityNodeInfo.ACTION_CLICK) != true) {
            val r = Rect().also { n.getBoundsInScreen(it) }
            if (!gesture(r.exactCenterX(), r.exactCenterY(), r.exactCenterX(), r.exactCenterY(), 60)) throw PhoneOpException("ketukan gagal")
        }
    }

    suspend fun tap(index: Int?): JsonObject {
        requireInApp()
        clickNode(nodeAt(index))
        return observe()
    }

    suspend fun type(index: Int?, text: String, submit: Boolean): JsonObject {
        requireInApp()
        var n = nodeAt(index)
        if (!n.isEditable) {
            n = findEditable(n) ?: run {
                // a search box often looks like text or a button until it is tapped: tap it, then use the field that took focus
                clickNode(n)
                delay(900)
                findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.takeIf { it.isEditable } ?: appRoot()?.let { findEditable(it) }
            } ?: throw PhoneOpException("elemen itu bukan kolom isian, dan setelah diketuk tidak ada kolom isian — lihat layarnya lagi")
        }
        if (n.isPassword) throw PhoneOpException("kolom kata sandi/PIN: JARVIS tidak mengetiknya — pemilik yang mengisi")
        n.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        n.performAction(AccessibilityNodeInfo.ACTION_CLICK)
        val args = Bundle().apply { putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text.take(500)) }
        if (!n.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) throw PhoneOpException("teks tidak bisa diisi di kolom itu")
        if (submit && Build.VERSION.SDK_INT >= 30) {
            delay(250)
            n.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
        }
        return observe()
    }

    private fun findEditable(n: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (n.isEditable) return n
        for (c in 0 until n.childCount) n.getChild(c)?.let { findEditable(it) }?.let { return it }
        return null
    }

    suspend fun scroll(direction: String, index: Int?): JsonObject {
        requireInApp()
        val forward = direction == "bawah" || direction == "kanan"
        var target: AccessibilityNodeInfo? = index?.let { nodes.getOrNull(it) }
        while (target != null && !target.isScrollable) target = target.parent
        if (target == null) target = nodes.filter { it.isScrollable }.maxByOrNull { Rect().also { r -> it.getBoundsInScreen(r) }.let { r -> r.width() * r.height() } }
        val action = if (forward) AccessibilityNodeInfo.ACTION_SCROLL_FORWARD else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        if (target?.performAction(action) != true) {
            val dm = resources.displayMetrics
            val cx = dm.widthPixels / 2f
            val cy = dm.heightPixels / 2f
            val dy = dm.heightPixels * 0.3f
            val dx = dm.widthPixels * 0.3f
            when (direction) {
                "atas" -> gesture(cx, cy - dy, cx, cy + dy, 350)
                "kiri" -> gesture(cx - dx, cy, cx + dx, cy, 300)
                "kanan" -> gesture(cx + dx, cy, cx - dx, cy, 300)
                else -> gesture(cx, cy + dy, cx, cy - dy, 350)
            }
        }
        return observe()
    }

    suspend fun back(): JsonObject {
        requireRun()
        performGlobalAction(GLOBAL_ACTION_BACK)
        return observe()
    }

    suspend fun open(pkg: String): JsonObject {
        requireRun()
        if (pkg !in allowed) throw PhoneOpException("aplikasi $pkg tidak termasuk operasi ini")
        val launch = packageManager.getLaunchIntentForPackage(pkg) ?: throw PhoneOpException("$appLabel belum terpasang di HP ini")
        startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED))
        val end = SystemClock.uptimeMillis() + 12_000   // a cold start of a big app takes a while
        delay(1_500)
        while (SystemClock.uptimeMillis() < end && foreground() !in allowed) delay(500)
        return observe()
    }

    /** A picture of the screen (Android 11+), only of the run's app — for what the element list cannot say (maps, pictures). */
    suspend fun screenshot(): JsonObject {
        requireInApp()
        val bmp = (if (Build.VERSION.SDK_INT >= 30) capture() else throw PhoneOpException("tangkapan layar butuh Android 11+"))
            ?: throw PhoneOpException("tangkapan layar gagal")
        val w = 720
        val scaled = if (bmp.width > w) Bitmap.createScaledBitmap(bmp, w, bmp.height * w / bmp.width, true) else bmp
        val out = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, 60, out)
        return buildJsonObject { put("jpeg", java.util.Base64.getEncoder().encodeToString(out.toByteArray())) }
    }

    @RequiresApi(30)
    private suspend fun capture(): Bitmap? = suspendCancellableCoroutine { cont ->
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(result: ScreenshotResult) {
                val soft = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                result.hardwareBuffer.close()
                if (cont.isActive) cont.resume(soft)
            }

            override fun onFailure(errorCode: Int) {
                if (cont.isActive) cont.resume(null)
            }
        })
    }

    private suspend fun gesture(x1: Float, y1: Float, x2: Float, y2: Float, ms: Long): Boolean {
        val path = Path().apply { moveTo(x1, y1); lineTo(x2, y2) }
        val g = GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(path, 0, ms)).build()
        return suspendCancellableCoroutine { cont ->
            val ok = dispatchGesture(g, object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) { if (cont.isActive) cont.resume(true) }
                override fun onCancelled(gestureDescription: GestureDescription?) { if (cont.isActive) cont.resume(false) }
            }, null)
            if (!ok && cont.isActive) cont.resume(false)
        }
    }

    // ---------- the banner: JARVIS is working, tap to stop ----------

    private fun showBanner(onStop: () -> Unit) {
        hideBanner()
        val wm = getSystemService(WindowManager::class.java) ?: return
        val pad = (8 * resources.displayMetrics.density).toInt()
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(pad * 2, pad / 2, pad / 2, pad / 2)
            setBackgroundColor(Color.argb(230, 15, 23, 42))
            addView(TextView(context).apply {
                text = "🤖 JARVIS mengoperasikan $appLabel"
                setTextColor(Color.WHITE)
                textSize = 13f
            })
            addView(Button(context).apply {
                text = "Hentikan"
                textSize = 12f
                setOnClickListener { onStop(); end() }
            })
        }
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = (72 * resources.displayMetrics.density).toInt()   // above the app's own bottom bar
        }
        runCatching { wm.addView(box, lp); banner = box }
    }

    private fun hideBanner() {
        val b = banner ?: return
        banner = null
        runCatching { getSystemService(WindowManager::class.java)?.removeView(b) }
    }

    companion object {
        const val MAX_NODES = 160
        @Volatile var instance: PhoneAgentService? = null
            private set
    }
}

class PhoneOpException(message: String) : RuntimeException(message)
