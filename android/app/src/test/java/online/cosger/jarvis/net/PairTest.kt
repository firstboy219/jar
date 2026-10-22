package online.cosger.jarvis.net

import org.junit.Assert.assertEquals
import org.junit.Test

class PairTest {
    @Test fun serverMessageIsShown() {
        assertEquals("Password admin salah.", CoreApi.pairError(401, """{"detail": "Password admin salah."}"""))
        assertEquals("Terlalu banyak percobaan, coba lagi nanti.", CoreApi.pairError(429, "<html>"))
        assertEquals("Server HTTP 502", CoreApi.pairError(502, ""))
    }
}
