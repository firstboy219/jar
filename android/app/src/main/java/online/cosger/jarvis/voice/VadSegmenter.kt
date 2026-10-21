package online.cosger.jarvis.voice

import java.io.ByteArrayOutputStream

/**
 * Turns per-frame speech probabilities (Silero VAD, 32 ms frames) into whole utterances. Pure, so the
 * timing rules are unit-tested without a microphone:
 *  - speech starts after [startFrames] frames ≥ [onThreshold]; [preRollFrames] frames before it are kept
 *    so the first syllable is not cut;
 *  - it ends after [endSilenceMs] below [offThreshold] (a natural pause), or at [maxMs];
 *  - utterances shorter than [minSpeechMs] of speech (coughs, clicks) are dropped.
 */
class VadSegmenter(
    private val frameMs: Int = 32,
    private val onThreshold: Float = 0.5f,
    private val offThreshold: Float = 0.35f,
    private val startFrames: Int = 2,
    private val preRollFrames: Int = 10,
    var endSilenceMs: Int = 900,
    private val minSpeechMs: Int = 300,
    private val maxMs: Int = 30_000,
) {
    sealed interface Event {
        data object Started : Event
        data class Ended(val pcm: ByteArray) : Event
    }

    private val preRoll = ArrayDeque<ByteArray>()
    private val current = ByteArrayOutputStream()
    private var inSpeech = false
    private var aboveRun = 0
    private var silenceMs = 0
    private var speechMs = 0
    private var totalMs = 0

    val speaking: Boolean get() = inSpeech

    fun feed(frame: ByteArray, probability: Float): Event? {
        if (!inSpeech) {
            preRoll.addLast(frame)
            while (preRoll.size > preRollFrames) preRoll.removeFirst()
            aboveRun = if (probability >= onThreshold) aboveRun + 1 else 0
            if (aboveRun >= startFrames) {
                inSpeech = true
                preRoll.forEach { current.write(it) }
                preRoll.clear()
                speechMs = aboveRun * frameMs
                totalMs = current.size() / 32
                silenceMs = 0
                return Event.Started
            }
            return null
        }
        current.write(frame)
        totalMs += frameMs
        if (probability >= offThreshold) {
            speechMs += frameMs
            silenceMs = 0
        } else {
            silenceMs += frameMs
        }
        if (silenceMs >= endSilenceMs || totalMs >= maxMs) return finish()
        return null
    }

    private fun finish(): Event? {
        val pcm = current.toByteArray()
        val enough = speechMs >= minSpeechMs
        reset()
        return if (enough) Event.Ended(pcm) else null
    }

    fun reset() {
        current.reset()
        preRoll.clear()
        inSpeech = false
        aboveRun = 0
        silenceMs = 0
        speechMs = 0
        totalMs = 0
    }
}
