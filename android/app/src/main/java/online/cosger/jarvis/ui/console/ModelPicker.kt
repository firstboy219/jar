package online.cosger.jarvis.ui.console

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.clickable
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.delay
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
import java.net.URLEncoder
import java.util.Locale

/** Pure helpers of the model picker (unit-tested). The models themselves come live from OpenRouter's catalog. */
object Models {
    /** Same rules as the server: these categories need tool calling, vision needs images. */
    private val NEEDS_TOOLS = setOf("ngobrol", "web", "coding", "produktivitas", "analisis", "latar-belakang")
    fun needsTools(category: String) = category in NEEDS_TOOLS
    fun needsVision(category: String) = category == "penglihatan"

    val SORTS = listOf("Termurah" to "termurah", "Terbaru" to "terbaru", "Konteks" to "konteks", "Nama" to "nama")

    /** 0.044 → "0.044", 0.89 → "0.89", 15.0 → "15". */
    fun usd(v: Double?): String {
        val x = v ?: return "?"
        val text = if (x < 0.1) String.format(Locale.ROOT, "%.3f", x) else String.format(Locale.ROOT, "%.2f", x)
        return text.trimEnd('0').trimEnd('.').ifEmpty { "0" }
    }

    fun price(free: Boolean, priceIn: Double?, priceOut: Double?): String =
        if (free) "gratis" else "$${usd(priceIn)} masuk / $${usd(priceOut)} keluar per 1 juta token"

    fun context(tokens: Int): String = when {
        tokens >= 1_000_000 -> "${tokens / 1_000_000}M"
        tokens >= 1_000 -> "${tokens / 1_000}K"
        else -> tokens.toString()
    }

    fun tags(m: JsonObject): List<String> =
        listOfNotNull("GRATIS".takeIf { m.b("free") }, "ALAT".takeIf { m.b("tools") }, "GAMBAR".takeIf { m.b("vision") })

    /** A chosen route as the owner reads it: the catalog name, "Model lokal (Qwen)", or the bare id. */
    fun routeLabel(route: JsonObject): String = when {
        route.s("name").isNotBlank() -> route.s("name")
        route.s("provider").startsWith("lokal") -> "Model lokal (Qwen)"
        else -> route.s("model")
    }

    fun routePrice(route: JsonObject): String = when {
        route.s("provider").startsWith("lokal") -> "di server, gratis"
        route["price_in"] != null -> price(route.b("free"), route.d("price_in"), route.d("price_out"))
        else -> route.s("model")
    }

    fun query(q: String, free: Boolean, tools: Boolean, vision: Boolean, sort: String): String =
        "/api/v1/console/openrouter/models?q=${URLEncoder.encode(q.trim(), "UTF-8")}&free=$free&tools=$tools&vision=$vision&sort=$sort&limit=60"
}

/** Full-screen list of OpenRouter's models: search, filters, sorting, price and context; tap one to use it. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ModelPickerDialog(vm: JarvisViewModel, category: String, title: String, role: String, onDone: () -> Unit, onDismiss: () -> Unit) {
    val scope = rememberCoroutineScope()
    val gate = rememberOwnerGate()
    var query by remember { mutableStateOf("") }
    var free by remember { mutableStateOf(false) }
    var tools by remember { mutableStateOf(Models.needsTools(category)) }
    var vision by remember { mutableStateOf(Models.needsVision(category)) }
    var sort by remember { mutableStateOf("termurah") }
    var confirm by remember { mutableStateOf<Pair<JsonObject, String>?>(null) }
    val list = rememberLoad(query, free, tools, vision, sort) {
        delay(300) // typing: only the last keystroke asks the server
        vm.console.get(Models.query(query, free, tools, vision, sort)).obj()
    }
    fun pick(m: JsonObject, confirmed: Boolean) = gate("Pakai ${m.s("name")} untuk $title") {
        scope.launch {
            runCatching {
                vm.console.put("/api/v1/composition/model", buildJsonObject {
                    put("category", category); put("model", m.s("id")); put("role", role); put("confirmed", confirmed)
                }).obj()
            }.onSuccess { r ->
                if (r.b("needs_confirmation")) confirm = m to r.s("say")
                else { vm.notify("$title: ${m.s("name")} dipakai."); onDone() }
            }.onFailure { vm.notify(it.message ?: "Gagal") }
        }
    }
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = JarvisColors.Background) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Pilih model — $title (${if (role == "cadangan") "cadangan" else "utama"})", color = JarvisColors.Text,
                    fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
                Small("Daftar langsung dari OpenRouter. Ketuk satu model untuk memakainya.")
                OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true,
                    label = { Text("Cari (mis. deepseek, claude, qwen)") })
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Action(if (free) "✓ Gratis" else "Gratis", if (free) JarvisColors.Green else JarvisColors.Muted) { free = !free }
                    Action(if (tools) "✓ Bisa alat" else "Bisa alat", if (tools) JarvisColors.Green else JarvisColors.Muted) { tools = !tools }
                    Action(if (vision) "✓ Bisa lihat gambar" else "Bisa lihat gambar", if (vision) JarvisColors.Green else JarvisColors.Muted) { vision = !vision }
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Models.SORTS.forEach { (label, key) ->
                        Action(label, if (sort == key) JarvisColors.Amber else JarvisColors.Muted) { sort = key }
                    }
                }
                LoadState(list) { o ->
                    val models = o["models"].arr().map { it.obj() }
                    Small("${models.size} model ditampilkan dari ${o.i("total") ?: 0}" +
                        if (Models.needsTools(category)) " · kategori ini butuh model yang bisa memakai alat" else "")
                    if (models.isEmpty()) Small("Tidak ada yang cocok — longgarkan filter.")
                    models.forEach { m ->
                        Card(Modifier.clickable { pick(m, false) }) {
                            Body(m.s("name"), size = 14)
                            Small(m.s("id"))
                            Small("${Models.price(m.b("free"), m.d("price_in"), m.d("price_out"))} · konteks ${Models.context(m.i("context") ?: 0)}" +
                                Models.tags(m).joinToString("") { " · $it" }, JarvisColors.Cyan)
                        }
                    }
                }
                Action("Tutup", JarvisColors.Muted, onClick = onDismiss)
            }
        }
    }
    confirm?.let { (m, say) ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("Model mahal") },
            text = { Text(say) },
            confirmButton = { TextButton({ val chosen = m; confirm = null; pick(chosen, true) }) { Text("Tetap pakai") } },
            dismissButton = { TextButton({ confirm = null }) { Text("Batal") } },
        )
    }
}
