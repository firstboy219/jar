package online.cosger.jarvis.screen

import android.content.Context
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.os.Handler
import android.os.Looper
import android.util.Base64
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.ByteArrayOutputStream

/**
 * Screen sharing with JARVIS: a low-resolution mirror of the screen, of which only the latest frame is
 * kept. A frame is sent only together with something the owner says — never streamed continuously.
 * Apps that mark their windows secure (banking, passwords) appear black, as Android enforces.
 */
class ScreenCapture(private val context: Context) {
    private val _active = MutableStateFlow(false)
    val active: StateFlow<Boolean> = _active

    private var projection: MediaProjection? = null
    private var display: VirtualDisplay? = null
    private var reader: ImageReader? = null

    fun attach(p: MediaProjection) {
        detach()
        projection = p
        val metrics = context.resources.displayMetrics
        val scale = TARGET_WIDTH.toFloat() / metrics.widthPixels
        val w = TARGET_WIDTH
        val h = (metrics.heightPixels * scale).toInt()
        val r = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        reader = r
        p.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() = detach()
        }, Handler(Looper.getMainLooper()))
        display = p.createVirtualDisplay("jarvis-share", w, h, metrics.densityDpi / 2,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, r.surface, null, null)
        _active.value = true
    }

    fun detach() {
        lastFrame = null
        display?.release(); display = null
        reader?.close(); reader = null
        projection?.let { p -> projection = null; runCatching { p.stop() } }
        _active.value = false
    }

    @Volatile private var lastFrame: Bitmap? = null

    /** Latest frame (kept, because acquireLatestImage hands each image out only once). */
    fun latestBitmap(): Bitmap? {
        val image = runCatching { reader?.acquireLatestImage() }.getOrNull() ?: return lastFrame
        return image.use { img ->
            val plane = img.planes[0]
            val rowPadding = plane.rowStride - plane.pixelStride * img.width
            val bmp = Bitmap.createBitmap(img.width + rowPadding / plane.pixelStride, img.height, Bitmap.Config.ARGB_8888)
            bmp.copyPixelsFromBuffer(plane.buffer)
            Bitmap.createBitmap(bmp, 0, 0, img.width, img.height).also { lastFrame = it }
        }
    }

    /** Latest frame as base64 JPEG (≈60–150 KB), or null if nothing captured yet. */
    fun latestJpegBase64(): String? = latestBitmap()?.let { jpeg(it) }

    fun jpeg(bmp: Bitmap): String {
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }

    companion object {
        const val TARGET_WIDTH = 1080 // sharp enough for ML Kit to read chat text (≥16 px characters)
        const val JPEG_QUALITY = 60
    }
}
