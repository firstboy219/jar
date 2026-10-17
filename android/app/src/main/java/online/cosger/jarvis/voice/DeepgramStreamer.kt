package online.cosger.jarvis.voice

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
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
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import kotlin.math.sqrt

/**
 * FS-101 client-side audio streaming: AudioRecord (Linear16, 16 kHz, mono) → 100 ms chunks →
 * Deepgram live WSS, KeepAlive every 5 s. Push-to-talk: start() on press, finish() on release
 * returns the final transcript (interim text is exposed live for the UI).
 */
class DeepgramStreamer(
    private val scope: CoroutineScope,
    private val client: OkHttpClient = OkHttpClient(),
    private val model: String = "nova-3",
    private val language: String = "id",
) {
    private val _interim = MutableStateFlow("")
    val interim: StateFlow<String> = _interim

    /** 0..1 microphone level for the orb animation. */
    private val _level = MutableStateFlow(0f)
    val level: StateFlow<Float> = _level

    private var ws: WebSocket? = null
    private var recorder: AudioRecord? = null
    private var pump: Job? = null
    private var keepAlive: Job? = null
    private val finals = StringBuilder()
    private var closed = CompletableDeferred<Unit>()

    @SuppressLint("MissingPermission") // caller checks RECORD_AUDIO before start()
    fun start(accessToken: String) {
        cancel()
        finals.clear()
        _interim.value = ""
        closed = CompletableDeferred()
        val url = "wss://api.deepgram.com/v1/listen?model=$model&language=$language&encoding=linear16" +
            "&sample_rate=$SAMPLE_RATE&channels=1&interim_results=true&smart_format=true&endpointing=300"
        ws = client.newWebSocket(
            Request.Builder().url(url).header("Authorization", "Bearer $accessToken").build(),
            object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, text: String) = onResult(text)
                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { closed.complete(Unit) }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { closed.complete(Unit) }
            },
        )

        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, CHUNK_BYTES * 4),
        )
        recorder = rec
        rec.startRecording()
        pump = scope.launch(Dispatchers.IO) {
            val buf = ByteArray(CHUNK_BYTES)
            while (isActive) {
                val n = rec.read(buf, 0, buf.size)
                if (n <= 0) continue
                ws?.send(buf.toByteString(0, n))
                _level.value = rms(buf, n)
            }
        }
        keepAlive = scope.launch {
            while (isActive) {
                delay(5_000)
                ws?.send("""{"type":"KeepAlive"}""")
            }
        }
    }

    /** Stop recording, flush Deepgram, and return everything it finalized. */
    suspend fun finish(): String {
        stopMic()
        ws?.send("""{"type":"Finalize"}""")
        delay(FLUSH_MS) // Deepgram answers Finalize with the last is_final result(s)
        ws?.send("""{"type":"CloseStream"}""")
        withTimeoutOrNull(2_000) { closed.await() }
        keepAlive?.cancel()
        ws = null
        val text = finals.toString().trim().ifEmpty { _interim.value.trim() }
        _interim.value = ""
        return text
    }

    fun cancel() {
        stopMic()
        keepAlive?.cancel()
        ws?.cancel()
        ws = null
        _interim.value = ""
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
        val o = runCatching { Json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        if (o["type"]?.jsonPrimitive?.content != "Results") return
        val transcript = o["channel"]?.jsonObject?.get("alternatives")?.jsonArray?.firstOrNull()
            ?.jsonObject?.get("transcript")?.jsonPrimitive?.content.orEmpty()
        val isFinal = o["is_final"]?.jsonPrimitive?.booleanOrNull == true
        if (isFinal) {
            if (transcript.isNotBlank()) finals.append(transcript).append(' ')
            _interim.value = finals.toString()
        } else {
            _interim.value = finals.toString() + transcript
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
        const val FLUSH_MS = 700L
    }
}
