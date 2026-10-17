package online.cosger.jarvis.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ProtocolTest {
    @Test fun parsesEveryServerEventType() {
        assertEquals(ServerEvent.Status("thinking", "s"), Protocol.parse("""{"type":"status","state":"thinking","session_id":"s"}"""))
        assertEquals(ServerEvent.Thought("The user", "s"), Protocol.parse("""{"type":"thought","text":"The user","session_id":"s"}"""))
        assertEquals(
            ServerEvent.Tool("c1", "memory_search", "Mencari di memori", "proyek", "⚡", true, "s"),
            Protocol.parse("""{"type":"tool","id":"c1","name":"memory_search","title":"Mencari di memori","label":"proyek","emoji":"⚡","status":"running","session_id":"s"}"""),
        )
        val ctx = Protocol.parse("""{"type":"context","source":"memory","query":"proyek","items":[{"text":"Autotoko","category":"project","score":0.81}],"session_id":"s"}""")
        assertEquals(ServerEvent.Context("proyek", listOf(ContextItem("Autotoko", "project", 0.81)), "s"), ctx)
        assertEquals(ServerEvent.Delta("Ha", "s"), Protocol.parse("""{"type":"delta","text":"Ha","session_id":"s"}"""))
        assertEquals(ServerEvent.Reply("Halo", "hermes", "s"), Protocol.parse("""{"type":"reply","text":"Halo","route":"hermes","session_id":"s"}"""))
        assertEquals(ServerEvent.Pong, Protocol.parse("""{"type":"pong"}"""))
        assertEquals(ServerEvent.AuthOk, Protocol.parse("""{"type":"auth_ok"}"""))
    }

    @Test fun completedToolIsNotRunning() {
        val e = Protocol.parse("""{"type":"tool","id":"c1","name":"x","status":"completed"}""") as ServerEvent.Tool
        assertEquals(false, e.running)
    }

    @Test fun ignoresGarbageAndUnknownTypes() {
        assertNull(Protocol.parse("not json"))
        assertNull(Protocol.parse("""{"type":"future_event","x":1}"""))
    }

    @Test fun commandIsValidJsonWithEscaping() {
        val cmd = Protocol.command("kata \"kutip\"\nbaris", "sid")
        assertTrue(cmd.contains("\"user_command\":\"kata \\\"kutip\\\"\\nbaris\""))
        assertTrue(cmd.contains("\"session_id\":\"sid\""))
    }
}
