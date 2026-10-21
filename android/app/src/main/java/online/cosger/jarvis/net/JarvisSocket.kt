package online.cosger.jarvis.net

import kotlinx.coroutines.CoroutineScope
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
import java.util.concurrent.TimeUnit
import kotlin.math.min

enum class Connection { Disconnected, Connecting, Connected, Unauthorized }

/**
 * WSS link to jarvis-core with "Fail-Safe Auto-Reconnect" (BRD §4): exponential backoff 1 s → 30 s,
 * app-level ping every 20 s, two missed pongs = dead link. Close code 4401 = bad token, no retry.
 */
class JarvisSocket(
    private val scope: CoroutineScope,
    private val client: OkHttpClient = defaultClient(),
    private val backoff: (attempt: Int) -> Long = { min(30_000L, 1_000L shl min(it, 5)) },
    private val pingIntervalMs: Long = 20_000,
) {
    private val _events = MutableSharedFlow<ServerEvent>(extraBufferCapacity = 256)
    val events: SharedFlow<ServerEvent> = _events

    private val _connection = MutableStateFlow(Connection.Disconnected)
    val connection: StateFlow<Connection> = _connection

    @Volatile private var ws: WebSocket? = null
    @Volatile private var missedPongs = 0
    private var loop: Job? = null
    private var url: String = ""
    private var token: String = ""

    fun start(baseUrl: String, deviceToken: String) {
        stop()
        url = baseUrl.trimEnd('/').replaceFirst("https://", "wss://") + "/ws"
        token = deviceToken
        loop = scope.launch { runLoop() }
    }

    fun stop() {
        loop?.cancel()
        loop = null
        ws?.close(1000, "bye")
        ws = null
        _connection.value = Connection.Disconnected
    }

    /** Returns false if not connected; the caller shows that instead of pretending it was sent. */
    /** Report heard/spoken, task cancel — fire and forget. */
    fun sendControl(json: String): Boolean = _connection.value == Connection.Connected && ws?.send(json) == true

    fun send(text: String, sessionId: String, location: DeviceLocation? = null, screen: String? = null,
             imageSource: String? = null, confidence: Double? = null, speakers: Int? = null, screenText: String? = null): Boolean =
        _connection.value == Connection.Connected &&
            ws?.send(Protocol.command(text, sessionId, location, screen, imageSource, confidence, speakers, screenText)) == true

    private suspend fun runLoop() {
        var attempt = 0
        while (scope.isActive) {
            _connection.value = Connection.Connecting
            val closed = kotlinx.coroutines.CompletableDeferred<Int>()
            val request = Request.Builder().url(url).header("Authorization", "Bearer $token")
                .header("X-App-Version", online.cosger.jarvis.BuildConfig.VERSION_NAME)
                .header("X-App-Caps", CAPS).build()
            missedPongs = 0
            ws = client.newWebSocket(request, object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    attempt = 0
                    _connection.value = Connection.Connected
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    val event = Protocol.parse(text) ?: return
                    if (event is ServerEvent.Pong) missedPongs = 0
                    if (event is ServerEvent.Error && event.message == "unauthorized") {
                        _connection.value = Connection.Unauthorized
                    }
                    _events.tryEmit(event)
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, null)
                    closed.complete(code)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    closed.complete(code)
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    closed.complete(if (response?.code == 401) UNAUTHORIZED else -1)
                }
            })

            val pinger = scope.launch {
                while (isActive) {
                    delay(pingIntervalMs)
                    if (_connection.value != Connection.Connected) continue
                    if (missedPongs >= 2) {
                        ws?.cancel() // dead link: triggers onFailure -> reconnect
                        break
                    }
                    missedPongs++
                    ws?.send(Protocol.PING)
                }
            }
            val code = closed.await()
            pinger.cancel()
            ws = null
            if (code == UNAUTHORIZED || _connection.value == Connection.Unauthorized) {
                _connection.value = Connection.Unauthorized
                return
            }
            _connection.value = Connection.Disconnected
            delay(backoff(attempt++))
        }
    }

    companion object {
        const val UNAUTHORIZED = 4401
        /** What this app understands, so the server knows it may stream sentences and stage panels. */
        const val CAPS = "say,stage,utterance,brain"

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS) // long agent turns; liveness is our ping/pong
            .build()
    }
}
