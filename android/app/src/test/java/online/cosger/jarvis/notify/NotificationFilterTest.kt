package online.cosger.jarvis.notify

import online.cosger.jarvis.net.Protocol
import online.cosger.jarvis.net.ServerEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NotificationFilterTest {
    private fun c(pkg: String = "com.whatsapp", ongoing: Boolean = false, summary: Boolean = false, title: String = "Budi", text: String = "Rapat jam 3") =
        NotificationFilter.Candidate(pkg, "online.cosger.jarvis", ongoing, summary, title, text)

    @Test fun forwardsPersonalMessagesOnly() {
        assertTrue(NotificationFilter.shouldForward(c()))
        assertFalse("own notifications", NotificationFilter.shouldForward(c(pkg = "online.cosger.jarvis")))
        assertFalse("system UI", NotificationFilter.shouldForward(c(pkg = "com.android.systemui")))
        assertFalse("ongoing (music, downloads, JARVIS mic)", NotificationFilter.shouldForward(c(ongoing = true)))
        assertFalse("group summary duplicates", NotificationFilter.shouldForward(c(summary = true)))
        assertFalse("empty", NotificationFilter.shouldForward(c(title = "", text = "")))
    }

    @Test fun oneTimeCodesNeverLeaveThePhone() {
        assertEquals("(kode/OTP disembunyikan di HP)", NotificationFilter.safeText("BCA", "Kode OTP Anda 482913. Jangan berikan."))
        assertEquals("(kode/OTP disembunyikan di HP)", NotificationFilter.safeText("Google", "G-582913 is your verification code"))
        assertEquals("(kode/OTP disembunyikan di HP)", NotificationFilter.safeText("Shopee", "Kode 7741 untuk masuk"))
        assertEquals("Rapat jadi jam 3", NotificationFilter.safeText("Budi", "Rapat jadi jam 3"))
        assertEquals("Transfer Rp 250.000 masuk", NotificationFilter.safeText("BCA", "Transfer Rp 250.000 masuk"))
    }

    @Test fun repostsAreSentOnce() {
        val d = NotificationFilter.Deduper(windowMs = 1_000)
        assertTrue(d.firstTime("k", "Budi", "hai", 0))
        assertFalse(d.firstTime("k", "Budi", "hai", 500))
        assertTrue("new text is new", d.firstTime("k", "Budi", "hai lagi", 600))
        assertTrue("after the window", d.firstTime("k", "Budi", "hai", 2_000))
    }

    @Test fun protocol() {
        assertEquals(ServerEvent.Announce("Ada WA dari Budi."), Protocol.parse("""{"type":"announce","text":"Ada WA dari Budi."}"""))
        assertEquals(
            """{"type":"notification","notification":{"app":"WhatsApp","package":"com.whatsapp","title":"Budi","text":"hai","posted_at":5}}""",
            Protocol.notification("WhatsApp", "com.whatsapp", "Budi", "hai", 5),
        )
    }
}
