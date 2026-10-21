package online.cosger.jarvis.ocr

import org.junit.Assert.assertEquals
import org.junit.Test

class ScreenTextTest {
    @Test fun readsTopToBottomWithoutStatusBar() {
        val text = ScreenText.arrange(listOf(300 to "Bu Rina", 10 to "09:41", 12 to "87%", 400 to "Pak, bisa rapat besok jam 9?", 350 to "online"))
        assertEquals("Bu Rina\nonline\nPak, bisa rapat besok jam 9?", text)
    }
}
