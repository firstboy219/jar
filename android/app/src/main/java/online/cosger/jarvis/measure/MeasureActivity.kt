package online.cosger.jarvis.measure

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.graphics.Color
import android.opengl.GLES20
import android.opengl.GLSurfaceView
import android.opengl.Matrix
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.google.ar.core.Anchor
import com.google.ar.core.ArCoreApk
import com.google.ar.core.Config
import com.google.ar.core.DepthPoint
import com.google.ar.core.Plane
import com.google.ar.core.Point
import com.google.ar.core.Session
import com.google.ar.core.TrackingState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.JarvisApp
import java.util.concurrent.ArrayBlockingQueue
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.opengles.GL10

/**
 * ADR-087 (Kamera ukur): an AR ruler. Move the phone so ARCore finds the surfaces, tap a point, tap the next — the real distance between
 * them appears on the line (several points add up: a table's sides, a room's walls). "Simpan" keeps the measurement in JARVIS (Kamera
 * ukur in the app). Far things (a house across the street) are better estimated from a photo in the app.
 */
class MeasureActivity : Activity(), GLSurfaceView.Renderer {
    private var session: Session? = null
    private var installRequested = false
    private lateinit var gl: GLSurfaceView
    private lateinit var overlay: MeasureOverlay
    private lateinit var hint: TextView
    private lateinit var total: TextView
    private val background = BackgroundRenderer()
    private val taps = ArrayBlockingQueue<MotionEvent>(8)
    private val anchors = mutableListOf<Anchor>()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var vw = 1
    private var vh = 1

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        gl = GLSurfaceView(this).apply {
            preserveEGLContextOnPause = true
            setEGLContextClientVersion(2)
            setEGLConfigChooser(8, 8, 8, 8, 16, 0)
            setRenderer(this@MeasureActivity)
            renderMode = GLSurfaceView.RENDERMODE_CONTINUOUSLY
            setOnTouchListener { _, e -> if (e.action == MotionEvent.ACTION_UP) taps.offer(MotionEvent.obtain(e)); true }
        }
        overlay = MeasureOverlay(this)
        hint = TextView(this).apply { setTextColor(Color.WHITE); textSize = 15f; setPadding(32, 48, 32, 16); setShadowLayer(6f, 0f, 0f, Color.BLACK)
            text = "Gerakkan HP pelan ke kiri-kanan agar permukaan dikenali…" }
        total = TextView(this).apply { setTextColor(Color.WHITE); textSize = 22f; setPadding(32, 8, 32, 8); setShadowLayer(6f, 0f, 0f, Color.BLACK) }
        val bar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER; setPadding(16, 16, 16, 48); setBackgroundColor(Color.parseColor("#AA06090F"))
            addView(button("Batal titik") { undo() }); addView(button("Ulang") { clear() }); addView(button("Simpan") { save() }); addView(button("Tutup") { finish() })
        }
        setContentView(FrameLayout(this).apply {
            addView(gl, ViewGroup.LayoutParams(-1, -1))
            addView(this@MeasureActivity.overlay, ViewGroup.LayoutParams(-1, -1))   // not View.overlay
            addView(LinearLayout(this@MeasureActivity).apply { orientation = LinearLayout.VERTICAL; addView(hint); addView(total) }, FrameLayout.LayoutParams(-1, -2, Gravity.TOP))
            addView(bar, FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM))
        })
    }

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply { text = label; setOnClickListener { onClick() } }

    override fun onResume() {
        super.onResume()
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 1); return
        }
        if (session == null) {
            try {
                if (ArCoreApk.getInstance().requestInstall(this, !installRequested) == ArCoreApk.InstallStatus.INSTALL_REQUESTED) { installRequested = true; return }
                session = Session(this).also { s ->
                    val c = Config(s).apply {
                        planeFindingMode = Config.PlaneFindingMode.HORIZONTAL_AND_VERTICAL
                        focusMode = Config.FocusMode.AUTO
                        updateMode = Config.UpdateMode.LATEST_CAMERA_IMAGE
                        if (s.isDepthModeSupported(Config.DepthMode.AUTOMATIC)) depthMode = Config.DepthMode.AUTOMATIC
                    }
                    s.configure(c)
                }
            } catch (e: Exception) {
                Toast.makeText(this, "AR tidak tersedia di HP ini (${e.javaClass.simpleName}). Pakai ukur dari foto di aplikasi.", Toast.LENGTH_LONG).show()
                finish(); return
            }
        }
        runCatching { session?.resume() }.onFailure { Toast.makeText(this, "Kamera AR tidak bisa dibuka", Toast.LENGTH_LONG).show(); finish(); return }
        gl.onResume()
    }

    override fun onPause() {
        super.onPause()
        gl.onPause()
        session?.pause()
    }

    override fun onDestroy() {
        scope.cancel()
        session?.close(); session = null
        super.onDestroy()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (grantResults.firstOrNull() != PackageManager.PERMISSION_GRANTED) { Toast.makeText(this, "Izin kamera dibutuhkan untuk mengukur", Toast.LENGTH_LONG).show(); finish() }
    }

    override fun onSurfaceCreated(unused: GL10?, config: EGLConfig?) {
        GLES20.glClearColor(0f, 0f, 0f, 1f)
        background.create()
    }

    override fun onSurfaceChanged(unused: GL10?, width: Int, height: Int) {
        GLES20.glViewport(0, 0, width, height)
        vw = width; vh = height
        session?.setDisplayGeometry(windowManager.defaultDisplay.rotation, width, height)
    }

    override fun onDrawFrame(unused: GL10?) {
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
        val s = session ?: return
        s.setCameraTextureName(background.textureId)
        val frame = runCatching { s.update() }.getOrNull() ?: return
        background.draw(frame)
        val camera = frame.camera
        val tracking = camera.trackingState == TrackingState.TRACKING
        taps.poll()?.let { tap ->
            if (tracking) {
                frame.hitTest(tap).firstOrNull { h ->
                    when (val t = h.trackable) {
                        is Plane -> t.isPoseInPolygon(h.hitPose)
                        is DepthPoint -> true
                        is Point -> t.orientationMode == Point.OrientationMode.ESTIMATED_SURFACE_NORMAL
                        else -> false
                    }
                }?.let { synchronized(anchors) { anchors.add(it.createAnchor()) } }
            }
            tap.recycle()
        }
        val view = FloatArray(16); val proj = FloatArray(16); val vp = FloatArray(16)
        camera.getViewMatrix(view, 0)
        camera.getProjectionMatrix(proj, 0, 0.05f, 100f)
        Matrix.multiplyMM(vp, 0, proj, 0, view, 0)
        val pts = synchronized(anchors) { anchors.filter { it.trackingState != TrackingState.STOPPED }.map { val p = it.pose; Ruler.P(p.tx(), p.ty(), p.tz()) } }
        val segs = Ruler.segments(pts)
        overlay.points = pts.map { Ruler.project(vp, it, vw, vh) }
        overlay.lengths = segs.map(Ruler::label)
        val planes = s.getAllTrackables(Plane::class.java).any { it.trackingState == TrackingState.TRACKING }
        runOnUiThread {
            overlay.invalidate()
            hint.text = when {
                !tracking -> "Gerakkan HP pelan ke kiri-kanan agar permukaan dikenali…"
                !planes && pts.isEmpty() -> "Arahkan ke lantai/meja/dinding yang bertekstur…"
                pts.isEmpty() -> "Ketuk titik awal di layar"
                else -> "Ketuk titik berikutnya (bisa beberapa sisi)"
            }
            val area = Ruler.area(pts)
            total.text = if (segs.isEmpty()) "" else "Total ${Ruler.label(segs.sum())}" + (if (segs.size > 1) "  (${segs.joinToString(" + ") { Ruler.label(it) }})" else "") +
                (if (area > 0.01f) "\nLuas ${String.format(java.util.Locale("id", "ID"), "%.2f", area)} m²" else "")
        }
    }

    private fun undo() = synchronized(anchors) { anchors.removeLastOrNull()?.detach() }
    private fun clear() = synchronized(anchors) { anchors.forEach { it.detach() }; anchors.clear() }

    private fun save() {
        val pts = synchronized(anchors) { anchors.map { val p = it.pose; Ruler.P(p.tx(), p.ty(), p.tz()) } }
        val segs = Ruler.segments(pts)
        val area = Ruler.area(pts)
        val height = Ruler.height(pts)
        if (segs.isEmpty()) { Toast.makeText(this, "Ketuk minimal dua titik", Toast.LENGTH_SHORT).show(); return }
        val name = EditText(this).apply { hint = "mis. lebar meja" }
        AlertDialog.Builder(this).setTitle("Simpan ukuran ${Ruler.label(segs.sum())}").setView(name)
            .setPositiveButton("Simpan") { _, _ ->
                scope.launch {
                    runCatching {
                        (application as JarvisApp).engine.console.post("/api/v1/app/measure/ar", buildJsonObject {
                            put("label", name.text.toString().ifBlank { "Ukuran AR" }.take(80))
                            put("segments", JsonArray(segs.map { JsonPrimitive(Math.round(it * 1000) / 1000.0) }))
                            if (area > 0.01f) put("area_m2", Math.round(area * 100) / 100.0)
                            if (height > 0.05f) put("height_m", Math.round(height * 100) / 100.0)
                        })
                    }.onSuccess { Toast.makeText(this@MeasureActivity, "Tersimpan di Kamera ukur", Toast.LENGTH_SHORT).show() }
                        .onFailure { Toast.makeText(this@MeasureActivity, "Gagal menyimpan: ${it.message}", Toast.LENGTH_LONG).show() }
                }
            }.setNegativeButton("Batal", null).show()
    }
}
