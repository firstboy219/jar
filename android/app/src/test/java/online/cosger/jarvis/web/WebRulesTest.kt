package online.cosger.jarvis.web

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WebRulesTest {
    @Test fun onlyHttpsPagesOfTheNamedSites() {
        val sites = listOf("21cineplex.com", "www.cgv.id")
        assertTrue(WebRules.allowed("https://21cineplex.com/theaters", sites))
        assertTrue(WebRules.allowed("https://m.21cineplex.com/", sites))
        assertTrue(WebRules.allowed("https://cgv.id/en/schedule", sites))
        assertFalse(WebRules.allowed("http://21cineplex.com/", sites))           // not https
        assertFalse(WebRules.allowed("https://evil21cineplex.com/", sites))     // not a subdomain
        assertFalse(WebRules.allowed("https://bank.example/", sites))
        assertFalse(WebRules.allowed("javascript:alert(1)", sites))
        assertNull(WebRules.host("ftp://x.id"))
        assertEquals("kci.id", WebRules.host("https://KCI.id/info"))
    }

    @Test fun recognisesABotCheck() {
        assertTrue(WebRules.challenged("Just a moment...", ""))
        assertTrue(WebRules.challenged("CGV", "Access Restricted. We were unable to process your request"))
        assertFalse(WebRules.challenged("CINEMA 21", "Jadwal film hari ini"))
    }

    @Test fun moneySitesAreNeverOpenedBySessions() {
        assertTrue(WebRules.financial("https://ibank.klikbca.com/"))
        assertTrue(WebRules.financial("https://www.indodax.com/market"))
        assertFalse(WebRules.financial("https://www.traveloka.com/id-id/hotel"))
        assertFalse(WebRules.financial("https://www.tiket.com/pesawat"))
    }
}
