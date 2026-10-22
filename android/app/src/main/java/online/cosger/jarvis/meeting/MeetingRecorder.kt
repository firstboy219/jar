package online.cosger.jarvis.meeting

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaRecorder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.net.ConsoleApi
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream

/**
 * Records a meeting from the phone's microphone (Android does not let apps capture Zoom/Meet/WhatsApp
 * call audio, so put the phone on the table or use the speaker).
 *
 * Capture is CONTINUOUS (AudioRecord → AAC-LC encoder → ADTS files of 60 s cut on a frame boundary): nothing is
 * lost between chunks. Each chunk is uploaded as soon as it is complete and retried until the server has it;
 * chunks left on the phone (app killed, no network) are uploaded the next time the app starts. The live
 * [State.level] / [State.quietS] tell the owner whether the microphone really hears the room.
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
        val level: Float = 0f,       // 0..1, what the microphone hears right now
        val quietS: Float = 0f,      // seconds of near-silence in a row
    ) {
        fun elapsedS(now: Long = System.currentTimeMillis()): Long =
            if (startedAtMs == 0L) 0 else (now - startedAtMs - pausedMs) / 1000

        /** The room has been silent for a while: the phone is probably too far from the speakers. */
        val tooQuiet: Boolean get() = recording && !paused && quietS >= RoomLevel.WARN_AFTER_S
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()
    private var capture: Capture? = null
    private var pausedAt = 0L
    private val root: File get() = File(context.filesDir, "meetings")
    private val dir: File get() = File(root, _state.value.meetingId.orEmpty())

    init {
        scope.launch(Dispatchers.IO) { recoverUnsent() }
    }

    suspend fun start(title: String, confidential: Boolean, participants: List<String> = emptyList(), agenda: String = ""): Result<String> =
        runCatching {
            val m = api.post("/api/v1/meetings", buildJsonObject {
                put("title", title); put("confidential", confidential); put("consent", true)
                put("agenda", agenda.take(2_000))
                put("participants", JsonArray(participants.map { it.trim() }.filter { it.isNotEmpty() }.take(30).map { JsonPrimitive(it) }))
            }).obj()
            val id = m.s("id")
            _state.value = State(meetingId = id, title = m.s("title"), recording = true, startedAtMs = System.currentTimeMillis())
            dir.mkdirs()
            MeetingService.start(context)
            val c = Capture()
            capture = c
            c.start()
            id
        }

    /** One continuous capture: AudioRecord thread → AAC encoder → numbered ADTS chunk files. */
    private inner class Capture : Thread("meeting-capture") {
        @Volatile var stopping = false
        @Volatile var paused = false
        private var rec: AudioRecord? = null
        private var codec: MediaCodec? = null
        private var out: BufferedOutputStream? = null
        private var frames = 0
        private var chunkNo = 0
        private var quiet = 0f
        private var lastUi = 0L

        private fun openRecorder(): AudioRecord {
            val min = AudioRecord.getMinBufferSize(Adts.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            // VOICE_RECOGNITION: tuned for speech from a distance, without the heavy call-style processing of VOICE_COMMUNICATION
            @Suppress("MissingPermission")
            val r = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, Adts.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT, maxOf(min, Adts.SAMPLE_RATE * 2))
            check(r.state == AudioRecord.STATE_INITIALIZED) { "mikrofon tidak bisa dibuka (dipakai aplikasi lain?)" }
            return r
        }

        override fun run() {
            val buf = ByteArray(3_200) // 100 ms
            val info = MediaCodec.BufferInfo()
            try {
                val format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, Adts.SAMPLE_RATE, 1).apply {
                    setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
                    setInteger(MediaFormat.KEY_BIT_RATE, 32_000)
                    setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16_384)
                }
                val c = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
                c.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                c.start()
                codec = c
                var r = openRecorder().also { it.startRecording() }
                rec = r
                var ptsUs = 0L
                var failures = 0
                var wasPaused = false
                while (!stopping) {
                    if (paused) {
                        if (!wasPaused) { runCatching { r.stop() }; drain(info, false); closeChunk(); wasPaused = true }
                        sleep(100)
                        continue
                    }
                    if (wasPaused) { r.startRecording(); wasPaused = false }
                    val n = r.read(buf, 0, buf.size)
                    if (n > 0) {
                        failures = 0
                        feed(c, buf, n, ptsUs, false)
                        ptsUs += n / 2 * 1_000_000L / Adts.SAMPLE_RATE
                        level(buf, n)
                    } else if (n < 0 && ++failures > 20) {
                        // the microphone was taken away (a phone call, another app): try to get it back
                        _state.update { it.copy(error = "Mikrofon terputus — mencoba menyambung lagi…") }
                        runCatching { r.stop(); r.release() }
                        sleep(2_000)
                        r = runCatching { openRecorder().also { it.startRecording() } }.getOrNull() ?: continue
                        rec = r
                        failures = 0
                        _state.update { it.copy(error = null) }
                    }
                    drain(info, false)
                }
                // end of stream: flush the encoder and close the last chunk
                feed(c, ByteArray(0), 0, ptsUs, true)
                drain(info, true)
            } catch (e: Exception) {
                _state.update { it.copy(error = e.message ?: "perekaman berhenti") }
            } finally {
                runCatching { rec?.stop() }
                runCatching { rec?.release() }
                runCatching { codec?.stop() }
                runCatching { codec?.release() }
                closeChunk()
            }
        }

        private fun feed(c: MediaCodec, data: ByteArray, n: Int, ptsUs: Long, eos: Boolean) {
            val i = c.dequeueInputBuffer(if (eos) 1_000_000 else 20_000)
            if (i < 0) return
            val b = c.getInputBuffer(i) ?: return
            b.clear()
            b.put(data, 0, n)
            c.queueInputBuffer(i, 0, n, ptsUs, if (eos) MediaCodec.BUFFER_FLAG_END_OF_STREAM else 0)
        }

        private fun drain(info: MediaCodec.BufferInfo, untilEnd: Boolean) {
            val c = codec ?: return
            var idle = 0
            while (true) {
                val o = c.dequeueOutputBuffer(info, if (untilEnd) 100_000 else 0)
                if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED || o == MediaCodec.INFO_OUTPUT_BUFFERS_CHANGED) continue
                if (o < 0) { if (untilEnd && ++idle < 50) continue else break } // at the end: wait up to ~5 s for the last frames
                if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG == 0 && info.size > 0) {
                    val ob = c.getOutputBuffer(o)!!
                    ob.position(info.offset); ob.limit(info.offset + info.size)
                    val frame = ByteArray(info.size)
                    ob.get(frame)
                    writeFrame(frame)
                }
                c.releaseOutputBuffer(o, false)
                if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
            }
        }

        private fun writeFrame(frame: ByteArray) {
            val s = out ?: BufferedOutputStream(FileOutputStream(File(dir, "chunk-%05d.aac".format(chunkNo)))).also { out = it }
            s.write(Adts.header(frame.size))
            s.write(frame)
            if (++frames >= Adts.FRAMES_PER_CHUNK) closeChunk()
        }

        /** Finish the current file (if it has audio) and hand it to the uploader. */
        private fun closeChunk() {
            val s = out ?: return
            out = null
            runCatching { s.flush(); s.close() }
            val n = chunkNo
            val had = frames
            frames = 0
            chunkNo++
            if (had == 0) { File(dir, "chunk-%05d.aac".format(n)).delete(); chunkNo--; return }
            _state.update { it.copy(chunks = n + 1) }
            upload(n)
        }

        private fun level(buf: ByteArray, n: Int) {
            val rms = RoomLevel.rms(buf, n)
            quiet = RoomLevel.quietSeconds(quiet, rms, n / 2f / Adts.SAMPLE_RATE)
            val now = System.currentTimeMillis()
            if (now - lastUi >= 250) {
                lastUi = now
                _state.update { it.copy(level = RoomLevel.meter(rms), quietS = quiet) }
            }
        }
    }

    private fun upload(n: Int, meetingId: String? = _state.value.meetingId) {
        val id = meetingId ?: return
        val file = File(File(root, id), "chunk-%05d.aac".format(n))
        scope.launch {
            var attempt = 0
            while (isActive && file.exists()) {
                val ok = runCatching {
                    withContext(Dispatchers.IO) { api.putBytes("/api/v1/meetings/$id/chunks/$n?ext=aac", file.readBytes(), "audio/aac") }
                }.isSuccess
                if (ok) {
                    file.delete()
                    _state.update { it.copy(uploaded = it.uploaded + 1) }
                    return@launch
                }
                delay(minOf(60_000L, 2_000L shl minOf(attempt++, 5)))
            }
        }
    }

    /** Chunks a previous run could not upload (app killed, no network): send them now; drop the ones the server refuses. */
    private suspend fun recoverUnsent() {
        val current = _state.value.meetingId
        root.listFiles { f -> f.isDirectory && f.name != current }?.forEach { d ->
            d.listFiles { f -> f.name.startsWith("chunk-") }?.sortedBy { it.name }?.forEach { f ->
                val n = f.name.removePrefix("chunk-").substringBefore('.').toIntOrNull() ?: return@forEach
                val ext = f.extension.ifEmpty { "ogg" }
                val r = runCatching { api.putBytes("/api/v1/meetings/${d.name}/chunks/$n?ext=$ext", f.readBytes(), "audio/$ext") }
                val refused = r.exceptionOrNull()?.message.orEmpty().let { "tidak sedang direkam" in it || "tidak ditemukan" in it }
                if (r.isSuccess || refused) f.delete()
            }
            if (d.listFiles().isNullOrEmpty()) d.delete()
        }
    }

    fun pause() {
        val c = capture ?: return
        if (!_state.value.recording || _state.value.paused) return
        c.paused = true
        pausedAt = System.currentTimeMillis()
        _state.update { it.copy(paused = true, level = 0f) }
    }

    fun resume() {
        val c = capture ?: return
        if (!_state.value.paused) return
        _state.update { it.copy(paused = false, pausedMs = it.pausedMs + System.currentTimeMillis() - pausedAt) }
        c.paused = false
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
        val c = capture
        capture = null
        _state.update { it.copy(recording = false, finishing = true, level = 0f) }
        scope.launch {
            withContext(Dispatchers.IO) { c?.let { it.stopping = true; it.join(15_000) } }
            MeetingService.stop(context)
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
}
