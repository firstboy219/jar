package online.cosger.jarvis.ui.console

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.d
import online.cosger.jarvis.ui.stage.i
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s
import online.cosger.jarvis.ui.theme.JarvisColors
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

/** Pure helpers for model numbers (unit-tested). */
object ModelStats {
    fun ms(v: Int?): String = when {
        v == null -> "?"
        v >= 1000 -> String.format(java.util.Locale.ROOT, "%.1f dtk", v / 1000.0).replace('.', ',')
        else -> "$v ms"
    }

    /** 2 = reliable (≥ 95 %), 1 = shaky (85–95 %), 0 = bad, -1 = not enough data. */
    fun level(okPct: Double?, calls: Int): Int = when {
        okPct == null || calls < 5 -> -1
        okPct >= 95 -> 2
        okPct >= 85 -> 1
        else -> 0
    }

    fun levelColor(level: Int): Color = when (level) {
        2 -> JarvisColors.Green
        1 -> JarvisColors.Amber
        0 -> JarvisColors.Red
        else -> JarvisColors.Muted
    }

    fun cost(v: Double?): String = when {
        v == null -> "?"
        v == 0.0 -> "gratis"
        v < 0.0001 -> "<\$0.0001"
        else -> "\$" + String.format(java.util.Locale.ROOT, "%.4f", v).trimEnd('0').trimEnd('.')
    }

    /** "ditolak OpenRouter (403) ×9, timeout ×2": the most frequent causes first. */
    fun errorsText(errors: JsonObject, top: Int = 3): String =
        errors.entries.mapNotNull { (k, v) -> ((v as? JsonPrimitive)?.intOrNull)?.let { k to it } }
            .sortedByDescending { it.second }.take(top).joinToString(", ") { "${it.first} ×${it.second}" }

    /** One line a list row shows about a model JARVIS has used. */
    fun badge(calls: Int?, okPct: Double?, p50: Int?): String? =
        if (calls == null || calls <= 0) null
        else "dipakai ${calls}× · ${okPct?.let { String.format(java.util.Locale.ROOT, "%.0f", it) + "% berhasil" } ?: "?"} · median ${ms(p50)}"
}

/**
 * Everything to choose a model on: advantages, drawbacks, what it is good for, how often it fails and how fast it
 * answers — from OpenRouter's catalog, OpenRouter's own provider stats, JARVIS' real calls and a live test.
 * [onPick] shows "Pakai sebagai …" buttons (from the model picker); null = information only (Statistik model).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ModelDetailDialog(vm: JarvisViewModel, modelId: String, category: String?, onPick: ((String) -> Unit)?, onDismiss: () -> Unit) {
    val scope = rememberCoroutineScope()
    var tick by remember { mutableIntStateOf(0) }
    var benching by remember { mutableStateOf(false) }
    val data = rememberLoad(modelId, tick) {
        vm.console.get("/api/v1/console/models/$modelId/insight" + (category?.let { "?category=$it" } ?: "")).obj()
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = JarvisColors.Background) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                LoadState(data) { d ->
                    if (d.s("error").isNotBlank()) { Body(d.s("error")); return@LoadState }
                    val m = d["model"].obj()
                    Text(m.s("name"), color = JarvisColors.Text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                    Small(m.s("id"))
                    Small("${Models.price(m.b("free"), m.d("price_in"), m.d("price_out"))} · konteks ${Models.context(m.i("context") ?: 0)}" +
                        Models.tags(m).joinToString("") { " · $it" }, JarvisColors.Cyan)
                    if (m.s("description").isNotBlank()) Small(m.s("description"))
                    d["untuk_kategori"].obj().takeIf { it.isNotEmpty() }?.let { k ->
                        Card(border = if (k.b("cocok")) JarvisColors.Green else JarvisColors.Amber) { Body(k.s("kata"), size = 13) }
                    }
                    Card(border = JarvisColors.Green) {
                        Label("Kelebihan", JarvisColors.Green)
                        val pros = d["kelebihan"].arr()
                        if (pros.isEmpty()) Small("Belum ada yang menonjol dari data yang ada.")
                        pros.forEach { Body("✓ " + (it as JsonPrimitive).content, size = 13) }
                    }
                    Card(border = JarvisColors.Amber) {
                        Label("Kekurangan", JarvisColors.Amber)
                        val cons = d["kekurangan"].arr()
                        if (cons.isEmpty()) Small("Tidak ada yang mencolok.")
                        cons.forEach { Body("⚠ " + (it as JsonPrimitive).content, size = 13) }
                    }
                    val good = d["cocok_untuk"].arr().map { it.obj().s("nama") }
                    if (good.isNotEmpty()) Card { Label("Cocok untuk"); Body(good.joinToString(" · "), size = 13) }

                    val mk = d["pasar"].obj()
                    Card {
                        Label("Di OpenRouter (semua penyedia, 30 menit terakhir)")
                        if (mk.isEmpty()) Small("Data pasar tidak tersedia.") else {
                            Body("Mulai menjawab: median ${ModelStats.ms(mk.d("latency_p50_ms")?.toInt())} · 90% di bawah ${ModelStats.ms(mk.d("latency_p90_ms")?.toInt())}", size = 13)
                            Body("Menulis: ~${mk.d("throughput_p50")?.let { String.format(java.util.Locale.ROOT, "%.0f", it) } ?: "?"} token/detik " +
                                "(tercepat ${mk.d("throughput_best")?.let { String.format(java.util.Locale.ROOT, "%.0f", it) } ?: "?"})", size = 13)
                            Body("Aktif sehari terakhir: ${mk.d("uptime_1d_avg") ?: "?"}% (terburuk ${mk.d("uptime_1d_min") ?: "?"}%) · ${mk.i("providers") ?: 0} penyedia", size = 13)
                        }
                    }
                    val jv = d["jarvis"].obj()
                    Card(border = ModelStats.levelColor(ModelStats.level(jv.d("ok_pct"), jv.i("calls") ?: 0))) {
                        Label("Di JARVIS (14 hari, pemakaian nyata)")
                        if (jv.isEmpty()) Small("Belum pernah dipakai JARVIS.") else {
                            Body("${jv.i("calls")} panggilan · ${jv.d("ok_pct")?.let { String.format(java.util.Locale.ROOT, "%.0f", it) } ?: "?"}% berhasil", size = 13)
                            Body("Waktu per panggilan: median ${ModelStats.ms(jv.i("p50_ms"))} · 95% di bawah ${ModelStats.ms(jv.i("p95_ms"))}" +
                                (jv.i("first_token_ms")?.let { " · token pertama ${ModelStats.ms(it)}" } ?: ""), size = 13)
                            Body("Biaya rata-rata ${ModelStats.cost(jv.d("cost_per_call_usd"))} per panggilan · total ${ModelStats.cost(jv.d("cost_usd"))}", size = 13)
                            ModelStats.errorsText(jv["errors"].obj()).takeIf { it.isNotBlank() }?.let { Small("Gagal karena: $it", JarvisColors.Amber) }
                            if ((jv.i("credit_fails") ?: 0) > 0) Small("${jv.i("credit_fails")} panggilan gagal karena kredit habis tidak dihitung ke persen berhasil.")
                        }
                    }
                    val t = d["uji"].obj()
                    Card {
                        Label("Uji langsung")
                        if (t.isEmpty()) Small("Belum pernah diuji.") else if (!t.b("ok")) Body("Uji terakhir gagal: ${t.s("error").take(160)}", JarvisColors.Red, 13) else {
                            Body("Token pertama ${ModelStats.ms(t.i("first_ms"))} · selesai ${ModelStats.ms(t.i("total_ms"))} · ${t.d("tok_s")?.let { String.format(java.util.Locale.ROOT, "%.0f", it) } ?: "?"} token/detik", size = 13)
                            Body(when { t["tools_ok"]?.toString() == "true" -> "Memanggil alat: lulus"; t["tools_ok"]?.toString() == "false" -> "Memanggil alat: GAGAL"; else -> "Memanggil alat: tidak teruji" }, size = 13)
                            Small(t.s("at").take(16).replace('T', ' ') + " · biaya ${ModelStats.cost(t.d("cost_usd"))}")
                        }
                        Action(if (benching) "Menguji… (10–60 detik)" else "Uji sekarang (≈ \$0.0001)", enabled = !benching) {
                            benching = true
                            scope.launch {
                                runCatching { vm.console.post("/api/v1/console/models/bench", buildJsonObject { put("model", modelId) }) }
                                    .onFailure { vm.notify(it.message ?: "Gagal menguji") }
                                benching = false
                                tick++
                            }
                        }
                    }
                    Small(d.s("catatan"))
                    if (onPick != null) FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Action("Pakai sebagai utama", JarvisColors.Green) { onPick("utama") }
                        Action("Pakai sebagai cadangan") { onPick("cadangan") }
                    }
                }
                Action("Tutup", JarvisColors.Muted, onClick = onDismiss)
            }
        }
    }
}

/** Statistik model: every model JARVIS called, how often it failed and why, how fast. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ModelStatsScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    var days by remember { mutableIntStateOf(7) }
    var sort by remember { mutableStateOf("pakai") }
    var open by remember { mutableStateOf<String?>(null) }
    val data = rememberLoad(days) { vm.console.get("/api/v1/console/models/stats?days=$days").obj() }
    ConsolePage("Statistik model", onBack, data.reload) {
        Small("Dari panggilan nyata JARVIS (bukan uji). Kegagalan karena kredit habis tidak dihitung sebagai salah model.")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(1 to "1 hari", 7 to "7 hari", 30 to "30 hari").forEach { (d, label) ->
                Action(label, if (days == d) JarvisColors.Green else JarvisColors.Muted) { days = d }
            }
        }
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("pakai" to "Terbanyak dipakai", "error" to "Paling sering error", "cepat" to "Tercepat").forEach { (k, label) ->
                Action(label, if (sort == k) JarvisColors.Amber else JarvisColors.Muted) { sort = k }
            }
        }
        LoadState(data) { o ->
            val models = o["models"].arr().map { it.obj() }.sortedWith(when (sort) {
                "error" -> compareBy<JsonObject> { it.d("ok_pct") ?: 101.0 }.thenByDescending { it.i("calls") ?: 0 }
                "cepat" -> compareBy<JsonObject> { it.i("p50_ms") ?: Int.MAX_VALUE }
                else -> compareByDescending<JsonObject> { it.i("calls") ?: 0 }
            })
            if (models.isEmpty()) Small("Belum ada panggilan dalam $days hari terakhir.")
            models.forEach { s ->
                val cloud = s.s("provider") == "openrouter"
                val level = ModelStats.level(s.d("ok_pct"), s.i("counted_calls") ?: 0)
                Card(Modifier.let { if (cloud) it.androidClickable { open = s.s("model") } else it }, border = ModelStats.levelColor(level)) {
                    Body(if (cloud) s.s("model") else if (s.s("provider") == "lokal") "Model lokal — ngobrol" else "Model lokal — kerja", size = 14)
                    Small("${s.i("calls")} panggilan · ${s.d("ok_pct")?.let { String.format(java.util.Locale.ROOT, "%.0f", it) } ?: "?"}% berhasil · " +
                        "median ${ModelStats.ms(s.i("p50_ms"))} · 95% di bawah ${ModelStats.ms(s.i("p95_ms"))}", ModelStats.levelColor(level))
                    Small("${ModelStats.cost(s.d("cost_per_call_usd"))} per panggilan · total ${ModelStats.cost(s.d("cost_usd"))}")
                    ModelStats.errorsText(s["errors"].obj()).takeIf { it.isNotBlank() }?.let { Small("Gagal karena: $it", JarvisColors.Amber) }
                    if (cloud) Small("Ketuk untuk kelebihan, kekurangan dan uji langsung", JarvisColors.Cyan)
                }
            }
        }
    }
    open?.let { ModelDetailDialog(vm, it, null, null) { open = null } }
}

private fun Modifier.androidClickable(onClick: () -> Unit): Modifier = this.clickable(onClick = onClick)
