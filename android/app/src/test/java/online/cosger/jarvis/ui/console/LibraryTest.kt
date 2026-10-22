package online.cosger.jarvis.ui.console

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LibraryTest {
    @Test fun labels() {
        assertEquals("Catatan", Library.kindLabel("teks"))
        assertEquals("Gambar", Library.kindLabel("gambar"))
        assertEquals("Lainnya", Library.kindLabel("lainnya"))
        assertEquals("Putar", Library.showLabel("musik"))
        assertEquals("Tampilkan", Library.showLabel("gambar"))
    }

    @Test fun onlyOwnFilesAreDownloaded() {
        assertTrue(Library.downloadable("/api/v1/documents/abc"))
        assertTrue(Library.downloadable("/api/v1/media/abc"))
        assertFalse(Library.downloadable("https://example.com/x.jpg"))
        assertFalse(Library.downloadable(""))
    }

    @Test fun keysAreEncodedForThePath() {
        assertEquals("shown%3A42", Library.path("shown:42"))
    }

    @Test fun todayIsSaidAsToday() {
        val now = System.currentTimeMillis()
        assertTrue(Library.date(now / 1000.0, now).startsWith("hari ini"))
        assertFalse(Library.date(0.0, now).startsWith("hari ini"))
    }
}
