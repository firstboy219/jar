package online.cosger.jarvis.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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

    @Test fun parsesV07Events() {
        val say = Protocol.parse("""{"type":"say","text":"Oke, aku cek dulu ya.","session_id":"s"}""") as ServerEvent.Say
        assertEquals("Oke, aku cek dulu ya.", say.text)
        val reply = Protocol.parse("""{"type":"reply","text":"x","route":"assistant","spoken":true}""") as ServerEvent.Reply
        assertEquals(true, reply.spoken)
        val t = Protocol.parse("""{"type":"transcript","seq":3,"text":"halo","is_owner":false}""") as ServerEvent.Transcript
        assertEquals(false, t.isOwner)
        val p = Protocol.parse("""{"type":"brain_pulse","ids":["a","b"],"kind":"write"}""") as ServerEvent.BrainPulse
        assertEquals(listOf("a", "b"), p.ids)
    }

    @Test fun utteranceCarriesAudioAndScreenText() {
        val json = Protocol.utterance("s1", 7, byteArrayOf(1, 2, 3), screenText = "Bu Rina: rapat jam 9?")
        val o = kotlinx.serialization.json.Json.parseToJsonElement(json).jsonObject
        assertEquals("utterance", o["type"]!!.jsonPrimitive.content)
        assertEquals("AQID", o["audio"]!!.jsonPrimitive.content)
        assertEquals("Bu Rina: rapat jam 9?", o["screen_text"]!!.jsonPrimitive.content)
    }
}
