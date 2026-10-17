package online.cosger.jarvis.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import online.cosger.jarvis.JarvisApp
import online.cosger.jarvis.data.AppSettings
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.net.CoreApi
import online.cosger.jarvis.net.DeviceLocation
import online.cosger.jarvis.net.JarvisSocket
import online.cosger.jarvis.net.ServerEvent
import online.cosger.jarvis.voice.DeepgramStreamer
import online.cosger.jarvis.voice.Speaker
import online.cosger.jarvis.voice.SttConfig

data class ChatMessage(val fromUser: Boolean, val text: String, val route: String? = null)

class JarvisViewModel(app: Application) : AndroidViewModel(app) {
    private val settingsStore = (app as JarvisApp).settings
    private val locations = (app as JarvisApp).location
    val settings: StateFlow<AppSettings> = settingsStore.state

    private val socket = JarvisSocket(viewModelScope)
    val connection: StateFlow<Connection> = socket.connection

    private val api = CoreApi()
    private val streamer = DeepgramStreamer(viewModelScope)
    val interim: StateFlow<String> = streamer.interim
    val micLevel: StateFlow<Float> = streamer.level
    private val speaker = Speaker(app)

    private val _turn = MutableStateFlow(TurnState())
    val turn: StateFlow<TurnState> = _turn.asStateFlow()

    private val _history = MutableStateFlow<List<ChatMessage>>(emptyList())
    val history: StateFlow<List<ChatMessage>> = _history.asStateFlow()

    private val _notice = MutableStateFlow<String?>(null)
    val notice: StateFlow<String?> = _notice.asStateFlow()

    @Volatile private var stt: SttConfig? = null
    private var sttFetch: Deferred<SttConfig>? = null
    private var pendingLocation: Deferred<DeviceLocation?>? = null

    init {
        viewModelScope.launch { socket.events.collect(::onEvent) }
        connect()
    }

    /** Fetch the voice token ahead of time so pressing the button starts streaming immediately. */
    fun prefetchVoice() {
        val s = settings.value
        if (!s.isConfigured || stt?.isFresh() == true || sttFetch?.isActive == true) return
        sttFetch = viewModelScope.async {
            api.sttConfig(s.serverUrl, s.deviceToken).also { stt = it }
        }
    }

    private suspend fun voiceConfig(): SttConfig {
        stt?.takeIf { it.isFresh() }?.let { return it }
        prefetchVoice()
        val fetch = sttFetch ?: throw IllegalStateException("Token perangkat belum diisi (Pengaturan)")
        val c = fetch.await()
        prefetchVoice() // keep the next one warm
        return c
    }

    private fun locationAsync(): Deferred<DeviceLocation?>? =
        if (settings.value.shareLocation) viewModelScope.async { locations.current() } else null

    fun locationPermissionMissing(): Boolean = settings.value.shareLocation && !locations.hasPermission()

    fun setShareLocation(enabled: Boolean) = settingsStore.update { it.copy(shareLocation = enabled) }

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

    fun newConversation() {
        settingsStore.newConversation()
        _history.value = emptyList()
        _turn.value = TurnState()
    }

    fun dismissNotice() { _notice.value = null }

    fun sendText(text: String, location: Deferred<DeviceLocation?>? = null) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        speaker.stop()
        _turn.value = TurnState(phase = Phase.Thinking, userText = clean)
        viewModelScope.launch {
            // Location is usually ready already (started when the talk button went down); never wait long.
            val loc = runCatching { (location ?: locationAsync())?.let { kotlinx.coroutines.withTimeoutOrNull(2_500) { it.await() } } }
                .getOrNull()
            if (!socket.send(clean, settings.value.sessionId, loc)) {
                _turn.value = TurnState()
                _notice.value = "Belum terhubung ke JARVIS — pesan tidak terkirim."
                return@launch
            }
            _history.update { it + ChatMessage(fromUser = true, text = clean) }
        }
    }

    // ---- walkie-talkie ----

    fun onTalkPressed() {
        speaker.stop()
        _turn.value = TurnState(phase = Phase.Listening)
        pendingLocation = locationAsync() // resolves while the owner is speaking
        try {
            streamer.start(::voiceConfig) // mic opens now; audio is buffered until the stream is ready
        } catch (e: Exception) {
            _turn.value = TurnState(phase = Phase.Failed, error = e.message ?: "Mikrofon tidak bisa dibuka")
        }
    }

    fun onTalkReleased() {
        if (_turn.value.phase != Phase.Listening) return
        viewModelScope.launch {
            val text = try {
                streamer.finish()
            } catch (e: Exception) {
                _turn.value = TurnState(phase = Phase.Failed, error = e.message ?: "Pengenalan suara gagal")
                return@launch
            }
            if (text.isBlank()) {
                _turn.value = TurnState(phase = Phase.Idle)
                _notice.value = "Tidak ada suara yang terdengar."
            } else {
                sendText(text, pendingLocation)
            }
        }
    }

    private fun onEvent(event: ServerEvent) {
        if (event is ServerEvent.Pong || event is ServerEvent.AuthOk) return
        if (event.sessionId != null && event.sessionId != settings.value.sessionId) return
        _turn.update { it.reduce(event) }
        when (event) {
            is ServerEvent.Reply -> {
                _history.update { it + ChatMessage(fromUser = false, text = event.text, route = event.route) }
                if (settings.value.speakReplies) speaker.speak(event.text)
            }
            is ServerEvent.Error -> _notice.value = event.message
            else -> Unit
        }
    }

    override fun onCleared() {
        streamer.cancel()
        socket.stop()
        speaker.shutdown()
    }
}
