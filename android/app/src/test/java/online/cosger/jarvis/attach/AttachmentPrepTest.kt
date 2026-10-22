package online.cosger.jarvis.attach

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AttachmentPrepTest {
    @Test fun recognisesPicturesByTypeOrExtension() {
        assertTrue(AttachmentPrep.isImage("foto.JPG", ""))
        assertTrue(AttachmentPrep.isImage("x", "image/png"))
        assertFalse(AttachmentPrep.isImage("laporan.pdf", "application/pdf"))
    }

    @Test fun shrinksBigPhotosButNeverEnlarges() {
        assertEquals(2, AttachmentPrep.sampleSize(4000, 3000))      // 4000 → 2000 (≥ 1600)
        assertEquals(1, AttachmentPrep.sampleSize(1200, 800))
        assertEquals(4, AttachmentPrep.sampleSize(8000, 6000))      // 8000 → 2000
        assertEquals(1600 to 1200, AttachmentPrep.fit(4000, 3000))
        assertEquals(1200 to 800, AttachmentPrep.fit(1200, 800))
    }

    @Test fun picturesAreSentAsJpegAndFilesKeepTheirName() {
        assertEquals("struk.jpg", AttachmentPrep.uploadName("struk.png", true))
        assertEquals("foto.jpg", AttachmentPrep.uploadName("foto", true))
        assertEquals("kontrak.pdf", AttachmentPrep.uploadName("kontrak.pdf", false))
        assertTrue(AttachmentPrep.tooBig(12_000_001))
        assertFalse(AttachmentPrep.tooBig(1_000_000))
    }
}
