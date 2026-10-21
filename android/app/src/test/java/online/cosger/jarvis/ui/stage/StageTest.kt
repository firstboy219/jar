package online.cosger.jarvis.ui.stage

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import online.cosger.jarvis.net.Protocol
import online.cosger.jarvis.net.ServerEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StageTest {
    private fun stage(json: String) = Protocol.parse(json) as ServerEvent.Stage

    @Test fun showUpdateClose() {
        var s = StageState()
        s = s.reduce(stage("""{"type":"stage","id":"a1","panel":"draft","mode":"show","payload":{"variants":[{"label":"Singkat","text":"Siap"}]},"caption":"Draf"}"""))
        assertEquals("draft", s.panel?.kind)
        s = s.reduce(stage("""{"type":"stage","id":"a1","panel":"draft","mode":"update","payload":{"variants":[{"label":"Formal","text":"Baik"}]}}"""))
        assertEquals("Formal", s.panel!!.list("variants")[0].s("label"))
        s = s.reduce(stage("""{"type":"stage","id":"zz","panel":"draft","mode":"close"}"""))
        assertEquals("a1", s.panel?.id) // closing another panel does nothing
        s = s.reduce(stage("""{"type":"stage","id":"a1","panel":"draft","mode":"close"}"""))
        assertNull(s.panel)
    }

    @Test fun unknownPanelsAreIgnoredAndRoutesSelectable() {
        val s = StageState().reduce(stage("""{"type":"stage","id":"x","panel":"shell","mode":"show","payload":{}}"""))
        assertNull(s.panel)
        val m = StageState().reduce(stage("""{"type":"stage","id":"m","panel":"map","payload":{"routes":[{},{}],"selected":0}}""")).select(1)
        assertEquals(1, m.panel!!.int("selected"))
    }

    @Test fun pulsesFade() {
        val s = StageState().pulse(listOf("m1"), "read", nowMs = 1_000)
        assertTrue("m1" in s.pulses)
        assertFalse("m1" in s.pulse(emptyList(), "read", nowMs = 1_000 + StageState.PULSE_MS + 1).pulses)
    }

    @Test fun brainParsesAndProjects() {
        val g = BrainGraph.parse(Json.parseToJsonElement("""{"nodes":[
            {"id":"a","x":0.5,"y":0.1,"z":0.2,"category":"personal","label":"Suka kopi"},
            {"id":"b","x":-0.5,"y":0.0,"z":-0.3,"category":"project","label":"UAT Kamis"}],
            "edges":[[0,1],[0,9]],"active":["a"],"categories":{"personal":"#4FC3F7"},"total":2}"""))
        assertEquals(2, g.nodes.size)
        assertEquals(listOf(0 to 1), g.edges) // out-of-range edge dropped
        assertEquals(0xFF4FC3F7, g.colors["personal"])
        val p = project(g.nodes, 0f, 0f, 400f, 400f)
        assertTrue(p.first().depth >= p.last().depth) // far first
        assertTrue(p.all { it.x in 0f..400f && it.y in 0f..400f })
    }

    @Test fun webIsLockedToTheConfirmedDomain() {
        assertEquals("detik.com", baseDomain("news.detik.com"))
        assertEquals("klikbca.co.id", baseDomain("ibank.klikbca.co.id"))
        assertTrue(allowedUrl("https://m.detik.com/x", "news.detik.com"))
        assertFalse(allowedUrl("http://news.detik.com", "news.detik.com"))
        assertFalse(allowedUrl("https://detik.com.evil.io/login", "news.detik.com"))
    }

    @Test fun whatsappLinksUseInternationalNumbers() {
        assertTrue(waLink("0812-3456-789", "Siap Bu").startsWith("https://wa.me/628123456789?text="))
    }

    @Test fun routePolylineIsRead() {
        val r = Json.parseToJsonElement("""{"polyline":[[-6.2,106.8],[-6.3,106.9],["x"]]}""").jsonObject
        assertEquals(listOf(-6.2 to 106.8, -6.3 to 106.9), routePoints(r))
    }
}
