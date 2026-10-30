package online.cosger.jarvis.web

import android.annotation.SuppressLint
import android.content.Context
import android.content.MutableContextWrapper
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine

/**
 * ADR-087 batch I: JARVIS working on any website (booking a hotel, a flight, a ticket) in a browser that lives on the phone but nobody sees.
 * A session keeps its page between steps; jarvis-core sends the script to run on it (read the page and its form, fill fields, press a
 * button) and decides what to do next. When the site needs the OWNER — sign in, a "not a robot" check, a code, the payment — the very same
 * page (with what was filled) is shown to him in [WebLoginActivity]; when he presses "Selesai" JARVIS carries on.
 *
 * Kept here: https only; bank / e-wallet / crypto sites are never opened by a session; no JavaScript bridge into the app; a session that
 * is not used for 20 minutes is closed.
 */
object WebSessions {
    class Session(val id: String, val web: WebView, val holder: MutableContextWrapper) {
        @Volatile var loading = false
        @Volatile var lastUsed = SystemClock.uptimeMillis()
        @Volatile var shown = false
        @Volatile var ownerDone = false
        @Volatile var ownerCancelled = false
        var reason = ""
    }

    private val sessions = mutableMapOf<String, Session>()
    private const val IDLE_MS = 20 * 60_000L

    fun get(id: String): Session? = sessions[id]

    @SuppressLint("SetJavaScriptEnabled")
    private fun create(context: Context, id: String): Session {
        val holder = MutableContextWrapper(context.applicationContext)
        val web = WebView(holder)
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.javaScriptCanOpenWindowsAutomatically = false
        web.measure(View.MeasureSpec.makeMeasureSpec(1080, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(2340, View.MeasureSpec.EXACTLY))
        web.layout(0, 0, 1080, 2340)
        val s = Session(id, web, holder)
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url.toString()
                return WebRules.host(u) == null || WebRules.financial(u)   // https only; never a bank / e-wallet / crypto site
            }
            override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) { s.loading = true }
            override fun onPageFinished(view: WebView, url: String) { s.loading = false }
        }
        sessions[id] = s
        return s
    }

    private fun sweep() {
        val now = SystemClock.uptimeMillis()
        sessions.values.filter { !it.shown && now - it.lastUsed > IDLE_MS }.map { it.id }.forEach { close(it) }
    }

    suspend fun open(context: Context, id: String, url: String, waitMs: Long = 25_000): JsonObject = withContext(Dispatchers.Main) {
        if (WebRules.host(url) == null || WebRules.financial(url)) return@withContext buildJsonObject { put("error", "situs tidak boleh dibuka (https saja; bukan situs bank/dompet digital)") }
        sweep()
        val s = sessions[id] ?: create(context, id)
        s.lastUsed = SystemClock.uptimeMillis()
        s.ownerDone = false; s.ownerCancelled = false
        s.loading = true
        s.web.loadUrl(url)
        settle(s, waitMs)
        status(s)
    }

    /** Runs the server's script on the session's page (after the page settles); its JSON string result comes back as `result`. */
    suspend fun eval(id: String, js: String, settleMs: Long = 0): JsonObject = withContext(Dispatchers.Main) {
        val s = sessions[id] ?: return@withContext buildJsonObject { put("error", "sesi web sudah ditutup — buka lagi") }
        s.lastUsed = SystemClock.uptimeMillis()
        val out = evaluate(s.web, js)
        if (settleMs > 0) { delay(400); settle(s, settleMs) }
        buildJsonObject { put("result", out); put("url", s.web.url ?: ""); put("title", s.web.title ?: "") }
    }

    private suspend fun settle(s: Session, waitMs: Long) {
        withTimeoutOrNull(waitMs) {
            while (s.loading) delay(250)
            var last = -1
            var still = 0
            while (still < 3) {   // the page stops changing (script-drawn content, a bot check clearing itself)
                delay(400)
                val len = evaluate(s.web, "String((document.body&&document.body.innerText||'').length)+'|'+document.title").hashCode()
                if (len == last) still++ else { still = 0; last = len }
            }
        }
    }

    fun status(s: Session): JsonObject = buildJsonObject {
        put("url", s.web.url ?: ""); put("title", s.web.title ?: ""); put("shown", s.shown)
        put("owner_done", s.ownerDone); put("owner_cancelled", s.ownerCancelled); put("loading", s.loading)
    }

    fun statusOf(id: String): JsonObject = sessions[id]?.let { status(it) } ?: buildJsonObject { put("error", "sesi web sudah ditutup") }

    /** The owner sees the session's own page (to sign in, prove he is human, type a code, pay); "Selesai" hands it back. */
    fun show(context: Context, id: String, reason: String): JsonObject {
        val s = sessions[id] ?: return buildJsonObject { put("error", "sesi web sudah ditutup") }
        s.reason = reason.take(160); s.ownerDone = false; s.ownerCancelled = false
        WebLoginActivity.openSession(context, id)
        return buildJsonObject { put("ok", true) }
    }

    /** Called by the activity: the page is put on screen (it needs the activity as its context for pickers and autofill) … */
    fun attach(id: String, activity: Context, parent: ViewGroup): Session? {
        val s = sessions[id] ?: return null
        (s.web.parent as? ViewGroup)?.removeView(s.web)
        s.holder.baseContext = activity
        parent.addView(s.web, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        s.shown = true
        return s
    }

    /** … and taken off it again, still alive for JARVIS. */
    fun detach(id: String, done: Boolean) {
        val s = sessions[id] ?: return
        (s.web.parent as? ViewGroup)?.removeView(s.web)
        s.holder.baseContext = s.web.context.applicationContext
        s.shown = false
        if (done) s.ownerDone = true else s.ownerCancelled = true
        s.lastUsed = SystemClock.uptimeMillis()
        CookieManager.getInstance().flush()
    }

    fun close(id: String) {
        val s = sessions.remove(id) ?: return
        (s.web.parent as? ViewGroup)?.removeView(s.web)
        s.web.stopLoading(); s.web.destroy()
        CookieManager.getInstance().flush()
    }

    private suspend fun evaluate(web: WebView, js: String): String = suspendCoroutine { cont ->
        web.evaluateJavascript(js) { raw ->
            cont.resume(runCatching { Json.parseToJsonElement(raw).jsonPrimitive.content }.getOrDefault(raw ?: ""))
        }
    }
}
