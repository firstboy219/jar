package online.cosger.jarvis.voice

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.util.ArrayDeque
import kotlin.math.min
import kotlin.math.sqrt

/** What the owner sees on the readiness indicator. */
enum class MicState {
    Muted,      // mic closed; JARVIS is not listening at all
    Preparing,  // mic open, connection to the recogniser not ready yet (audio is buffered meanwhile)
    Ready,      // listening — speak now
    Hearing,    // speech detected
    Paused,     // JARVIS is speaking; input ignored so it does not hear itself
    Error,
}

/**
 * Mute/unmute continuous listening (replaces push-to-talk). While unmuted the mic streams to Deepgram
 * and every finished utterance is emitted on [utterances]. While muted the mic is fully closed.
 *
 * No words are lost on the edges: the mic opens immediately and audio is buffered (up to [BUFFER_MS])
 * until the recogniser socket is open; the socket reconnects by itself with a fresh token.
 */
class ContinuousListener(
    private val scope: CoroutineScope,
    private val client: OkHttpClient = OkHttpClient(),
) : VoiceInput {
    private val _state = MutableStateFlow(MicState.Muted)
    override val state: StateFlow<MicState> = _state

    private val _level = MutableStateFlow(0f)
    override val level: StateFlow<Float> = _level

    private val _interim = MutableStateFlow("")
    override val interim: StateFlow<String> = _interim

    private val _utterances = MutableSharedFlow<UtteranceSegmenter.Output.Utterance>(extraBufferCapacity = 16)
    override val texts: SharedFlow<UtteranceSegmenter.Output.Utterance> = _utterances
    override val audio: SharedFlow<ByteArray> = MutableSharedFlow()

    private val _errors = MutableSharedFlow<String>(extraBufferCapacity = 4)
    override val errors: SharedFlow<String> = _errors

    private val segmenter = UtteranceSegmenter()
    private val pending = ArrayDeque<ByteString>()
    @Volatile private var ws: WebSocket? = null
    @Volatile private var socketOpen = false
    @Volatile private var paused = false
    @Volatile override var lastSpeechAtMs = 0L
        private set
    private var recorder: AudioRecord? = null
    private var jobs = mutableListOf<Job>()

    override val unmuted: Boolean get() = _state.value != MicState.Muted

    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO
    override fun unmute(config: suspend () -> SttConfig) {
        if (unmuted) return
        _state.value = MicState.Preparing
        lastSpeechAtMs = System.currentTimeMillis()
        segmenter.reset()
        synchronized(pending) { pending.clear() }

        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, CHUNK_BYTES * 8),
        )
        recorder = rec
        rec.startRecording()

        jobs += scope.launch(Dispatchers.IO) { pumpAudio(rec) }
        jobs += scope.launch { connectLoop(config) }
        jobs += scope.launch {
            while (isActive) { // Deepgram closes idle streams; keep it alive while we send no audio
                delay(4_000)
                if (paused || !socketOpen) ws?.send("""{"type":"KeepAlive"}""")
            }
        }
    }

    override fun mute() {
        if (!unmuted) return
        jobs.forEach { it.cancel() }
        jobs.clear()
        recorder?.run { runCatching { stop() }; release() }
        recorder = null
        ws?.send("""{"type":"CloseStream"}""")
        ws?.close(1000, "muted")
        ws = null
        socketOpen = false
        _level.value = 0f
        _interim.value = ""
        _state.value = MicState.Muted
    }

    /** While JARVIS speaks: drop mic audio so it does not transcribe itself. */
    override fun pause() {
        paused = true
        segmenter.reset()
        _interim.value = ""
        if (unmuted) _state.value = MicState.Paused
    }

    override fun resume() {
        paused = false
        if (unmuted) _state.value = if (socketOpen) MicState.Ready else MicState.Preparing
    }

    private suspend fun pumpAudio(rec: AudioRecord) {
        val buf = ByteArray(CHUNK_BYTES)
        while (scope.isActive && recorder === rec) {
            val n = rec.read(buf, 0, buf.size)
            if (n <= 0) continue
            _level.value = if (paused) 0f else rms(buf, n)
            if (paused) continue
            val chunk = buf.toByteString(0, n)
            val socket = ws
            if (socketOpen && socket != null) {
                socket.send(chunk)
            } else synchronized(pending) {
                pending.addLast(chunk)
                while (pending.size > BUFFER_MS / 100) pending.removeFirst()
            }
        }
    }

    private suspend fun connectLoop(config: suspend () -> SttConfig) {
        var attempt = 0
        while (scope.isActive && unmuted) {
            val cfg = try {
                config()
            } catch (e: Exception) {
                _state.value = MicState.Error
                _errors.tryEmit(e.message ?: "Token suara gagal diambil")
                delay(min(30_000L, 2_000L shl min(attempt++, 4)))
                continue
            }
            val closed = kotlinx.coroutines.CompletableDeferred<Unit>()
            ws = client.newWebSocket(
                Request.Builder().url(cfg.url()).header("Authorization", "Bearer ${cfg.token}").build(),
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        attempt = 0
                        synchronized(pending) {
                            while (pending.isNotEmpty()) webSocket.send(pending.removeFirst())
                        }
                        socketOpen = true
                        if (!paused) _state.value = MicState.Ready
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) = onResult(text)
                    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { closed.complete(Unit) }
                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { closed.complete(Unit) }
                },
            )
            closed.await()
            socketOpen = false
            ws = null
            if (!unmuted) return
            _state.value = if (paused) MicState.Paused else MicState.Preparing
            delay(min(10_000L, 500L shl min(attempt++, 4)))
        }
    }

    private fun onResult(text: String) {
        if (paused) return
        for (out in segmenter.feed(text)) when (out) {
            UtteranceSegmenter.Output.SpeechStarted -> _state.value = MicState.Hearing
            is UtteranceSegmenter.Output.Interim -> {
                _interim.value = out.text
                _state.value = MicState.Hearing
                lastSpeechAtMs = System.currentTimeMillis()
            }
            is UtteranceSegmenter.Output.Utterance -> {
                _interim.value = ""
                _state.value = MicState.Ready
                lastSpeechAtMs = System.currentTimeMillis()
                _utterances.tryEmit(out)
            }
        }
    }

    private fun rms(buf: ByteArray, n: Int): Float {
        var sum = 0.0
        var i = 0
        while (i + 1 < n) {
            val s = (buf[i].toInt() and 0xff) or (buf[i + 1].toInt() shl 8)
            sum += s.toDouble() * s
            i += 2
        }
        val rms = sqrt(sum / (n / 2).coerceAtLeast(1)) / 32768.0
        return (rms * 4).coerceIn(0.0, 1.0).toFloat()
    }

    companion object {
        const val SAMPLE_RATE = 16_000
        const val CHUNK_BYTES = SAMPLE_RATE * 2 / 10 // 100 ms of 16-bit mono
        const val BUFFER_MS = 8_000
    }
}
