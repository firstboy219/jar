package online.cosger.jarvis.ui.screens

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import online.cosger.jarvis.ui.Board
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.SpokenReport
import online.cosger.jarvis.ui.ToolActivity
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.ui.Worker
import online.cosger.jarvis.ui.theme.JarvisTheme
import online.cosger.jarvis.voice.MicState
import org.junit.Rule
import org.junit.Test

/** Renders the talk screen in its key states (no emulator needed): ./gradlew recordPaparazziDebug */
class TalkScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val workers = Board(
        workers = listOf(
            Worker(4, "Cek harga emas Antam", "running", TurnState(
                phase = Phase.Acting,
                thoughts = "Owner wants today's Antam price. Check logammulia.com first, then compare with Pegadaian.",
                tools = listOf(ToolActivity("a", "Mencari di web", "harga emas antam hari ini", "", false),
                    ToolActivity("b", "Membaca halaman web", "logammulia.com/id/harga-emas", "", true)),
            )),
            Worker(5, "Kurs dolar ke rupiah", "queued"),
        ),
        reports = listOf(SpokenReport(9, 3, "Cuaca Pondok Aren siang ini cerah, 35 derajat dan terasa 39. UV sangat tinggi, jadi pakai tabir surya ya.", 2, true, SpokenReport.State.Spoken)),
    )

    private fun shot(turn: TurnState, mic: MicState, board: Board = Board(), interim: String = "", speaking: Boolean = false, connected: Boolean = true) =
        paparazzi.snapshot {
            JarvisTheme { TalkContent(turn, mic, 0.6f, interim, speaking, board, connected, {}, {}, {}, {}) }
        }

    @Test fun mutedIdle() = shot(TurnState(), MicState.Muted)
    @Test fun preparing() = shot(TurnState(), MicState.Preparing)
    @Test fun readyWithWorkersAndReport() = shot(
        TurnState(phase = Phase.Done, userText = "Cek harga emas sama kurs dolar ya", answer = "Oke, aku cek dulu ya, nanti aku kabari."),
        MicState.Ready, workers,
    )
    @Test fun hearing() = shot(TurnState(), MicState.Hearing, interim = "Ngomong-ngomong, kopi atau teh yang")
    @Test fun jarvisSpeaking() = shot(TurnState(phase = Phase.Done, answer = "Teh hangat cocok buat pagi ini."), MicState.Paused, speaking = true)
}
