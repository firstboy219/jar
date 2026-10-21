package online.cosger.jarvis.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class VadSegmenterTest {
    private val frame = ByteArray(1024) // 32 ms of PCM16 at 16 kHz

    private fun VadSegmenter.run(probs: List<Float>) = probs.mapNotNull { feed(frame, it) }

    @Test fun utteranceKeepsPreRollAndEndsAfterThePause() {
        val seg = VadSegmenter(endSilenceMs = 320)
        val events = seg.run(List(5) { 0.1f } + List(20) { 0.9f } + List(10) { 0.05f })
        assertEquals(VadSegmenter.Event.Started, events.first())
        val ended = events.last() as VadSegmenter.Event.Ended
        // pre-roll (5 quiet frames before the 2 start frames are kept) + speech + the closing silence
        assertTrue(ended.pcm.size >= (5 + 20 + 10) * 1024 - 2 * 1024)
    }

    @Test fun clicksAreNotUtterances() {
        val seg = VadSegmenter(endSilenceMs = 320)
        val events = seg.run(listOf(0.9f, 0.9f) + List(12) { 0.0f })
        assertEquals(listOf(VadSegmenter.Event.Started), events) // started, then dropped as too short
    }

    @Test fun oneLoudFrameDoesNotStartSpeech() {
        val seg = VadSegmenter()
        assertNull(seg.feed(frame, 0.95f))
        assertNull(seg.feed(frame, 0.1f))
    }

    @Test fun longSpeechIsCutAtTheMaximum() {
        val seg = VadSegmenter(maxMs = 1_000)
        val events = seg.run(List(60) { 0.9f })
        assertTrue(events.any { it is VadSegmenter.Event.Ended })
    }
}
