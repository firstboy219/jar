package online.cosger.jarvis.voice

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.nio.FloatBuffer

/**
 * "Hey Jarvis" on the phone (openWakeWord: melspectrogram → speech embedding → hey_jarvis, ONNX; the
 * pretrained models are CC BY-NC-SA — fine for this personal assistant). Runs every 80 ms on 16 kHz audio;
 * nothing is sent anywhere until the phrase is heard. Validated 2026-10-21: "Hey Jarvis" (English
 * pronunciation) 0.999, ordinary Indonesian sentences < 0.01; an Indonesian-accented synthetic voice
 * scored 0.25, hence the adjustable [threshold].
 */
class WakeWordModel(context: Context) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private fun load(ctx: Context, name: String) = env.createSession(ctx.assets.open(name).use { it.readBytes() },
        OrtSession.SessionOptions().apply { setIntraOpNumThreads(1) })
    private val mel = load(context, "melspectrogram.onnx")
    private val emb = load(context, "embedding_model.onnx")
    private val ww = load(context, "hey_jarvis_v0.1.onnx")
    private val wwInput = ww.inputNames.first()

    private val raw = FloatArray(RAW)                       // last 1760 samples (1280 new + 480 overlap)
    private val melBuf = ArrayDeque<FloatArray>()            // mel frames, 32 each
    private val features = ArrayDeque<FloatArray>()          // 96-d embeddings

    init { reset() }

    fun reset() {
        raw.fill(0f)
        melBuf.clear(); repeat(76) { melBuf.addLast(FloatArray(32) { 1f }) }
        features.clear()
    }

    /** [chunk]: exactly [CHUNK] PCM16 samples. Returns the wake-word score 0..1 (0 until warmed up). */
    fun score(chunk: ShortArray): Float {
        System.arraycopy(raw, CHUNK, raw, 0, RAW - CHUNK)
        for (i in 0 until CHUNK) raw[RAW - CHUNK + i] = chunk[i].toFloat()
        OnnxTensor.createTensor(env, FloatBuffer.wrap(raw), longArrayOf(1, RAW.toLong())).use { input ->
            mel.run(mapOf("input" to input)).use { out ->
                @Suppress("UNCHECKED_CAST")
                val frames = (out[0].value as Array<Array<Array<FloatArray>>>)[0][0]
                for (f in frames) melBuf.addLast(FloatArray(32) { f[it] / 10f + 2f })
            }
        }
        while (melBuf.size > 76) melBuf.removeFirst()
        val window = FloatArray(76 * 32)
        melBuf.forEachIndexed { i, f -> System.arraycopy(f, 0, window, i * 32, 32) }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(window), longArrayOf(1, 76, 32, 1)).use { input ->
            emb.run(mapOf("input_1" to input)).use { out ->
                @Suppress("UNCHECKED_CAST")
                features.addLast((out[0].value as Array<Array<Array<FloatArray>>>)[0][0][0].copyOf())
            }
        }
        while (features.size > 16) features.removeFirst()
        if (features.size < 16) return 0f
        val x = FloatArray(16 * 96)
        features.forEachIndexed { i, f -> System.arraycopy(f, 0, x, i * 96, 96) }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(x), longArrayOf(1, 16, 96)).use { input ->
            ww.run(mapOf(wwInput to input)).use { out ->
                @Suppress("UNCHECKED_CAST")
                return (out[0].value as Array<FloatArray>)[0][0]
            }
        }
    }

    override fun close() { mel.close(); emb.close(); ww.close() }

    companion object {
        const val CHUNK = 1280
        const val RAW = CHUNK + 480
    }
}

/** Listens for "Hey Jarvis" while the main mic is muted; [heard] fires once per detection. */
class WakeListener(private val context: Context, private val scope: CoroutineScope) {
    private val _active = MutableStateFlow(false)
    val active: StateFlow<Boolean> = _active
    private val _heard = MutableSharedFlow<Float>(extraBufferCapacity = 1)
    val heard: SharedFlow<Float> = _heard
    @Volatile var threshold = 0.5f
    private var model: WakeWordModel? = null
    private var recorder: AudioRecord? = null
    private var job: Job? = null

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        if (_active.value) return true
        val m = runCatching { model ?: WakeWordModel(context).also { model = it } }.getOrNull() ?: return false
        m.reset()
        val min = AudioRecord.getMinBufferSize(16_000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = runCatching {
            AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, 16_000, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(min, WakeWordModel.CHUNK * 2 * 4))
        }.getOrNull() ?: return false
        recorder = rec
        rec.startRecording()
        _active.value = true
        job = scope.launch(Dispatchers.Default) {
            val buf = ShortArray(WakeWordModel.CHUNK)
            var cooldown = 0
            while (isActive && recorder === rec) {
                var read = 0
                while (read < buf.size) {
                    val n = rec.read(buf, read, buf.size - read)
                    if (n <= 0) break
                    read += n
                }
                if (read < buf.size) continue
                val s = m.score(buf)
                if (cooldown > 0) { cooldown--; continue }
                if (s >= threshold) {
                    cooldown = 25 // ~2 s
                    _heard.tryEmit(s)
                }
            }
        }
        return true
    }

    fun stop() {
        job?.cancel(); job = null
        recorder?.run { runCatching { stop() }; release() }
        recorder = null
        _active.value = false
    }
}
