package online.cosger.jarvis.update

import online.cosger.jarvis.ui.stage.fillScript
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class AppUpdaterTest {
    @Test fun offersOnlyNewerAndNotSnoozed() {
        assertTrue(AppUpdater.shouldOffer(latestCode = 10, installedCode = 9, snoozed = false))
        assertFalse(AppUpdater.shouldOffer(10, 10, false))
        assertFalse(AppUpdater.shouldOffer(10, 9, snoozed = true))
    }

    @Test fun checksumMatchesSha256() {
        val f = File.createTempFile("apk", ".bin").apply { writeText("abc") }
        assertTrue(AppUpdater.sha256(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    }

    @Test fun fillScriptEscapesValues() {
        val js = fillScript("ilham", "pa\"ss'\\word</script>")
        assertTrue(js.contains("\"pa\\\"ss'\\\\word</script>\""))
        assertFalse(js.contains("pa\"ss")) // quote is escaped, cannot break out of the string
    }
}
