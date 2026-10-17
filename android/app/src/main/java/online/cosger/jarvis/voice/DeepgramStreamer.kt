package online.cosger.jarvis.voice

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import kotlin.math.sqrt

/** Speech-to-text settings + short-lived token, both handed out by jarvis-core. */
data class SttConfig(
    val token: String,
    val model: String = "nova-2",
    val language: String = "id",
    val keywords: List<String> = emptyList(),
    val expiresAtMs: Long = Long.MAX_VALUE,
) {
    fun isFresh(nowMs: Long = System.currentTimeMillis()) = nowMs < expiresAtMs - 15_000

    fun url(): HttpUrl = "https://api.deepgram.com/v1/listen".toHttpUrl().newBuilder().apply {
        addQueryParameter("model", model)
        addQueryParameter("language", language)
        addQueryParameter("encoding", "linear16")
        addQueryParameter("sample_rate", DeepgramStreamer.SAMPLE_RATE.toString())
        addQueryParameter("channels", "1")
        addQueryParameter("interim_results", "true")
        addQueryParameter("smart_format", "true")
        // Push-to-talk decides when speech ends; long endpointing avoids splitting mid-sentence pauses.
        addQueryParameter("endpointing", "800")
        keywords.forEach {
            // nova-3 uses keyterm prompting; older models use keyword boosting.
            if (model.startsWith("nova-3")) addQueryParameter("keyterm", it)
            else addQueryParameter("keywords", "$it:2")
        }
    }.build()
}

/**
 * FS-101 push-to-talk: AudioRecord (Linear16, 16 kHz, mono) in 100 ms chunks → Deepgram live WSS.
 *
 * Nothing the owner says is lost:
 *  - recording starts the instant the button goes down; chunks are buffered until the socket is ready
 *    (the token is normally prefetched, so that wait is ~0),
 *  - after release it keeps recording [TAIL_MS] so the last syllable is not clipped,
 *  - it sends Finalize and waits for Deepgram's `from_finalize` result before closing.
 */
class DeepgramStreamer(
    private val scope: CoroutineScope,
    private val client: OkHttpClient = OkHttpClient(),
) {
    private val _interim = MutableStateFlow("")
    val interim: StateFlow<String> = _interim

    /** 0..1 microphone level for the orb animation. */
    private val _level = MutableStateFlow(0f)
    val level: StateFlow<Float> = _level

    private var ws: WebSocket? = null
    private var recorder: AudioRecord? = null
    private var pump: Job? = null
    private var sender: Job? = null
    private var keepAlive: Job? = null
    private var chunks = Channel<ByteString>(Channel.UNLIMITED)
    private val finals = StringBuilder()
    private var flushed = CompletableDeferred<Unit>()
    private var closed = CompletableDeferred<Unit>()
    @Volatile private var failure: String? = null

    /** Start recording now; [config] is awaited in parallel (usually already cached). */
    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO before start()
    fun start(config: suspend () -> SttConfig) {
        cancel()
        finals.clear()
        _interim.value = ""
        failure = null
        flushed = CompletableDeferred()
        closed = CompletableDeferred()
        chunks = Channel(Channel.UNLIMITED)

        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, CHUNK_BYTES * 8),
        )
        recorder = rec
        rec.startRecording()
        val out = chunks
        pump = scope.launch(Dispatchers.IO) {
            val buf = ByteArray(CHUNK_BYTES)
            while (isActive) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                out.trySend(buf.toByteString(0, n))
                _level.value = rms(buf, n)
            }
        }

        sender = scope.launch(Dispatchers.IO) {
            val cfg = try {
                config()
            } catch (e: Exception) {
                failure = e.message ?: "Token suara gagal diambil"
                flushed.complete(Unit); closed.complete(Unit)
                return@launch
            }
            val socket = client.newWebSocket(
                Request.Builder().url(cfg.url()).header("Authorization", "Bearer ${cfg.token}").build(),
                object : WebSocketListener() {
                    override fun onMessage(webSocket: WebSocket, text: String) = onResult(text)
                    override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { done() }
                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                        if (!flushed.isCompleted) failure = "Koneksi suara terputus"
                        done()
                    }
                },
            )
            ws = socket
            // OkHttp queues frames until the handshake completes, so buffered audio is never dropped.
            for (chunk in out) socket.send(chunk)
            socket.send("""{"type":"Finalize"}""")
        }

        keepAlive = scope.launch {
            while (isActive) {
                delay(5_000)
                ws?.send("""{"type":"KeepAlive"}""")
            }
        }
    }

    /** Stop after a short tail, flush Deepgram, and return the final transcript ("" if nothing heard). */
    suspend fun finish(): String {
        delay(TAIL_MS) // keep listening briefly: people release the button on their last syllable
        stopMic()
        chunks.close() // sender drains what's left, then sends Finalize
        withTimeoutOrNull(FLUSH_TIMEOUT_MS) { flushed.await() }
        ws?.send("""{"type":"CloseStream"}""")
        withTimeoutOrNull(2_000) { closed.await() }
        keepAlive?.cancel()
        ws = null
        val text = finals.toString().trim().ifEmpty { _interim.value.trim() }
        _interim.value = ""
        failure?.let { if (text.isEmpty()) throw IllegalStateException(it) }
        return text
    }

    fun cancel() {
        stopMic()
        chunks.close()
        sender?.cancel()
        keepAlive?.cancel()
        ws?.cancel()
        ws = null
        _interim.value = ""
    }

    private fun done() {
        flushed.complete(Unit)
        closed.complete(Unit)
    }

    private fun stopMic() {
        pump?.cancel()
        pump = null
        recorder?.run {
            runCatching { stop() }
            release()
        }
        recorder = null
        _level.value = 0f
    }

    private fun onResult(text: String) {
        val r = parseResult(text) ?: return
        if (r.isFinal) {
            if (r.transcript.isNotBlank()) finals.append(r.transcript).append(' ')
            _interim.value = finals.toString()
        } else {
            _interim.value = finals.toString() + r.transcript
        }
        if (r.fromFinalize) flushed.complete(Unit)
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

    data class Result(val transcript: String, val isFinal: Boolean, val fromFinalize: Boolean)

    companion object {
        const val SAMPLE_RATE = 16_000
        const val CHUNK_BYTES = SAMPLE_RATE * 2 / 10 // 100 ms of 16-bit mono
        const val TAIL_MS = 300L
        const val FLUSH_TIMEOUT_MS = 4_000L

        fun parseResult(text: String): Result? {
            val o = runCatching { Json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return null
            if (o["type"]?.jsonPrimitive?.content != "Results") return null
            val transcript = o["channel"]?.jsonObject?.get("alternatives")?.jsonArray?.firstOrNull()
                ?.jsonObject?.get("transcript")?.jsonPrimitive?.content.orEmpty()
            return Result(
                transcript = transcript,
                isFinal = o["is_final"]?.jsonPrimitive?.booleanOrNull == true,
                fromFinalize = o["from_finalize"]?.jsonPrimitive?.booleanOrNull == true,
            )
        }
    }
}
