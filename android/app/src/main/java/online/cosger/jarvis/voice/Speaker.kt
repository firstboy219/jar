package online.cosger.jarvis.voice

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

/**
 * On-device TTS (Indonesian) with a queue. [speaking] lets the listener pause the mic so JARVIS
 * does not hear itself; [onDone] callbacks tell the server a report was actually said out loud.
 */
class Speaker(context: Context) {
    private var ready = false
    private val _speaking = MutableStateFlow(false)
    val speaking: StateFlow<Boolean> = _speaking
    private val done = ConcurrentHashMap<String, () -> Unit>()
    private val queued = ConcurrentHashMap.newKeySet<String>()
    private var seq = 0

    private val tts = TextToSpeech(context.applicationContext) { status ->
        ready = status == TextToSpeech.SUCCESS
        if (ready) setLanguage()
    }.apply {
        setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String) { _speaking.value = true }
            override fun onDone(utteranceId: String) = finished(utteranceId)
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String) = finished(utteranceId)
            override fun onStop(utteranceId: String, interrupted: Boolean) = finished(utteranceId)
        })
    }

    private fun finished(id: String) {
        queued.remove(id)
        done.remove(id)?.invoke()
        if (queued.isEmpty()) _speaking.value = false
    }

    private fun setLanguage() {
        val id = Locale.forLanguageTag("id-ID")
        if (tts.isLanguageAvailable(id) >= TextToSpeech.LANG_AVAILABLE) tts.language = id
    }

    /** Say [text] after whatever is already queued; [onDone] runs once it has been spoken (or skipped). */
    fun say(text: String, onDone: (() -> Unit)? = null) {
        val clean = stripMarkdown(text)
        if (!ready || clean.isBlank()) {
            onDone?.invoke()
            return
        }
        val id = "j${seq++}"
        onDone?.let { done[id] = it }
        queued += id
        _speaking.value = true
        tts.speak(clean, TextToSpeech.QUEUE_ADD, null, id)
    }

    fun stop() {
        if (ready) tts.stop()
        queued.toList().forEach(::finished)
    }

    fun shutdown() = tts.shutdown()

    companion object {
        /** Spoken text should not read out markdown symbols or code. */
        fun stripMarkdown(text: String): String = text
            .replace(Regex("```.*?```", RegexOption.DOT_MATCHES_ALL), " (kode) ")
            .replace(Regex("`([^`]*)`"), "$1")
            .replace(Regex("\\*\\*|__|[*_#>]"), "")
            .replace(Regex("^\\s*[-•]\\s+", RegexOption.MULTILINE), "")
            .replace(Regex("\\[([^]]+)]\\([^)]+\\)"), "$1")
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}
