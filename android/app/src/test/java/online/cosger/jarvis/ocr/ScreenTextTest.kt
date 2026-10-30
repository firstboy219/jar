package online.cosger.jarvis.ocr

import org.junit.Assert.assertEquals
import org.junit.Test

class ScreenTextTest {
    @Test fun readsTopToBottomWithoutStatusBar() {
        val text = ScreenText.arrange(listOf(300 to "Bu Rina", 10 to "09:41", 12 to "87%", 400 to "Pak, bisa rapat besok jam 9?", 350 to "online"))
        assertEquals("Bu Rina\nonline\nPak, bisa rapat besok jam 9?", text)
    }

    @Test fun findsTheGuidesTargetOnTheScreen() {
        val lines = listOf(ScreenText.Line("Beranda", 0, 0, 100, 40), ScreenText.Line("Pengaturan Notifikasi", 10, 300, 400, 340),
            ScreenText.Line("Notifikasi", 10, 500, 200, 540), ScreenText.Line("Akun Saya", 600, 20, 700, 60))
        assertEquals(500, ScreenText.findTarget(lines, "Notifikasi")?.top)                 // the same words first
        assertEquals(300, ScreenText.findTarget(lines, "pengaturan notifikasi")?.top)
        assertEquals(20, ScreenText.findTarget(lines, "Akun")?.top)                        // the shortest line containing it
        assertEquals(null, ScreenText.findTarget(lines, "Transfer"))
        assertEquals(null, ScreenText.findTarget(lines, ""))
    }
}
