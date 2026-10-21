package online.cosger.jarvis.ui.console

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import kotlinx.coroutines.delay
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.d
import online.cosger.jarvis.ui.stage.i
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s
import online.cosger.jarvis.ui.theme.JarvisColors

private fun duration(seconds: Int?): String = when {
    seconds == null -> "-"
    seconds < 60 -> "$seconds dtk"
    seconds < 3600 -> "${seconds / 60} mnt"
    else -> "${seconds / 3600} jam ${seconds % 3600 / 60} mnt"
}

/**
 * Everything JARVIS does behind the scenes (GET /api/v1/console/background): what runs now and for whom,
 * the 50% rule for its own work, what is scheduled, the last 24 hours, and its log. Refreshes every 10 s.
 */
@Composable
fun BackgroundScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val data = rememberLoad { vm.console.get("/api/v1/console/background").obj() }
    LaunchedEffect(Unit) { while (true) { delay(10_000); data.reload() } }
    ConsolePage("Di balik layar", onBack, data.reload) {
        LoadState(data) { o ->
            val now = o["now"].obj()
            Card(border = JarvisColors.Cyan) {
                Label("Aturan")
                Small(o.s("rule"), JarvisColors.Text)
                Body("CPU sekarang ${"%.0f".format(now.d("cpu_pct") ?: 0.0)}% · kerja latar " +
                    if (now.b("background_allowed")) "boleh berjalan" else "menunggu", size = 13)
                if (now.s("background_reason").isNotBlank()) Small("Alasan: ${now.s("background_reason")}", JarvisColors.Amber)
                Small("Model AI kerja lokal: ${now.s("worker_cpu_why")}")
            }
            Label("Sedang dikerjakan")
            val tasks = now["tasks"].arr().map { it.obj() }
            val calls = now["ai_calls"].arr().map { it.obj() }
            if (tasks.isEmpty() && calls.isEmpty()) Small("Tidak ada — JARVIS sedang diam.")
            tasks.forEach { t ->
                Card(border = if (t.b("mine")) JarvisColors.Green else JarvisColors.Border) {
                    Body("#${t.i("id")} ${t.s("title")}", size = 13)
                    Small("${t.s("what")} · ${t.s("status")} · ${duration(t.i("seconds"))}")
                }
            }
            calls.forEach { c ->
                Small("AI untuk ${c.s("what")} (${c.s("category")}) di ${c.s("place")} · ${duration(c.i("seconds"))}", JarvisColors.Text)
            }
            Label("Terjadwal")
            o["schedule"].arr().map { it.obj() }.forEach { s -> Small("• ${s.s("what")} — ${s.s("when")}", JarvisColors.Text) }
            Label("24 jam terakhir")
            val last = o["last24h"].obj()
            last["tasks"].arr().map { it.obj() }.forEach { t ->
                Small("${t.s("what")}: ${t.i("count")}× · ${"%.0f".format(t.d("minutes") ?: 0.0)} menit", JarvisColors.Text)
            }
            last["ai"].arr().map { it.obj() }.forEach { a ->
                Small("AI ${a.s("what")}: ${a.i("calls")} panggilan · ${"%.0f".format(a.d("minutes") ?: 0.0)} menit" +
                    (if (a.b("local")) " di CPU server" else "") + ((a.d("cost_usd") ?: 0.0).takeIf { it > 0 }?.let { " · $${"%.3f".format(it)}" } ?: ""))
            }
            Label("Catatan")
            val log = o["activity"].arr().map { it.obj() }
            if (log.isEmpty()) Small("Belum ada sejak server terakhir dimulai.")
            log.forEach { a -> Small("${a.s("at").drop(11).take(5)} UTC · ${a.s("text")}", JarvisColors.Text) }
        }
    }
}
