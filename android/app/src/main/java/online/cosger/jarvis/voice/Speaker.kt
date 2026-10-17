package online.cosger.jarvis.voice

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

/** On-device TTS (Indonesian): zero cost and no network round trip for the reply audio. */
class Speaker(context: Context) {
    private var ready = false
    private val tts = TextToSpeech(context.applicationContext) { status ->
        ready = status == TextToSpeech.SUCCESS
        if (ready) setLanguage()
    }

    private fun setLanguage() {
        val id = Locale.forLanguageTag("id-ID")
        if (tts.isLanguageAvailable(id) >= TextToSpeech.LANG_AVAILABLE) tts.language = id
    }

    fun speak(text: String) {
        if (!ready || text.isBlank()) return
        tts.speak(stripMarkdown(text), TextToSpeech.QUEUE_FLUSH, null, "jarvis-reply")
    }

    fun stop() {
        if (ready) tts.stop()
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
