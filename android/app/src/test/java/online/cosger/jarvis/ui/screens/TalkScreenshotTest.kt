package online.cosger.jarvis.ui.screens

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import online.cosger.jarvis.net.ContextItem
import online.cosger.jarvis.ui.ContextCard
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.ToolActivity
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.ui.theme.JarvisTheme
import org.junit.Rule
import org.junit.Test

/** Renders the walkie-talkie screen in its key states (no emulator needed): ./gradlew recordPaparazziDebug */
class TalkScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val thinking = TurnState(
        phase = Phase.Acting,
        userText = "Gimana progres proyek Autotoko minggu ini?",
        thoughts = "The user is asking about the Autotoko project's progress this week. I should check memory " +
            "for anything stored about Autotoko — marketplace, targets, recent decisions — before answering. " +
            "If nothing is there I'll say so and offer to note the current status.",
        tools = listOf(
            ToolActivity("1", "Mencari di memori", "autotoko progres minggu ini", "⚡", running = false),
            ToolActivity("2", "Melihat workflow n8n", "", "⚡", running = true),
        ),
        context = listOf(
            ContextCard(
                "autotoko progres minggu ini",
                listOf(
                    ContextItem("Autotoko jualan sparepart motor di Shopee dan Tokopedia", "project", 0.82),
                    ContextItem("Target Oktober: 300 order, margin rata-rata 18%", "project", 0.71),
                ),
            ),
        ),
    )

    @Test fun thinkingWithContext() = paparazzi.snapshot {
        JarvisTheme { TalkContent(thinking, "", 0f, connected = true, onPress = {}, onRelease = {}) }
    }

    @Test fun listening() = paparazzi.snapshot {
        JarvisTheme {
            TalkContent(TurnState(phase = Phase.Listening), "Tolong cek status server dan", 0.7f, true, {}, {})
        }
    }

    @Test fun answering() = paparazzi.snapshot {
        JarvisTheme {
            TalkContent(
                thinking.copy(
                    phase = Phase.Answering,
                    tools = thinking.tools.map { it.copy(running = false) },
                    answer = "Autotoko minggu ini: 74 order (target mingguan 75), margin 17,6%. Workflow laporan harian di n8n masih nonaktif — menunggu persetujuanmu (#3).",
                ),
                "", 0f, true, {}, {},
            )
        }
    }

    @Test fun idleDisconnected() = paparazzi.snapshot {
        JarvisTheme { TalkContent(TurnState(), "", 0f, connected = false, onPress = {}, onRelease = {}) }
    }
}
