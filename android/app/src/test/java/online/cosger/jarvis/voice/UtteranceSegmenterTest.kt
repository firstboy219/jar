package online.cosger.jarvis.voice

import online.cosger.jarvis.voice.UtteranceSegmenter.Output
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UtteranceSegmenterTest {
    private fun result(t: String, final: Boolean, speechFinal: Boolean = false) =
        """{"type":"Results","is_final":$final,"speech_final":$speechFinal,"channel":{"alternatives":[{"transcript":"$t"}]}}"""

    @Test fun accumulatesFinalSegmentsUntilSpeechFinal() {
        val s = UtteranceSegmenter()
        assertEquals(listOf(Output.SpeechStarted), s.feed("""{"type":"SpeechStarted"}"""))
        assertEquals(listOf(Output.Interim("tolong cek")), s.feed(result("tolong cek", final = false)))
        assertEquals(listOf(Output.Interim("tolong cek harga emas")), s.feed(result("tolong cek harga emas", final = true)))
        assertEquals(
            listOf(Output.Interim("tolong cek harga emas hari ini"), Output.Utterance("tolong cek harga emas hari ini")),
            s.feed(result("hari ini", final = true, speechFinal = true)),
        )
        assertEquals("", s.partial)
    }

    @Test fun utteranceEndIsABackupWhenSpeechFinalIsMissed() {
        val s = UtteranceSegmenter()
        s.feed(result("status server", final = true))
        assertEquals(listOf(Output.Utterance("status server")), s.feed("""{"type":"UtteranceEnd","last_word_end":2.1}"""))
        assertTrue("nothing left to send twice", s.feed("""{"type":"UtteranceEnd"}""").isEmpty())
    }

    @Test fun noiseWithoutWordsSendsNothing() {
        val s = UtteranceSegmenter()
        assertTrue(s.feed(result("", final = true, speechFinal = true)).isEmpty())
        assertTrue(s.feed("garbage").isEmpty())
    }
}
