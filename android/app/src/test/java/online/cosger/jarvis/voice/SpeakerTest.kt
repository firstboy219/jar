package online.cosger.jarvis.voice

import org.junit.Assert.assertEquals
import org.junit.Test

class SpeakerTest {
    @Test fun stripsMarkdownBeforeSpeaking() {
        val md = "**Proyek Autotoko**:\n- Shopee\n- `Tokopedia`\nLihat [docs](https://x.y)\n```\ncode\n```"
        assertEquals("Proyek Autotoko: Shopee Tokopedia Lihat docs (kode)", Speaker.stripMarkdown(md))
    }
}
