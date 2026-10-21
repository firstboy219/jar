package online.cosger.jarvis.ocr

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * Reads the text on the shared screen ON THE PHONE (ML Kit, bundled Latin model — free, offline,
 * nothing uploaded). JARVIS then gets the words of a WhatsApp/email thread instead of a picture: a
 * cheap text model (or the local one) can draft a reply, and vision costs nothing.
 */
object ScreenText {
    private val recognizer by lazy { TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS) }

    suspend fun read(bitmap: Bitmap): String = suspendCancellableCoroutine { cont ->
        recognizer.process(InputImage.fromBitmap(bitmap, 0))
            .addOnSuccessListener { result ->
                val lines = result.textBlocks.flatMap { b -> b.lines.map { it.boundingBox?.top to it.text } }
                cont.resume(arrange(lines))
            }
            .addOnFailureListener { cont.resume("") }
    }

    /** Top-to-bottom reading order, status-bar noise dropped. Pure; unit-tested. */
    fun arrange(lines: List<Pair<Int?, String>>): String = lines
        .sortedBy { it.first ?: Int.MAX_VALUE }
        .map { it.second.trim() }
        .filter { it.isNotEmpty() && !STATUS.matches(it) }
        .joinToString("\n")

    private val STATUS = Regex("^(\\d{1,2}[:.]\\d{2}|\\d{1,3}%|[0-9]{1,3}G|LTE|VoLTE|4G\\+?|5G)$")
}
