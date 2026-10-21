package online.cosger.jarvis.meeting

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.net.ConsoleApi
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s
import java.io.File

/**
 * Records a meeting from the phone's microphone (Android does not let apps capture Zoom/Meet/WhatsApp
 * call audio, so put the phone on the table or use the speaker). The recording is cut into 60-second
 * Opus files; each is uploaded as soon as it is finished and retried until the server has it, so a
 * dropped connection loses nothing. Chunks are deleted from the phone once uploaded.
 */
class MeetingRecorder(private val context: Context, private val api: ConsoleApi) {
    data class State(
        val meetingId: String? = null,
        val title: String = "",
        val recording: Boolean = false,
        val paused: Boolean = false,
        val startedAtMs: Long = 0,
        val pausedMs: Long = 0,
        val chunks: Int = 0,
        val uploaded: Int = 0,
        val finishing: Boolean = false,
        val error: String? = null,
    ) {
        fun elapsedS(now: Long = System.currentTimeMillis()): Long =
            if (startedAtMs == 0L) 0 else (now - startedAtMs - pausedMs) / 1000
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private var recorder: MediaRecorder? = null
    private var rotator: Job? = null
    private var pausedAt = 0L
    private val dir: File get() = File(context.filesDir, "meetings/${_state.value.meetingId}")

    val extension: String get() = if (Build.VERSION.SDK_INT >= 29) "ogg" else "m4a"

    suspend fun start(title: String, confidential: Boolean): Result<String> = runCatching {
        val m = api.post("/api/v1/meetings", buildJsonObject {
            put("title", title); put("confidential", confidential); put("consent", true)
        }).obj()
        val id = m.s("id")
        _state.value = State(meetingId = id, title = m.s("title"), recording = true, startedAtMs = System.currentTimeMillis())
        dir.mkdirs()
        MeetingService.start(context)
        beginChunk()
        rotator = scope.launch {
            while (isActive) {
                delay(CHUNK_MS)
                if (_state.value.recording && !_state.value.paused) { endChunk(); beginChunk() }
            }
        }
        id
    }

    private fun beginChunk() {
        val n = _state.value.chunks
        val file = File(dir, "chunk-%05d.$extension".format(n))
        val r = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(context) else @Suppress("DEPRECATION") MediaRecorder()
        r.setAudioSource(MediaRecorder.AudioSource.MIC)
        if (Build.VERSION.SDK_INT >= 29) {
            r.setOutputFormat(MediaRecorder.OutputFormat.OGG)
            r.setAudioEncoder(MediaRecorder.AudioEncoder.OPUS)
        } else {
            r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        }
        r.setAudioSamplingRate(16_000)
        r.setAudioChannels(1)
        r.setAudioEncodingBitRate(24_000)
        r.setOutputFile(file.absolutePath)
        r.prepare()
        r.start()
        recorder = r
    }

    private fun endChunk() {
        val r = recorder ?: return
        recorder = null
        runCatching { r.stop() }
        r.release()
        val n = _state.value.chunks
        _state.update { it.copy(chunks = n + 1) }
        upload(n)
    }

    private fun upload(n: Int) {
        val id = _state.value.meetingId ?: return
        val file = File(dir, "chunk-%05d.$extension".format(n))
        scope.launch {
            var attempt = 0
            while (isActive && file.exists()) {
                val ok = runCatching { api.putBytes("/api/v1/meetings/$id/chunks/$n", file.readBytes(), "audio/ogg") }.isSuccess
                if (ok) {
                    file.delete()
                    _state.update { it.copy(uploaded = it.uploaded + 1) }
                    return@launch
                }
                delay(minOf(60_000L, 2_000L shl minOf(attempt++, 5)))
            }
        }
    }

    fun pause() {
        if (!_state.value.recording || _state.value.paused) return
        endChunk()
        pausedAt = System.currentTimeMillis()
        _state.update { it.copy(paused = true) }
    }

    fun resume() {
        if (!_state.value.paused) return
        _state.update { it.copy(paused = false, pausedMs = it.pausedMs + System.currentTimeMillis() - pausedAt) }
        beginChunk()
    }

    fun mark(note: String = "penting") {
        val id = _state.value.meetingId ?: return
        val t = _state.value.elapsedS()
        scope.launch { runCatching { api.post("/api/v1/meetings/$id/marks", buildJsonObject { put("t", t); put("note", note) }) } }
    }

    /** Stop, wait for every chunk to be uploaded, then ask the server to make the minutes. */
    fun stop(onDone: (Result<String>) -> Unit) {
        val st = _state.value
        val id = st.meetingId ?: return
        rotator?.cancel()
        if (!st.paused) endChunk()
        _state.update { it.copy(recording = false, finishing = true) }
        MeetingService.stop(context)
        scope.launch {
            val total = _state.value.chunks
            var waited = 0
            while (_state.value.uploaded < total && waited < 30 * 60) { delay(1_000); waited++ }
            val result = runCatching {
                api.post("/api/v1/meetings/$id/finish", buildJsonObject {
                    put("duration_s", st.elapsedS().toDouble()); put("chunks", total)
                })
                id
            }
            _state.value = if (result.isSuccess) State() else _state.value.copy(finishing = false, error = result.exceptionOrNull()?.message)
            onDone(result)
        }
    }

    companion object {
        const val CHUNK_MS = 60_000L
    }
}
