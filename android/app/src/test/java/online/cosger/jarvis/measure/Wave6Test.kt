package online.cosger.jarvis.measure

import online.cosger.jarvis.guide.GuideNotice
import online.cosger.jarvis.phone.YouTubeCaptions
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Wave6Test {
    @Test fun rulerDistancesLabelsAndProjection() {
        val pts = listOf(Ruler.P(0f, 0f, 0f), Ruler.P(1.2f, 0f, 0f), Ruler.P(1.2f, 0f, 0.6f))
        val segs = Ruler.segments(pts)
        assertEquals(1.2f, segs[0], 1e-4f)
        assertEquals(0.6f, segs[1], 1e-4f)
        assertEquals("60 cm", Ruler.label(0.6f))
        assertEquals("1,20 m", Ruler.label(1.2f))
        val identity = floatArrayOf(1f, 0f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 0f, 1f, 0f, 0f, 0f, 0f, 1f)
        assertEquals(50f to 50f, Ruler.project(identity, Ruler.P(0f, 0f, 0f), 100, 100))
        val behind = identity.clone().also { it[15] = -1f }
        assertNull(Ruler.project(behind, Ruler.P(0f, 0f, 0f), 100, 100))
    }

    @Test fun youtubeCaptionTracksAreFoundAndPicked() {
        val page = """var ytInitialPlayerResponse = {"captions":{"playerCaptionsTracklistRenderer":{"captionTracks":[""" +
            """{"baseUrl":"https://www.youtube.com/api/timedtext?v=abc&lang=en","languageCode":"en","kind":"asr","name":{"simpleText":"[auto]"}},""" +
            """{"baseUrl":"https://www.youtube.com/api/timedtext?v=abc&lang=id","languageCode":"id","name":{"simpleText":"Indonesia ]"}}],"x":1}}};"""
        val tracks = YouTubeCaptions.tracks(page)
        assertEquals(listOf("en", "id"), tracks.map { it.lang })
        assertTrue(tracks[1].url.endsWith("v=abc&lang=id"))
        assertEquals("id", YouTubeCaptions.pick(tracks, listOf("id", "en"))?.lang)
        assertEquals("en", YouTubeCaptions.pick(tracks, listOf("ja"))?.lang)
        assertNull(YouTubeCaptions.tracksJson("no captions here"))
    }

    @Test fun guideScreenKeyIgnoresSpacingAndCase() {
        assertEquals(GuideNotice.key("Pengaturan\n  Akun"), GuideNotice.key("pengaturan akun"))
    }
}
