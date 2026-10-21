package online.cosger.jarvis.voice

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import java.nio.FloatBuffer
import java.nio.LongBuffer

/**
 * Silero VAD v5 (MIT, 2.3 MB, < 1 ms per 32 ms frame on a phone CPU). Each call takes [FRAME] new
 * samples at 16 kHz plus the last [CONTEXT] samples of the previous frame, and keeps its recurrent state.
 */
class SileroVad(context: Context) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession = env.createSession(
        context.assets.open("silero_vad.onnx").use { it.readBytes() },
        OrtSession.SessionOptions().apply { setIntraOpNumThreads(1); setInterOpNumThreads(1) },
    )
    private var state = FloatArray(2 * 1 * 128)
    private val window = FloatArray(CONTEXT + FRAME)
    private val sr = OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(16_000L)), longArrayOf())

    /** [pcm]: [FRAME] 16-bit little-endian samples. Returns speech probability 0..1. */
    fun probability(pcm: ByteArray): Float {
        System.arraycopy(window, FRAME, window, 0, CONTEXT)
        for (i in 0 until FRAME) {
            val s = (pcm[2 * i].toInt() and 0xff) or (pcm[2 * i + 1].toInt() shl 8)
            window[CONTEXT + i] = s / 32768f
        }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(window), longArrayOf(1, (CONTEXT + FRAME).toLong())).use { input ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(state), longArrayOf(2, 1, 128)).use { st ->
                session.run(mapOf("input" to input, "state" to st, "sr" to sr)).use { out ->
                    @Suppress("UNCHECKED_CAST")
                    val prob = (out[0].value as Array<FloatArray>)[0][0]
                    @Suppress("UNCHECKED_CAST")
                    val next = out[1].value as Array<Array<FloatArray>>
                    var k = 0
                    for (a in next) for (b in a) for (v in b) state[k++] = v
                    return prob
                }
            }
        }
    }

    fun reset() {
        state = FloatArray(2 * 1 * 128)
        window.fill(0f)
    }

    override fun close() {
        sr.close()
        session.close()
    }

    companion object {
        const val FRAME = 512    // 32 ms at 16 kHz
        const val CONTEXT = 64
        const val FRAME_BYTES = FRAME * 2
    }
}
