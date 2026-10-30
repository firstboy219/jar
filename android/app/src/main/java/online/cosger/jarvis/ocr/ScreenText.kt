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

    /** A line of text and where it is on the picture (ADR-087 phase J: the guide puts a frame around the button to tap). */
    data class Line(val text: String, val left: Int, val top: Int, val right: Int, val bottom: Int)

    suspend fun read(bitmap: Bitmap): String = arrange(readLines(bitmap).map { it.top to it.text })

    suspend fun readLines(bitmap: Bitmap): List<Line> = suspendCancellableCoroutine { cont ->
        recognizer.process(InputImage.fromBitmap(bitmap, 0))
            .addOnSuccessListener { result ->
                cont.resume(result.textBlocks.flatMap { b -> b.lines.mapNotNull { l -> l.boundingBox?.let { r -> Line(l.text, r.left, r.top, r.right, r.bottom) } } })
            }
            .addOnFailureListener { cont.resume(emptyList()) }
    }

    /** The line the guide's target text is on: the same words, else the shortest line containing them, else the line most like them. Pure. */
    fun findTarget(lines: List<Line>, target: String): Line? {
        val t = norm(target)
        if (t.length < 2) return null
        lines.firstOrNull { norm(it.text) == t }?.let { return it }
        lines.filter { norm(it.text).contains(t) }.minByOrNull { it.text.length }?.let { return it }
        val words = t.split(' ').filter { it.length > 2 }.toSet()
        if (words.isEmpty()) return null
        return lines.map { it to norm(it.text).split(' ').count { w -> w in words } }.filter { it.second * 2 >= words.size && it.second > 0 }
            .maxByOrNull { it.second }?.first
    }

    private fun norm(s: String) = s.lowercase().replace(Regex("[^\\p{L}\\p{N} ]"), " ").replace(Regex("\\s+"), " ").trim()

    /** Top-to-bottom reading order, status-bar noise dropped. Pure; unit-tested. */
    fun arrange(lines: List<Pair<Int?, String>>): String = lines
        .sortedBy { it.first ?: Int.MAX_VALUE }
        .map { it.second.trim() }
        .filter { it.isNotEmpty() && !STATUS.matches(it) }
        .joinToString("\n")

    private val STATUS = Regex("^(\\d{1,2}[:.]\\d{2}|\\d{1,3}%|[0-9]{1,3}G|LTE|VoLTE|4G\\+?|5G)$")
}
