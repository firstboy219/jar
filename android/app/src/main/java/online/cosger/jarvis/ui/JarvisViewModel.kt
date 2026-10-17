package online.cosger.jarvis.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import online.cosger.jarvis.JarvisApp
import online.cosger.jarvis.data.AppSettings
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.net.CoreApi
import online.cosger.jarvis.net.JarvisSocket
import online.cosger.jarvis.net.ServerEvent
import online.cosger.jarvis.voice.DeepgramStreamer
import online.cosger.jarvis.voice.Speaker

data class ChatMessage(val fromUser: Boolean, val text: String, val route: String? = null)

class JarvisViewModel(app: Application) : AndroidViewModel(app) {
    private val settingsStore = (app as JarvisApp).settings
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

    init {
        viewModelScope.launch { socket.events.collect(::onEvent) }
        connect()
    }

    fun connect() {
        val s = settings.value
        if (s.isConfigured) socket.start(s.serverUrl, s.deviceToken) else socket.stop()
    }

    fun saveSettings(serverUrl: String, token: String, speak: Boolean) {
        settingsStore.update { it.copy(serverUrl = serverUrl, deviceToken = token, speakReplies = speak) }
        connect()
    }

    fun newConversation() {
        settingsStore.newConversation()
        _history.value = emptyList()
        _turn.value = TurnState()
    }

    fun dismissNotice() { _notice.value = null }

    fun sendText(text: String) {
        val clean = text.trim()
        if (clean.isEmpty()) return
        speaker.stop()
        if (!socket.send(clean, settings.value.sessionId)) {
            _notice.value = "Belum terhubung ke JARVIS — pesan tidak terkirim."
            return
        }
        _history.update { it + ChatMessage(fromUser = true, text = clean) }
        _turn.value = TurnState(phase = Phase.Thinking, userText = clean)
    }

    // ---- walkie-talkie ----

    fun onTalkPressed() {
        speaker.stop()
        _turn.value = TurnState(phase = Phase.Listening)
        viewModelScope.launch {
            val s = settings.value
            try {
                streamer.start(api.deepgramToken(s.serverUrl, s.deviceToken))
            } catch (e: Exception) {
                _turn.value = TurnState(phase = Phase.Failed, error = e.message ?: "Mikrofon/voice gagal")
            }
        }
    }

    fun onTalkReleased() {
        if (_turn.value.phase != Phase.Listening) return
        viewModelScope.launch {
            val text = streamer.finish()
            if (text.isBlank()) {
                _turn.value = TurnState(phase = Phase.Idle)
                _notice.value = "Tidak ada suara yang terdengar."
            } else {
                sendText(text)
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
