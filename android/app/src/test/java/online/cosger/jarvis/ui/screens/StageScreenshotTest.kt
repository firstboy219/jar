package online.cosger.jarvis.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.Modifier
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import online.cosger.jarvis.net.ConsoleApi
import online.cosger.jarvis.ui.Board
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.ServerUsage
import online.cosger.jarvis.ui.TurnState
import online.cosger.jarvis.ui.console.MoreScreen
import online.cosger.jarvis.ui.stage.BrainGraph
import online.cosger.jarvis.ui.stage.BrainView
import online.cosger.jarvis.ui.stage.Panel
import online.cosger.jarvis.ui.stage.StageActions
import online.cosger.jarvis.ui.stage.StageHost
import online.cosger.jarvis.ui.stage.StageState
import online.cosger.jarvis.ui.theme.JarvisColors
import online.cosger.jarvis.ui.theme.JarvisTheme
import online.cosger.jarvis.voice.MicState
import org.junit.Rule
import org.junit.Test
import kotlin.math.cos
import kotlin.math.sin

/** The v0.7 front screen ("Panggung") and console menu, rendered without a phone. */
class StageScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val actions = StageActions(ConsoleApi({ "https://vis1.cosger.online" }, { "jdv_x" }), { _, _ -> }, {}, false)

    private val brain = BrainGraph(
        nodes = (0 until 90).map { i ->
            val a = i * 0.7f
            val side = if (i % 2 == 0) 1f else -1f
            BrainGraph.Node("n$i", side * (0.25f + 0.4f * ((i * 37) % 10) / 10f), 0.5f * sin(a), 0.8f * cos(a),
                listOf("personal", "project", "knowledge", "experience", "operational")[i % 5], "memori $i")
        },
        edges = (0 until 89).map { it to (it + 2) % 90 },
        active = setOf("n3", "n10"),
        colors = mapOf("personal" to 0xFF4FC3F7, "project" to 0xFFFFB74D, "knowledge" to 0xFF81C784,
                       "experience" to 0xFFBA68C8, "operational" to 0xFFE57373),
        total = 128,
    )

    private fun panel(kind: String, json: String, caption: String = "") =
        StageState(panel = Panel("p1", kind, Json.parseToJsonElement(json).jsonObject, caption))

    private fun talk(stage: StageState, turn: TurnState = TurnState()) = paparazzi.snapshot {
        JarvisTheme {
            TalkContent(turn, MicState.Ready, 0f, "", false, Board(), true, {}, {}, {}, {},
                panelOpen = stage.panel != null,
                stageContent = { StageHost(stage, brain, turn.phase != Phase.Idle, actions, Modifier.fillMaxSize()) })
        }
    }

    @Test fun brainIdle() = talk(StageState(pulses = mapOf("n5" to StageState.Pulse("write", System.currentTimeMillis()))))

    @Test fun replyDrafts() = talk(panel("draft", """{"to":"Bu Rina","channel":"whatsapp","summary":"minta rapat besok jam 9",
        "variants":[{"label":"Singkat","text":"Bisa, Bu."},{"label":"Santai","text":"Siap Bu, jam 9 ya, sampai besok."},
        {"label":"Formal","text":"Baik Bu Rina, saya bisa hadir besok pukul 09.00. Terima kasih."}]}""", "Draf balasan untuk Bu Rina"),
        TurnState(phase = Phase.Done, userText = "Bantu balas ini", answer = "Drafnya sudah di layar, pilih yang cocok ya."))

    @Test fun document() = talk(panel("doc", """{"title":"Notulen — UAT Autotoko","url":"/api/v1/documents/1","format":"docx"}""",
        "Dokumen: Notulen — UAT Autotoko"))

    @Test fun webLoginAsksFirst() = talk(panel("web", """{"url":"https://ibank.klikbca.co.id","mode":"login","domain":"ibank.klikbca.co.id"}""",
        "Masuk ke KlikBCA"))

    @Test fun waitingForHeyJarvis() = paparazzi.snapshot {
        JarvisTheme {
            TalkContent(TurnState(), MicState.Muted, 0f, "", false, Board(), true, {}, {}, {}, {},
                stageContent = { StageHost(StageState(), brain, false, actions, Modifier.fillMaxSize()) }, wakeListening = true)
        }
    }

    /** Home: the brain fills the screen behind the conversation; the memories in use are listed. */
    @Test fun brainBackgroundWithMemoriesInUse() {
        val now = System.currentTimeMillis()
        val stage = StageState().pulse(listOf("n3", "n7"), "read", listOf("Suka kopi tanpa gula", "Kantor di BSD"), nowMs = now)
        paparazzi.snapshot {
            JarvisTheme {
                TalkContent(TurnState(phase = Phase.Done, userText = "Mampir kopi dekat kantor?", answer = "Ada dua kedai di BSD yang buka sekarang."),
                    MicState.Ready, 0f, "", false, Board(), true, {}, {}, {}, {},
                    stageContent = { StageHost(stage, brain, false, actions, Modifier.fillMaxSize()) },
                    background = { BrainView(brain, stage.pulses, false, Modifier.fillMaxSize(), dim = 1f, centerY = BRAIN_CENTER_Y, zoom = BRAIN_ZOOM) },
                    involved = stage.involved.map { it.label },
                    server = ServerUsage(34.0, 1.2, 4, 7.4, 15.6, 0.3, 62.0, 198.0, 320.0, 1, 2, 0.42, 20.0))
            }
        }
    }

    /** Anything at once on the front screen: a note, a map, a document, over the dimmed brain. */
    @Test fun boardWithAnything() {
        val stage = panel("board", """{"title":"Persiapan ke Bandung","blocks":[
            {"kind":"text","title":"Catatan","text":"1. Berangkat 06.00\n2. Isi bensin di rest area KM 57\n3. Rapat 10.00"},
            {"kind":"doc","title":"Agenda rapat","url":"/api/v1/documents/2","format":"pdf"},
            {"kind":"text","text":"Cuaca Bandung: cerah berawan, 22–29°C"}]}""", "Persiapan ke Bandung")
        paparazzi.snapshot {
            JarvisTheme {
                TalkContent(TurnState(), MicState.Ready, 0f, "", false, Board(), true, {}, {}, {}, {},
                    panelOpen = true, stageContent = { StageHost(stage, brain, false, actions, Modifier.fillMaxSize()) },
                    background = { BrainView(brain, emptyMap(), false, Modifier.fillMaxSize(), dim = 0.45f, centerY = BRAIN_CENTER_Y, zoom = BRAIN_ZOOM) })
            }
        }
    }

    @Test fun consoleMenu() = paparazzi.snapshot { JarvisTheme { Box(Modifier.background(JarvisColors.Background)) { MoreScreen {} } } }

}
