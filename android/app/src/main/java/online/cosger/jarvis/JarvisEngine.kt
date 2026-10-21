package online.cosger.jarvis

import android.content.Context
import android.content.Intent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import online.cosger.jarvis.data.AppSettings
import online.cosger.jarvis.data.LocationProvider
import online.cosger.jarvis.data.PhoneSensors
import online.cosger.jarvis.data.SecureSettings
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.net.ConsoleApi
import online.cosger.jarvis.net.CoreApi
import online.cosger.jarvis.net.DeviceLocation
import online.cosger.jarvis.net.JarvisSocket
import online.cosger.jarvis.net.Protocol
import online.cosger.jarvis.net.ServerEvent
import online.cosger.jarvis.notify.Conversations
import online.cosger.jarvis.ocr.ScreenText
import online.cosger.jarvis.screen.ScreenCapture
import online.cosger.jarvis.screen.ScreenShareService
import online.cosger.jarvis.ui.Board
import online.cosger.jarvis.ui.ChatMessage
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.ui.stage.BrainGraph
import online.cosger.jarvis.ui.stage.StageState
import online.cosger.jarvis.voice.ContinuousListener
import online.cosger.jarvis.voice.ListeningService
import online.cosger.jarvis.voice.MicState
import online.cosger.jarvis.voice.Speaker
import online.cosger.jarvis.voice.SttConfig
import online.cosger.jarvis.voice.VadListener
import online.cosger.jarvis.voice.VoiceInput
import online.cosger.jarvis.voice.WakeListener

/**
 * Everything that must outlive a screen: the link to jarvis-core, the microphone, the voice, the board
 * of workers/reports, and the front screen ("Panggung"). Lives in [JarvisApp]; a foreground service keeps
 * the process alive while the mic is unmuted.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class JarvisEngine(private val context: Context, val settingsStore: SecureSettings, private val locations: LocationProvider) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    val settings: StateFlow<AppSettings> = settingsStore.state

    private val socket = JarvisSocket(scope)
    val connection: StateFlow<Connection> = socket.connection
    private val api = CoreApi()
    val console = ConsoleApi({ settings.value.serverUrl }, { settings.value.deviceToken })
    val meetings = online.cosger.jarvis.meeting.MeetingRecorder(context, console)
    val updater = online.cosger.jarvis.update.AppUpdater(context, console, settingsStore)

    // Two ways to listen (Komposisi AI → mesin suara): Deepgram live stream, or on-phone VAD + server STT.
    private val deepgram = ContinuousListener(scope)
    private val vad = VadListener(context, scope)
    private val _input = MutableStateFlow<VoiceInput>(vad)
    private val listener: VoiceInput get() = _input.value
    private val _sttEngine = MutableStateFlow("whisper")
    val sttEngine: StateFlow<String> = _sttEngine.asStateFlow()
    val mic: StateFlow<MicState> = _input.flatMapLatest { it.state }.stateIn(scope, SharingStarted.Eagerly, MicState.Muted)
    val micLevel: StateFlow<Float> = _input.flatMapLatest { it.level }.stateIn(scope, SharingStarted.Eagerly, 0f)
    val interim: StateFlow<String> = _input.flatMapLatest { it.interim }.stateIn(scope, SharingStarted.Eagerly, "")
    private val speaker = Speaker(context)
    val speaking: StateFlow<Boolean> = speaker.speaking
    /** "Hey Jarvis" while muted (opt-in). */
    private val wake = WakeListener(context, scope)
    val wakeListening: StateFlow<Boolean> = wake.active

    /** Camera: while the preview is open, its current frame goes along with each thing the owner says. */
    private val _cameraOn = MutableStateFlow(false)
    val cameraOn: StateFlow<Boolean> = _cameraOn.asStateFlow()
    @Volatile var cameraFrame: (() -> String?)? = null
    fun setCamera(on: Boolean) { _cameraOn.value = on }

    private val sensors = PhoneSensors(context)

    /** Screen sharing: the latest frame's TEXT (read on the phone) goes along with each thing the owner says. */
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

    /** The front screen: a panel JARVIS opened, or (none) the 3D brain. */
    private val _stage = MutableStateFlow(StageState())
    val stage: StateFlow<StageState> = _stage.asStateFlow()
    private val _brain = MutableStateFlow<BrainGraph?>(null)
    val brain: StateFlow<BrainGraph?> = _brain.asStateFlow()

    @Volatile private var stt: SttConfig? = null
    private var sttFetch: Deferred<SttConfig>? = null
    private val reportQueue = Channel<ServerEvent>(Channel.UNLIMITED) // Report (needs ack) or Announce (once)
    private val outbox = ArrayDeque<String>() // notifications captured while offline
    private var utteranceSeq = 0L
    @Volatile private var spokenLive = false

    init {
        scope.launch { socket.events.collect(::onEvent) }
        scope.launch { deepgram.texts.collect { sendText(it.text, it.confidence, it.speakers) } }
        scope.launch { vad.audio.collect(::sendUtterance) }
        scope.launch { reportContextForever() }
        scope.launch { deepgram.errors.collect { _notice.value = it } }
        scope.launch { vad.errors.collect { _notice.value = it } }
        // JARVIS must not transcribe its own voice: mute input while speaking, resume a moment after —
        // unless barge-in is on and a headset keeps JARVIS' voice out of the mic.
        scope.launch {
            speaker.speaking.collect { talking ->
                if (talking) { if (!bargeInNow()) listener.pause() }
                else { delay(350); if (!speaker.speaking.value) listener.resume() }
            }
        }
        scope.launch { vad.speechStarts.collect { if (speaker.speaking.value && bargeInNow()) speaker.stop() } }
        scope.launch {
            wake.heard.collect {
                wake.stop()
                runCatching { android.media.ToneGenerator(android.media.AudioManager.STREAM_MUSIC, 70)
                    .startTone(android.media.ToneGenerator.TONE_PROP_BEEP2, 150) }
                unmute()
            }
        }
        scope.launch { delay(2_000); syncWake() }
        scope.launch { speakReportsWhenFree() }
        scope.launch {
            connection.collect { c ->
                if (c == Connection.Connected) {
                    synchronized(outbox) {
                        while (outbox.isNotEmpty() && socket.sendControl(outbox.first())) outbox.removeFirst()
                    }
                    refreshComposition()
                    refreshBrain()
                    updater.check()
                }
            }
        }
        scope.launch {
            var ticks = 0
            while (true) {
                delay(5 * 60_000L)
                if (connection.value != Connection.Connected) continue
                refreshBrain()
                if (++ticks % 36 == 0) updater.check() // every ~3 h
            }
        }
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
    fun setReadNotifications(enabled: Boolean) = settingsStore.update { it.copy(readNotifications = enabled) }
    fun setUseCalendar(enabled: Boolean) = settingsStore.update { it.copy(useCalendar = enabled) }
    fun setWakeWord(enabled: Boolean, sensitive: Boolean = settings.value.wakeSensitive) {
        settingsStore.update { it.copy(wakeWord = enabled, wakeSensitive = sensitive) }
        syncWake()
    }
    fun setBargeIn(enabled: Boolean) = settingsStore.update { it.copy(bargeIn = enabled) }

    private fun bargeInNow(): Boolean = settings.value.bargeIn && sensors.headset() == true && listener === vad

    /** "Hey Jarvis" runs only while the main mic is muted (one app can't hold the mic twice). */
    private fun syncWake() {
        val want = settings.value.wakeWord && !listener.unmuted &&
            context.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) == android.content.pm.PackageManager.PERMISSION_GRANTED
        wake.threshold = if (settings.value.wakeSensitive) 0.25f else 0.5f
        if (want && !wake.active.value) {
            if (wake.start()) ListeningService.start(context)
        } else if (!want && wake.active.value) {
            wake.stop()
            if (!listener.unmuted) context.stopService(Intent(context, ListeningService::class.java))
        }
    }

    /** Which speech engine the owner chose; the switch happens while muted. */
    suspend fun refreshComposition() {
        val engine = runCatching {
            console.get("/api/v1/composition").jsonObject["stt"]?.jsonObject?.get("engine")?.jsonPrimitive?.contentOrNull
        }.getOrNull() ?: return
        _sttEngine.value = engine
        val wanted = if (engine == "deepgram") deepgram else vad
        if (wanted !== _input.value && !listener.unmuted) _input.value = wanted
    }

    suspend fun refreshBrain() {
        runCatching { BrainGraph.parse(console.get("/api/v1/brain")) }.getOrNull()?.let { _brain.value = it }
    }

    /** Situational awareness heartbeat: more often while JARVIS is listening, rarer while muted. */
    private suspend fun reportContextForever() {
        while (true) {
            if (connection.value == Connection.Connected) runCatching { sendContext() }
            delay(if (listener.unmuted) 3 * 60_000L else 10 * 60_000L)
        }
    }

    suspend fun sendContext() {
        val s = settings.value
        val loc = if (s.shareLocation) runCatching { withTimeoutOrNull(5_000) { locations.current() } }.getOrNull() else null
        val ctx = sensors.collect(loc, listener.unmuted, s.useCalendar)
        socket.sendControl(Protocol.context(ctx))
    }

    /** From the notification listener: send now, or keep (bounded) until the link is back. */
    fun forwardNotification(app: String, pkg: String, title: String, text: String, postedAtMs: Long) {
        val json = Protocol.notification(app, pkg, title, text, postedAtMs)
        scope.launch {
            if (!socket.sendControl(json)) synchronized(outbox) {
                outbox.addLast(json)
                while (outbox.size > 20) outbox.removeFirst()
            }
        }
    }
    fun locationPermissionMissing(): Boolean = settings.value.shareLocation && !locations.hasPermission()

    fun newConversation() {
        settingsStore.newConversation()
        _history.value = emptyList()
        _turn.value = TurnState()
    }

    fun dismissNotice() { _notice.value = null }
    fun notify(text: String) { _notice.value = text }

    // ---------- voice ----------

    fun prefetchVoice() {
        val s = settings.value
        if (_sttEngine.value != "deepgram") return // VAD path needs no token
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
        wake.stop()
        val wanted = if (_sttEngine.value == "deepgram") deepgram else vad
        if (wanted !== _input.value) _input.value = wanted
        vad.echoCancel = settings.value.bargeIn
        ListeningService.start(context)
        listener.unmute(::voiceConfig)
        scope.launch { delay(1_000); runCatching { sendContext() } } // "I'm here now" — fresh context
    }

    fun mute() {
        listener.mute()
        context.stopService(Intent(context, ListeningService::class.java))
        syncWake() // back to waiting for "Hey Jarvis" if enabled
    }

    fun toggleMute() = if (listener.unmuted) mute() else unmute()

    /** Recording a meeting or a voiceprint sample: the JARVIS mic must let go of the microphone. */
    fun prepareMeeting() {
        speaker.stop()
        mute()
        wake.stop()
        context.stopService(Intent(context, ListeningService::class.java))
    }

    private suspend fun autoMuteWatchdog() {
        while (true) {
            delay(15_000)
            val idleMs = System.currentTimeMillis() - listener.lastSpeechAtMs
            // With "Hey Jarvis" on, go back to wake-word listening sooner (it costs less battery).
            val limit = if (settings.value.wakeWord) WAKE_IDLE_MS else AUTO_MUTE_MS
            if (listener.unmuted && !speaker.speaking.value && idleMs > limit) {
                mute()
                if (!settings.value.wakeWord) _notice.value = "Mic dimatikan otomatis setelah ${AUTO_MUTE_MS / 60_000} menit tanpa suara."
            }
        }
    }

    // ---------- talking to JARVIS ----------

    private fun locationAsync(): Deferred<DeviceLocation?>? =
        if (settings.value.shareLocation) scope.async { locations.current() } else null

    /** What the owner is showing: camera frame (image), or the shared screen read as text on the phone. */
    private data class Shown(val image: String?, val source: String?, val text: String?)

    private suspend fun shown(): Shown {
        val cam = if (_cameraOn.value) runCatching { cameraFrame?.invoke() }.getOrNull() else null
        if (cam != null) return Shown(cam, "camera", null)
        if (!screen.active.value) return Shown(null, null, null)
        val bmp = withContext(Dispatchers.Default) { runCatching { screen.latestBitmap() }.getOrNull() } ?: return Shown(null, null, null)
        val text = withTimeoutOrNull(2_500) { ScreenText.read(bmp) }.orEmpty()
        val thread = Conversations.latest()?.takeIf { System.currentTimeMillis() - it.at < 30 * 60_000L }?.let(Conversations::text)
        val combined = listOfNotNull(text.takeIf { it.isNotBlank() }, thread).joinToString("\n\n")
        // Text is enough for chats and articles; a picture only when the screen has (almost) no words.
        val image = if (text.length < MIN_SCREEN_TEXT) withContext(Dispatchers.Default) { screen.jpeg(bmp) } else null
        return Shown(image, if (image != null) "screen" else null, combined.ifBlank { null })
    }

    fun sendText(text: String, confidence: Double? = null, speakers: Int? = null) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        speaker.stop()
        spokenLive = false
        val location = locationAsync()
        _turn.value = TurnState(phase = Phase.Thinking, userText = clean)
        scope.launch {
            val loc = runCatching { location?.let { withTimeoutOrNull(2_000) { it.await() } } }.getOrNull()
            val show = shown()
            if (!socket.send(clean, settings.value.sessionId, loc, show.image, show.source, confidence, speakers, show.text)) {
                _turn.value = TurnState()
                _notice.value = "Belum terhubung ke JARVIS — pesan tidak terkirim."
                return@launch
            }
            _history.update { it + ChatMessage(fromUser = true, text = clean) }
        }
    }

    /** VAD cut an utterance: send the audio; the server transcribes it and answers. */
    private fun sendUtterance(pcm: ByteArray) {
        speaker.stop()
        spokenLive = false
        val seq = ++utteranceSeq
        val location = locationAsync()
        _turn.value = TurnState(phase = Phase.Thinking, userText = "…")
        scope.launch {
            val loc = runCatching { location?.let { withTimeoutOrNull(1_500) { it.await() } } }.getOrNull()
            val show = shown()
            val json = Protocol.utterance(settings.value.sessionId, seq, pcm, loc, show.image, show.source, show.text)
            if (!socket.sendControl(json)) {
                _turn.value = TurnState()
                _notice.value = "Belum terhubung ke JARVIS — ucapan tidak terkirim."
            }
        }
    }

    /** "Balas" while sharing WhatsApp/email: ask for reply drafts from what is on screen. */
    fun askReplyDraft(instruction: String = "") =
        sendText(if (instruction.isBlank()) "Tolong bantu buatkan draf balasan untuk pesan di layarku." else "Bantu balas pesan ini: $instruction")

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

    // ---------- the front screen ----------

    fun stageEvent(event: String, detail: Map<String, Int> = emptyMap()) {
        val current = _stage.value.panel ?: return
        socket.sendControl(Protocol.stageEvent(current.id, event, detail))
        when (event) {
            "closed" -> _stage.update { it.close(current.id) }
            "route_selected" -> detail["index"]?.let { i -> _stage.update { it.select(i) } }
        }
    }

    fun closeStage() = stageEvent("closed")

    private var lastUpdateCheck = 0L

    /** App came to the foreground: ask the server for a newer APK (at most every 10 minutes). */
    fun checkUpdateSoon() {
        val now = System.currentTimeMillis()
        if (now - lastUpdateCheck < 10 * 60_000L || !settings.value.isConfigured) return
        lastUpdateCheck = now
        scope.launch { updater.check() }
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
            is ServerEvent.Proactive -> {
                _history.update { it + ChatMessage(fromUser = false, text = event.text, route = "proactive") }
                reportQueue.trySend(ServerEvent.Announce(event.text))
            }
            is ServerEvent.Announce -> {
                _history.update { it + ChatMessage(fromUser = false, text = event.text, route = "announce") }
                reportQueue.trySend(event)
            }
            is ServerEvent.Media -> {
                _board.update { it.reduce(event) }
                if (event.items.isNotEmpty()) _notice.value = "JARVIS menampilkan: ${event.caption.ifBlank { "${event.items.size} gambar/video" }}"
            }
            is ServerEvent.Stage -> _stage.update { it.reduce(event) }
            is ServerEvent.BrainPulse -> _stage.update { it.pulse(event.ids, event.kind) }
            is ServerEvent.Approval -> _notice.value = "Butuh persetujuanmu: ${event.title} (menu Tugas & Persetujuan)"
            is ServerEvent.Transcript -> {
                if (event.sessionId != null && event.sessionId != settings.value.sessionId) return
                listener.setInterim("")
                if (event.text.isBlank()) {
                    _turn.value = TurnState()
                    event.error?.let { _notice.value = "Suara tidak tertangkap: $it" }
                } else {
                    _turn.update { it.copy(userText = event.text) }
                    _history.update { it + ChatMessage(fromUser = true, text = event.text) }
                }
            }
            is ServerEvent.Say -> {
                if (event.sessionId != null && event.sessionId != settings.value.sessionId) return
                spokenLive = true
                if (settings.value.speakReplies) speaker.say(event.text)
            }
            else -> {
                if (event.sessionId != null && event.sessionId != settings.value.sessionId) return
                _turn.update { it.reduce(event) }
                when (event) {
                    is ServerEvent.Reply -> if (event.route == "silent") {
                        // JARVIS judged the speech was not for it (or unfinished): no answer, no voice.
                        _turn.value = TurnState()
                    } else {
                        _history.update { it + ChatMessage(fromUser = false, text = event.text, route = event.route) }
                        if (settings.value.speakReplies && !event.spoken && !spokenLive) speaker.say(event.text)
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
        for (item in reportQueue) {
            if (item is ServerEvent.Announce) {
                withTimeoutOrNull(45_000) { mic.first { it != MicState.Hearing } }
                if (settings.value.speakReplies) speaker.say(item.text)
                continue
            }
            val r = item as? ServerEvent.Report ?: continue
            if (_board.value.reports.find { it.id == r.id }?.state == online.cosger.jarvis.ui.SpokenReport.State.Acknowledged) continue
            // Wait for a natural gap, but never forever (a stuck turn must not swallow a report).
            withTimeoutOrNull(45_000) { mic.first { it != MicState.Hearing } }
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
        const val WAKE_IDLE_MS = 60_000L
        const val MIN_SCREEN_TEXT = 40
    }
}
