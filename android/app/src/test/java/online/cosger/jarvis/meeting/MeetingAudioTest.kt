package online.cosger.jarvis.meeting

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MeetingAudioTest {
    @Test fun adtsHeaderDescribesAnAacLcMonoFrameOf16kHz() {
        val h = Adts.header(93)
        assertEquals(7, h.size)
        assertEquals(0xFF, h[0].toInt() and 0xFF)
        assertEquals(0xF1, h[1].toInt() and 0xFF)                  // MPEG-4, no CRC
        assertEquals(1, (h[2].toInt() and 0xFF) ushr 6)            // profile AAC-LC
        assertEquals(8, ((h[2].toInt() and 0xFF) ushr 2) and 0xF)  // 16000 Hz
        assertEquals(1, (((h[2].toInt() and 1) shl 2) or ((h[3].toInt() and 0xFF) ushr 6)))  // mono
        assertEquals(100, Adts.frameLength(h))                     // payload + 7
        assertEquals(2047, Adts.frameLength(Adts.header(2040)))    // longer frames keep their length field
    }

    @Test fun aChunkIsSixtySecondsOfWholeFrames() {
        assertEquals(937, Adts.FRAMES_PER_CHUNK)
        val seconds = Adts.FRAMES_PER_CHUNK * Adts.SAMPLES_PER_FRAME / Adts.SAMPLE_RATE.toDouble()
        assertTrue(seconds in 59.9..60.0)
    }

    private fun pcm(vararg samples: Int): ByteArray = ByteArray(samples.size * 2).also { b ->
        samples.forEachIndexed { i, s -> b[2 * i] = (s and 0xFF).toByte(); b[2 * i + 1] = (s shr 8).toByte() }
    }

    @Test fun levelFollowsTheLoudnessOfTheRoom() {
        assertEquals(0f, RoomLevel.rms(pcm(0, 0, 0, 0), 8), 0f)
        val loud = RoomLevel.rms(pcm(16_000, -16_000, 16_000, -16_000), 8)
        assertEquals(0.488f, loud, 0.01f)
        assertTrue(RoomLevel.meter(loud) > 0.9f)
        assertEquals(0f, RoomLevel.meter(0f), 0f)
        assertTrue(RoomLevel.meter(0.001f) < 0.1f)   // −60 dBFS: nobody talking
        val murmur = RoomLevel.rms(pcm(300, -300, 300, -300), 8)  // ≈ −40 dBFS, a distant speaker
        assertTrue(RoomLevel.meter(murmur) in 0.3f..0.5f)
    }

    @Test fun warnsOnlyAfterALongSilence() {
        var quiet = 0f
        repeat(19) { quiet = RoomLevel.quietSeconds(quiet, 0.001f, 1f) }
        assertEquals(19f, quiet, 0f)
        assertEquals(0f, RoomLevel.quietSeconds(quiet, 0.05f, 1f), 0f)  // someone spoke: the count restarts
        assertFalse(online.cosger.jarvis.meeting.MeetingRecorder.State(recording = true, quietS = 19f).tooQuiet)
        assertTrue(online.cosger.jarvis.meeting.MeetingRecorder.State(recording = true, quietS = 21f).tooQuiet)
        assertFalse(online.cosger.jarvis.meeting.MeetingRecorder.State(recording = true, paused = true, quietS = 60f).tooQuiet)
    }
}
