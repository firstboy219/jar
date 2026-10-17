package online.cosger.jarvis.voice

import online.cosger.jarvis.net.CoreApi
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SttTest {
    @Test fun serverConfigIsParsed() {
        val c = CoreApi.parseSttConfig(
            """{"access_token":"tok","expires_in":60,"model":"nova-2","language":"id","keywords":["JARVIS","Kelapa Gading"]}""",
            nowMs = 1_000,
        )
        assertEquals(SttConfig("tok", "nova-2", "id", listOf("JARVIS", "Kelapa Gading"), 61_000), c)
        assertTrue(c.isFresh(nowMs = 40_000))
        assertFalse("refresh 15 s before expiry", c.isFresh(nowMs = 50_000))
    }

    @Test fun nova2UsesKeywordBoostingAndUrlEncodes() {
        val url = SttConfig("t", "nova-2", "id", listOf("Kelapa Gading", "n8n")).url().toString()
        assertTrue(url.startsWith("https://api.deepgram.com/v1/listen?model=nova-2&language=id&encoding=linear16&sample_rate=16000"))
        assertTrue(url.contains("keywords=Kelapa%20Gading%3A2"))
        assertTrue(url.contains("keywords=n8n%3A2"))
        assertFalse(url.contains("keyterm"))
    }

    @Test fun nova3UsesKeyterms() {
        val url = SttConfig("t", "nova-3", "id", listOf("JARVIS")).url().toString()
        assertTrue(url.contains("keyterm=JARVIS"))
        assertFalse(url.contains("keywords="))
    }

    @Test fun parsesInterimFinalAndFlush() {
        fun msg(t: String, final: Boolean, flush: Boolean) =
            """{"type":"Results","is_final":$final,"from_finalize":$flush,"channel":{"alternatives":[{"transcript":"$t"}]}}"""
        assertEquals(DeepgramStreamer.Result("cek status", false, false), DeepgramStreamer.parseResult(msg("cek status", false, false)))
        assertEquals(DeepgramStreamer.Result("cek status server", true, true), DeepgramStreamer.parseResult(msg("cek status server", true, true)))
        assertEquals(null, DeepgramStreamer.parseResult("""{"type":"Metadata"}"""))
    }
}
