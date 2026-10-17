package online.cosger.jarvis

import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import online.cosger.jarvis.data.AppSettings
import online.cosger.jarvis.data.LocationProvider
import online.cosger.jarvis.data.SecureSettings
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.net.CoreApi
import online.cosger.jarvis.net.DeviceLocation
import online.cosger.jarvis.net.JarvisSocket
import online.cosger.jarvis.net.Protocol
import online.cosger.jarvis.net.ServerEvent
import online.cosger.jarvis.ui.Board
import online.cosger.jarvis.ui.ChatMessage
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.screen.ScreenCapture
import online.cosger.jarvis.screen.ScreenShareService
import online.cosger.jarvis.voice.ContinuousListener
import online.cosger.jarvis.voice.ListeningService
import online.cosger.jarvis.voice.MicState
import online.cosger.jarvis.voice.Speaker
import online.cosger.jarvis.voice.SttConfig

/**
 * Everything that must outlive a screen: the link to jarvis-core, the microphone, the voice, and the
 * board of workers/reports. Lives in [JarvisApp]; a foreground service keeps the process alive while
 * the mic is unmuted.
 */
class JarvisEngine(private val context: Context, val settingsStore: SecureSettings, private val locations: LocationProvider) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    val settings: StateFlow<AppSettings> = settingsStore.state

    private val socket = JarvisSocket(scope)
    val connection: StateFlow<Connection> = socket.connection
    private val api = CoreApi()

    private val listener = ContinuousListener(scope)
    val mic: StateFlow<MicState> = listener.state
    val micLevel: StateFlow<Float> = listener.level
    val interim: StateFlow<String> = listener.interim
    private val speaker = Speaker(context)
    val speaking: StateFlow<Boolean> = speaker.speaking

    /** Screen sharing: the latest frame goes along with each thing the owner says. */
    val screen = ScreenCapture(context)
    val screenSharing: StateFlow<Boolean> = screen.active

    private val _turn = MutableStateFlow(TurnState())
    val turn: StateFlow<TurnState> = _turn.asStateFlow()
    private val _history = MutableStateFlow<List<ChatMessage>>(emptyList())
    val history: StateFlow<List<ChatMessage>> = _history.asStateFlow()
    private val _board = MutableStateFlow(Board())
    val board: StateFlow<Board> = _board.asStateFlow()
    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice.asStateFlow()

    @Volatile private var stt: SttConfig? = null
    private var sttFetch: Deferred<SttConfig>? = null
    private val reportQueue = Channel<ServerEvent.Report>(Channel.UNLIMITED)

    init {
        scope.launch { socket.events.collect(::onEvent) }
        scope.launch { listener.utterances.collect { sendText(it) } }
        scope.launch { listener.errors.collect { _notice.value = it } }
        // JARVIS must not transcribe its own voice: mute input while speaking, resume a moment after.
        scope.launch {
            speaker.speaking.collect { talking ->
                if (talking) listener.pause() else { delay(350); if (!speaker.speaking.value) listener.resume() }
            }
        }
        scope.launch { speakReportsWhenFree() }
        scope.launch { autoMuteWatchdog() }
        connect()
    }

    // ---------- connection & settings ----------

    fun connect() {
        val s = settings.value
        if (s.isConfigured) socket.start(s.serverUrl, s.deviceToken) else socket.stop()
    }

    fun saveSettings(serverUrl: String, token: String, speak: Boolean) {
        settingsStore.update { it.copy(serverUrl = serverUrl, deviceToken = token, speakReplies = speak) }
        stt = null
        connect()
        prefetchVoice()
    }

    fun setShareLocation(enabled: Boolean) = settingsStore.update { it.copy(shareLocation = enabled) }
    fun locationPermissionMissing(): Boolean = settings.value.shareLocation && !locations.hasPermission()

    fun newConversation() {
        settingsStore.newConversation()
        _history.value = emptyList()
        _turn.value = TurnState()
    }

    fun dismissNotice() { _notice.value = null }

    // ---------- voice ----------

    fun prefetchVoice() {
        val s = settings.value
        if (!s.isConfigured || stt?.isFresh() == true || sttFetch?.isActive == true) return
        sttFetch = scope.async { api.sttConfig(s.serverUrl, s.deviceToken).also { stt = it } }
    }

    private suspend fun voiceConfig(): SttConfig {
        stt?.takeIf { it.isFresh() }?.let { return it }
        prefetchVoice()
        val fetch = sttFetch ?: throw IllegalStateException("Token perangkat belum diisi (Pengaturan)")
        return fetch.await().also { prefetchVoice() }
    }

    /** Unmute: the mic stays open (foreground service) until muted again or idle too long. */
    fun unmute() {
        if (listener.unmuted) return
        ListeningService.start(context)
        listener.unmute(::voiceConfig)
    }

    fun mute() {
        listener.mute()
        context.stopService(Intent(context, ListeningService::class.java))
    }

    fun toggleMute() = if (listener.unmuted) mute() else unmute()

    private suspend fun autoMuteWatchdog() {
        while (true) {
            delay(30_000)
            val idleMs = System.currentTimeMillis() - listener.lastSpeechAtMs
            if (listener.unmuted && !speaker.speaking.value && idleMs > AUTO_MUTE_MS) {
                mute()
                _notice.value = "Mic dimatikan otomatis setelah ${AUTO_MUTE_MS / 60_000} menit tanpa suara."
            }
        }
    }

    // ---------- talking to JARVIS ----------

    private fun locationAsync(): Deferred<DeviceLocation?>? =
        if (settings.value.shareLocation) scope.async { locations.current() } else null

    fun sendText(text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        speaker.stop()
        val location = locationAsync()
        _turn.value = TurnState(phase = Phase.Thinking, userText = clean)
        scope.launch {
            val loc = runCatching { location?.let { withTimeoutOrNull(2_000) { it.await() } } }.getOrNull()
            val frame = if (screen.active.value) runCatching { screen.latestJpegBase64() }.getOrNull() else null
            if (!socket.send(clean, settings.value.sessionId, loc, frame)) {
                _turn.value = TurnState()
                _notice.value = "Belum terhubung ke JARVIS — pesan tidak terkirim."
                return@launch
            }
            _history.update { it + ChatMessage(fromUser = true, text = clean) }
        }
    }

    fun acknowledge(reportId: Long) {
        socket.sendControl(Protocol.control("ack", "report_id", reportId))
    }

    fun repeatReport(reportId: Long) {
        _board.value.reports.find { it.id == reportId }?.let {
            reportQueue.trySend(ServerEvent.Report(it.id, it.taskId, it.text, it.attempt, repeat = true))
        }
    }

    fun stopScreenShare() = ScreenShareService.stop(context)

    fun dismissMedia(seq: Long) = _board.update { it.dismissMedia(seq) }

    fun cancelTask(taskId: Long) {
        socket.sendControl(Protocol.control("cancel_task", "task_id", taskId))
    }

    private fun onEvent(event: ServerEvent) {
        when (event) {
            is ServerEvent.Pong, ServerEvent.AuthOk -> return
            is ServerEvent.Task, is ServerEvent.Tasks, is ServerEvent.TaskEvent,
            is ServerEvent.ReportAck, is ServerEvent.ReportUnheard -> _board.update { it.reduce(event) }
            is ServerEvent.Report -> {
                _board.update { it.reduce(event) }
                reportQueue.trySend(event)
            }
            is ServerEvent.Media -> {
                _board.update { it.reduce(event) }
                if (event.items.isNotEmpty()) _notice.value = "JARVIS menampilkan: ${event.caption.ifBlank { "${event.items.size} gambar/video" }}"
            }
            else -> {
                if (event.sessionId != null && event.sessionId != settings.value.sessionId) return
                _turn.update { it.reduce(event) }
                when (event) {
                    is ServerEvent.Reply -> {
                        _history.update { it + ChatMessage(fromUser = false, text = event.text, route = event.route) }
                        if (settings.value.speakReplies) speaker.say(event.text)
                    }
                    is ServerEvent.Error -> _notice.value = event.message
                    else -> Unit
                }
            }
        }
    }

    /**
     * Reports are spoken only when the owner is not mid-sentence and JARVIS is not answering something,
     * then the server is told it was said (that is what starts the "did you hear it?" clock).
     */
    private suspend fun speakReportsWhenFree() {
        for (r in reportQueue) {
            if (_board.value.reports.find { it.id == r.id }?.state == online.cosger.jarvis.ui.SpokenReport.State.Acknowledged) continue
            // Wait for a natural gap, but never forever (a stuck turn must not swallow a report).
            withTimeoutOrNull(45_000) { listener.state.first { it != MicState.Hearing } }
            withTimeoutOrNull(30_000) { _turn.first { it.phase !in setOf(Phase.Thinking, Phase.Acting, Phase.Answering) } }
            _history.update { it + ChatMessage(fromUser = false, text = r.text, route = "report") }
            val spoken = {
                socket.sendControl(Protocol.control("report_spoken", "report_id", r.id))
                _board.update { it.markSpoken(r.id) }
            }
            if (settings.value.speakReplies) {
                speaker.say((if (r.repeat) "Aku ulangi ya. " else "") + r.text) { spoken() }
            } else {
                spoken()
            }
        }
    }

    companion object {
        const val AUTO_MUTE_MS = 5 * 60_000L
    }
}
