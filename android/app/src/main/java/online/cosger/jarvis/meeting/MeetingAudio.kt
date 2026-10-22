package online.cosger.jarvis.meeting

import kotlin.math.log10
import kotlin.math.sqrt

/**
 * Pure helpers of the meeting recorder (unit-tested). The recorder captures PCM continuously with
 * AudioRecord and encodes AAC with MediaCodec: no gap between 60-second chunks (the old MediaRecorder
 * stop/start lost ~0.2 s of speech at every boundary), and the level of the room is known live.
 */
object Adts {
    const val SAMPLE_RATE = 16_000
    const val SAMPLES_PER_FRAME = 1024
    /** 60 s of audio per uploaded chunk, cut on a frame boundary. */
    const val FRAMES_PER_CHUNK = 60 * SAMPLE_RATE / SAMPLES_PER_FRAME

    /** 7-byte ADTS header for one AAC-LC frame of [payload] bytes (16 kHz, mono): the .aac chunks play and concatenate anywhere. */
    fun header(payload: Int): ByteArray {
        val len = payload + 7
        val profile = 1       // AAC-LC (object type 2, minus 1)
        val freqIndex = 8     // 16000 Hz
        val channels = 1
        return byteArrayOf(
            0xFF.toByte(), 0xF1.toByte(),
            ((profile shl 6) or (freqIndex shl 2) or (channels shr 2)).toByte(),
            (((channels and 3) shl 6) or (len shr 11)).toByte(),
            ((len shr 3) and 0xFF).toByte(),
            (((len and 7) shl 5) or 0x1F).toByte(),
            0xFC.toByte(),
        )
    }

    /** Frame length (header included) read back from a header — for tests and sanity checks. */
    fun frameLength(h: ByteArray): Int =
        ((h[3].toInt() and 3) shl 11) or ((h[4].toInt() and 0xFF) shl 3) or ((h[5].toInt() and 0xFF) ushr 5)
}

object RoomLevel {
    /** Below this the room is practically silent (≈ −50 dBFS): nobody is talking near the phone. */
    const val QUIET_RMS = 0.0032f
    /** Seconds of near-silence after which the app warns "move the phone closer". */
    const val WARN_AFTER_S = 20

    fun rms(pcm: ByteArray, bytes: Int): Float {
        var sum = 0.0
        var n = 0
        var i = 0
        while (i + 1 < bytes) {
            val s = (pcm[i].toInt() and 0xFF) or (pcm[i + 1].toInt() shl 8)
            val v = s.toShort() / 32768.0
            sum += v * v
            n++
            i += 2
        }
        return if (n == 0) 0f else sqrt(sum / n).toFloat()
    }

    /** 0..1 for a level bar: −60 dBFS = empty, −10 dBFS = full. */
    fun meter(rms: Float): Float = if (rms <= 0f) 0f else ((20 * log10(rms.toDouble()) + 60) / 50).coerceIn(0.0, 1.0).toFloat()

    /** Consecutive quiet seconds, given the previous count and one more [seconds]-long reading. */
    fun quietSeconds(previous: Float, rms: Float, seconds: Float): Float =
        if (rms < QUIET_RMS) previous + seconds else 0f
}
