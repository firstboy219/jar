package online.cosger.jarvis.ui.console

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GalaxyScreenTest {
    @Test fun `the token travels in the fragment, encoded, after a clean server url`() {
        assertEquals("https://vis1.cosger.online/canvas/#t=abc%2B1%2F2&app=1", galaxyUrl(" https://vis1.cosger.online/ ", "abc+1/2"))
    }

    @Test fun `only the jarvis server may be shown inside the screen`() {
        val s = "https://vis1.cosger.online"
        assertTrue(sameOrigin(s, "https://vis1.cosger.online/canvas/#kartu=3"))
        assertTrue(sameOrigin(s, "https://VIS1.cosger.online:443/api/v1/canvases"))
        assertFalse(sameOrigin(s, "https://vis1.cosger.online.evil.com/canvas/"))
        assertFalse(sameOrigin(s, "http://vis1.cosger.online/canvas/"))
        assertFalse(sameOrigin(s, "https://example.com/"))
        assertFalse(sameOrigin(s, "not a url"))
        assertFalse(sameOrigin("", "https://vis1.cosger.online/"))
    }
}
