package online.cosger.jarvis.voice

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
import kotlin.math.sqrt

/**
 * Mute/unmute listening where the PHONE decides what is speech (Silero VAD) and only sends finished
 * utterances to jarvis-core, which transcribes them with the owner's engine (local Whisper or Groq).
 * Nothing is sent while nobody speaks — cheaper, more private, and the CPU on the server stays free.
 */
class VadListener(private val context: Context, private val scope: CoroutineScope) : VoiceInput {
    private val _state = MutableStateFlow(MicState.Muted)
    override val state: StateFlow<MicState> = _state
    private val _level = MutableStateFlow(0f)
    override val level: StateFlow<Float> = _level
    private val _interim = MutableStateFlow("")
    override val interim: StateFlow<String> = _interim
    override val texts = MutableSharedFlow<UtteranceSegmenter.Output.Utterance>()
    private val _audio = MutableSharedFlow<ByteArray>(extraBufferCapacity = 8)
    override val audio: SharedFlow<ByteArray> = _audio
    private val _errors = MutableSharedFlow<String>(extraBufferCapacity = 4)
    override val errors: SharedFlow<String> = _errors

    @Volatile private var paused = false
    @Volatile override var lastSpeechAtMs = 0L
        private set
    private var recorder: AudioRecord? = null
    private var job: Job? = null
    private var vad: SileroVad? = null
    private val segmenter = VadSegmenter()

    override val unmuted: Boolean get() = _state.value != MicState.Muted

    /** End-of-speech pause the server suggests (same knob as Deepgram's utterance_end). */
    var endSilenceMs: Int
        get() = segmenter.endSilenceMs
        set(v) { segmenter.endSilenceMs = v.coerceIn(500, 2_500) }

    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO
    override fun unmute(config: suspend () -> SttConfig) {
        if (unmuted) return
        _state.value = MicState.Preparing
        lastSpeechAtMs = System.currentTimeMillis()
        val model = runCatching { vad ?: SileroVad(context).also { vad = it } }.getOrElse {
            _state.value = MicState.Error
            _errors.tryEmit("Pendeteksi suara gagal dimuat: ${it.message}")
            return
        }
        model.reset()
        segmenter.reset()
        val minBuf = AudioRecord.getMinBufferSize(SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, SR, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, SileroVad.FRAME_BYTES * 8))
        recorder = rec
        rec.startRecording()
        _state.value = if (paused) MicState.Paused else MicState.Ready
        job = scope.launch(Dispatchers.Default) { pump(rec, model) }
    }

    private fun pump(rec: AudioRecord, model: SileroVad) {
        val frame = ByteArray(SileroVad.FRAME_BYTES)
        while (scope.isActive && recorder === rec) {
            var read = 0
            while (read < frame.size) {
                val n = rec.read(frame, read, frame.size - read)
                if (n <= 0) break
                read += n
            }
            if (read < frame.size) continue
            if (paused) {
                _level.value = 0f
                continue
            }
            _level.value = rms(frame)
            val p = model.probability(frame)
            when (val ev = segmenter.feed(frame.copyOf(), p)) {
                VadSegmenter.Event.Started -> {
                    _state.value = MicState.Hearing
                    lastSpeechAtMs = System.currentTimeMillis()
                }
                is VadSegmenter.Event.Ended -> {
                    lastSpeechAtMs = System.currentTimeMillis()
                    _state.value = MicState.Ready
                    _interim.value = "…"
                    _audio.tryEmit(ev.pcm)
                }
                null -> if (segmenter.speaking) lastSpeechAtMs = System.currentTimeMillis()
                else if (_state.value == MicState.Hearing) _state.value = MicState.Ready
            }
        }
    }

    override fun mute() {
        if (!unmuted) return
        job?.cancel()
        job = null
        recorder?.run { runCatching { stop() }; release() }
        recorder = null
        segmenter.reset()
        _level.value = 0f
        _interim.value = ""
        _state.value = MicState.Muted
    }

    override fun pause() {
        paused = true
        segmenter.reset()
        if (unmuted) _state.value = MicState.Paused
    }

    override fun resume() {
        paused = false
        if (unmuted) _state.value = MicState.Ready
    }

    override fun setInterim(text: String) { _interim.value = text }

    private fun rms(buf: ByteArray): Float {
        var sum = 0.0
        var i = 0
        while (i + 1 < buf.size) {
            val s = (buf[i].toInt() and 0xff) or (buf[i + 1].toInt() shl 8)
            sum += s.toDouble() * s
            i += 2
        }
        return (sqrt(sum / (buf.size / 2)) / 32768.0 * 4).coerceIn(0.0, 1.0).toFloat()
    }

    companion object {
        const val SR = 16_000
    }
}
