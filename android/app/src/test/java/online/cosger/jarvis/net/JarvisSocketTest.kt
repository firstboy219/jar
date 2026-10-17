package online.cosger.jarvis.net

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** Fail-safe auto-reconnect behaviour against a real (local) WebSocket server. */
class JarvisSocketTest {
    private lateinit var server: MockWebServer
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val received = LinkedBlockingQueue<String>()

    private fun acceptingSocket(closeAfterOpen: Boolean = false) = MockResponse().withWebSocketUpgrade(
        object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (closeAfterOpen) webSocket.close(1011, "server restart")
            }
            override fun onMessage(webSocket: WebSocket, text: String) {
                received.add(text)
                if (text.contains("ping")) webSocket.send("""{"type":"pong"}""")
                else webSocket.send("""{"type":"reply","text":"ok","route":"core","session_id":"s"}""")
            }
        },
    )

    @Before fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After fun tearDown() {
        scope.cancel()
        // MockWebServer waits for server-side sockets the test deliberately dropped; not app behaviour.
        runCatching { server.shutdown() }
    }

    private fun baseUrl() = server.url("/").toString().replace("http://", "https://")

    @Test fun reconnectsAfterServerDropsAndDeliversReplies() = runBlocking {
        server.enqueue(acceptingSocket(closeAfterOpen = true)) // first connection dies immediately
        server.enqueue(acceptingSocket())
        val s = JarvisSocket(scope, backoff = { 50L }, pingIntervalMs = 10_000, client = plainClient())
        // Subscribe before sending: SharedFlow has no replay, a fast reply must not be missed.
        val reply = async(start = CoroutineStart.UNDISPATCHED) { s.events.first { it is ServerEvent.Reply } }
        s.start(baseUrl(), "jdv_test")
        withTimeout(10_000) {
            // Keep trying until the reconnected socket answers (the first one may still look "Connected" while closing).
            while (!reply.isCompleted) {
                s.send("status", "s")
                delay(200)
            }
        }
        assertEquals(ServerEvent.Reply("ok", "core", "s"), reply.await())
        assertTrue("must have reconnected", server.requestCount >= 2)
        assertEquals("Bearer jdv_test", server.takeRequest().getHeader("Authorization"))
        s.stop()
    }

    @Test fun keepsAliveWithPings() = runBlocking {
        server.enqueue(acceptingSocket())
        val s = JarvisSocket(scope, backoff = { 50L }, pingIntervalMs = 100, client = plainClient())
        s.start(baseUrl(), "jdv_test")
        withTimeout(5_000) { s.connection.first { it == Connection.Connected } }
        val first = received.poll(3, TimeUnit.SECONDS)
        assertEquals(Protocol.PING, first)
        s.stop()
    }

    @Test fun unauthorizedStopsRetrying() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401))
        server.enqueue(acceptingSocket()) // must never be used
        val s = JarvisSocket(scope, backoff = { 50L }, pingIntervalMs = 100, client = plainClient())
        s.start(baseUrl(), "jdv_bad")
        withTimeout(5_000) { s.connection.first { it == Connection.Unauthorized } }
        kotlinx.coroutines.delay(300)
        assertEquals(1, server.requestCount)
        assertTrue(!s.send("x", "s"))
    }

    /** MockWebServer speaks plain ws://; rewrite our wss:// back for the test only. */
    private fun plainClient() = okhttp3.OkHttpClient.Builder()
        .addInterceptor { chain ->
            val req = chain.request()
            chain.proceed(req.newBuilder().url(req.url.newBuilder().scheme("http").build()).build())
        }
        .build()
}
