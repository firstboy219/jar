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
        assertTrue(url.contains("utterance_end_ms=1800") && url.contains("vad_events=true"))
        assertTrue(url.contains("keywords=Kelapa%20Gading%3A2"))
        assertTrue(url.contains("keywords=n8n%3A2"))
        assertFalse(url.contains("keyterm"))
    }

    @Test fun nova3UsesKeyterms() {
        val url = SttConfig("t", "nova-3", "id", listOf("JARVIS")).url().toString()
        assertTrue(url.contains("keyterm=JARVIS"))
        assertFalse(url.contains("keywords="))
    }

    @Test fun serverTunesEndpointingAndDiarization() {
        val c = CoreApi.parseSttConfig("""{"access_token":"t","expires_in":60,"model":"nova-2","language":"id","keywords":[],
            "diarize":true,"endpointing_ms":1200,"utterance_end_ms":2000}""", 0)
        val url = c.url().toString()
        assertTrue(url.contains("endpointing=1200") && url.contains("utterance_end_ms=2000") && url.contains("diarize=true"))
    }
}
