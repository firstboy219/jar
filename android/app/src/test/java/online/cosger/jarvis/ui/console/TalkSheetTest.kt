package online.cosger.jarvis.ui.console

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TalkSheetTest {
    @Test fun `only the server's own origin counts as the app`() {
        val s = "https://vis1.cosger.online"
        assertTrue(sameOrigin(s, "https://vis1.cosger.online/app/#/misi"))
        assertTrue(sameOrigin(s, "https://VIS1.cosger.online:443/api/v1/app/home"))
        assertFalse(sameOrigin(s, "https://vis1.cosger.online.evil.com/app/"))
        assertFalse(sameOrigin(s, "http://vis1.cosger.online/app/"))
        assertFalse(sameOrigin(s, "https://example.com/"))
        assertFalse(sameOrigin(s, "not a url"))
        assertFalse(sameOrigin("", "https://vis1.cosger.online/"))
    }

    @Test fun `the sheet leaves the video to the app's player but shows the music controls`() {
        assertTrue("video" in APP_PLAYS)
        assertFalse("music" in APP_PLAYS)
    }
}
