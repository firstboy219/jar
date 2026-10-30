package online.cosger.jarvis.phone

import org.junit.Assert.assertEquals
import org.junit.Test

class YouTubeCaptionsTest {
    @Test fun `the player's subtitle request is read as json3 in its language`() {
        val u = "https://www.youtube.com/api/timedtext?v=abc&lang=en&fmt=srv3&pot=XYZ&tlang=id"
        assertEquals("https://www.youtube.com/api/timedtext?v=abc&lang=en&fmt=json3&pot=XYZ&tlang=id", YouTubeCaptions.asJson3(u))
        assertEquals("https://www.youtube.com/api/timedtext?v=abc&lang=id&fmt=json3", YouTubeCaptions.asJson3("https://www.youtube.com/api/timedtext?v=abc&lang=id"))
        assertEquals("id", YouTubeCaptions.langOf(u))                                     // translated: the language it was turned into
        assertEquals("en", YouTubeCaptions.langOf("https://www.youtube.com/api/timedtext?v=abc&lang=en&pot=1"))
    }
}
