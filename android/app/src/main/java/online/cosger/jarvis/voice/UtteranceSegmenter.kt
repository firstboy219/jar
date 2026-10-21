package online.cosger.jarvis.voice

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Turns Deepgram's continuous live results into whole utterances.
 *
 * Deepgram sends interim results, `is_final` segments, `speech_final` when it detects the end of
 * speech, and `UtteranceEnd` after a silence gap (a backup when speech_final is missed in noise).
 * We accumulate final segments and emit one utterance at the first end signal.
 */
class UtteranceSegmenter {
    sealed interface Output {
        data object SpeechStarted : Output
        data class Interim(val text: String) : Output
        /** A finished utterance with how sure recognition was and how many distinct voices it heard. */
        data class Utterance(val text: String, val confidence: Double? = null, val speakers: Int = 1) : Output
    }

    private val finals = StringBuilder()
    private var pendingInterim = ""
    private val confidences = mutableListOf<Double>()
    private val speakerIds = mutableSetOf<Int>()

    val partial: String get() = (finals.toString() + pendingInterim).trim()

    fun feed(message: String): List<Output> {
        val o = runCatching { Json.parseToJsonElement(message).jsonObject }.getOrNull() ?: return emptyList()
        return when (o["type"]?.jsonPrimitive?.content) {
            "SpeechStarted" -> listOf(Output.SpeechStarted)
            "UtteranceEnd" -> flush()
            "Results" -> {
                val alt = o["channel"]?.jsonObject?.get("alternatives")?.jsonArray?.firstOrNull()?.jsonObject
                val transcript = alt?.get("transcript")?.jsonPrimitive?.content.orEmpty().trim()
                val isFinal = o["is_final"]?.jsonPrimitive?.booleanOrNull == true
                val speechFinal = o["speech_final"]?.jsonPrimitive?.booleanOrNull == true
                val out = mutableListOf<Output>()
                if (isFinal) {
                    if (transcript.isNotEmpty()) {
                        finals.append(transcript).append(' ')
                        alt?.get("confidence")?.jsonPrimitive?.doubleOrNull?.let { confidences += it }
                        alt?.get("words")?.jsonArray?.forEach { w ->
                            w.jsonObject["speaker"]?.jsonPrimitive?.intOrNull?.let { speakerIds += it }
                        }
                    }
                    pendingInterim = ""
                } else {
                    pendingInterim = transcript
                }
                if (partial.isNotEmpty()) out += Output.Interim(partial)
                if (speechFinal) out += flush()
                out
            }
            else -> emptyList()
        }
    }

    /** End of an utterance: emit what was heard (nothing if it was only noise) and start fresh. */
    fun flush(): List<Output> {
        val text = finals.toString().trim()
        val confidence = confidences.takeIf { it.isNotEmpty() }?.average()
        val speakers = speakerIds.size.coerceAtLeast(1)
        reset()
        return if (text.isEmpty()) emptyList() else listOf(Output.Utterance(text, confidence, speakers))
    }

    fun reset() {
        finals.clear()
        pendingInterim = ""
        confidences.clear()
        speakerIds.clear()
    }
}
