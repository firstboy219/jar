package online.cosger.jarvis.attach

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.net.ConsoleApi
import online.cosger.jarvis.ocr.ScreenText
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s
import java.io.ByteArrayOutputStream
import kotlin.math.max

/** A file or picture the owner chose in the chat, not yet sent. */
data class PendingAttachment(val uri: Uri, val name: String, val mime: String) {
    val isImage: Boolean get() = AttachmentPrep.isImage(name, mime)
}

/** Pure helpers (unit-tested). */
object AttachmentPrep {
    const val MAX_BYTES = 12_000_000
    const val MAX_IMAGE_SIDE = 1600
    const val MAX_FILES = 5
    private val IMAGE_EXT = setOf("jpg", "jpeg", "png", "webp", "gif", "heic", "heif")

    fun isImage(name: String, mime: String): Boolean =
        mime.startsWith("image/") || name.substringAfterLast('.', "").lowercase() in IMAGE_EXT

    /** Power-of-two decode factor so the longest side lands between [maxSide] and 2× [maxSide]. */
    fun sampleSize(width: Int, height: Int, maxSide: Int = MAX_IMAGE_SIDE): Int {
        var s = 1
        var longest = max(width, height)
        while (longest / 2 >= maxSide) { s *= 2; longest /= 2 }
        return s
    }

    /** Target size so the longest side is at most [maxSide] (never enlarges). */
    fun fit(width: Int, height: Int, maxSide: Int = MAX_IMAGE_SIDE): Pair<Int, Int> {
        val longest = max(width, height)
        if (longest <= maxSide) return width to height
        val f = maxSide.toDouble() / longest
        return max(1, (width * f).toInt()) to max(1, (height * f).toInt())
    }

    /** Pictures are always sent as JPEG, so give them a .jpg name. */
    fun uploadName(name: String, image: Boolean): String =
        if (image) name.substringBeforeLast('.', name).ifBlank { "foto" } + ".jpg" else name

    fun tooBig(bytes: Int): Boolean = bytes > MAX_BYTES
}

/**
 * Sends one attachment to the server (POST /api/v1/attachments) and returns its id. A picture is first
 * shrunk to ≤ 1600 px and read by ML Kit on the phone: the words in it travel as text (free, exact), the
 * picture itself goes to whichever model can see. Files are sent as they are (≤ 12 MB); the server reads
 * PDF, Word, Excel, PowerPoint, text.
 */
class AttachmentUploader(private val context: Context, private val api: ConsoleApi) {
    fun describe(uri: Uri): PendingAttachment {
        val cr = context.contentResolver
        var name = "berkas"
        cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0)?.let { name = it }
        }
        return PendingAttachment(uri, name, cr.getType(uri).orEmpty())
    }

    suspend fun upload(p: PendingAttachment): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val cr = context.contentResolver
            val raw = cr.openInputStream(p.uri)?.use { it.readBytes() } ?: error("berkas tidak bisa dibuka")
            var bytes = raw
            var ocr = ""
            if (p.isImage) {
                val bmp = decode(raw) ?: error("gambar tidak bisa dibaca")
                ocr = withTimeoutOrNull(8_000) { ScreenText.read(bmp) }.orEmpty()
                bytes = ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.JPEG, 85, it) }.toByteArray()
            }
            if (AttachmentPrep.tooBig(bytes.size)) error("${p.name} lebih dari 12 MB")
            val r = api.post("/api/v1/attachments", buildJsonObject {
                put("name", AttachmentPrep.uploadName(p.name, p.isImage))
                put("content_type", if (p.isImage) "image/jpeg" else p.mime)
                put("data", Base64.encodeToString(bytes, Base64.NO_WRAP))
                put("ocr_text", ocr.take(20_000))
            }).obj()
            r.s("id").ifEmpty { error("server tidak mengembalikan id") }
        }
    }

    private fun decode(raw: ByteArray): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(raw, 0, raw.size, bounds)
        if (bounds.outWidth <= 0) return null
        val opts = BitmapFactory.Options().apply { inSampleSize = AttachmentPrep.sampleSize(bounds.outWidth, bounds.outHeight) }
        val bmp = BitmapFactory.decodeByteArray(raw, 0, raw.size, opts) ?: return null
        val (w, h) = AttachmentPrep.fit(bmp.width, bmp.height)
        return if (w == bmp.width) bmp else Bitmap.createScaledBitmap(bmp, w, h, true)
    }
}
