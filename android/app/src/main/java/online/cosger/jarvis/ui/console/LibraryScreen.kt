package online.cosger.jarvis.ui.console

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.d
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.openFile
import online.cosger.jarvis.ui.stage.s
import online.cosger.jarvis.ui.theme.JarvisColors
import java.io.File
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Pure helpers of Simpanan (unit-tested). */
object Library {
    /** Filter chips: label → server kind ("" = all). */
    val FILTERS = listOf(
        "Semua" to "", "Musik" to "musik", "Playlist" to "playlist", "Dokumen" to "dokumen", "Draf" to "draf",
        "Gambar" to "gambar", "Video" to "video", "Web" to "web", "Peta" to "peta", "Catatan" to "teks", "Rapat" to "rapat",
    )

    fun kindLabel(kind: String): String = when (kind) {
        "teks" -> "Catatan"
        "lainnya", "" -> "Lainnya"
        else -> FILTERS.firstOrNull { it.second == kind }?.first ?: kind.replaceFirstChar { it.uppercase() }
    }

    /** "Putar" for sound, "Tampilkan" for the rest. */
    fun showLabel(kind: String): String = if (kind == "musik" || kind == "playlist") "Putar" else "Tampilkan"

    /** A file to open/share on the phone: JARVIS' own documents and songs (pictures/videos are shown instead). */
    fun downloadable(url: String): Boolean = url.startsWith("/api/v1/documents/") || url.startsWith("/api/v1/media/")

    fun date(epochSeconds: Double, now: Long = System.currentTimeMillis()): String {
        val at = Date((epochSeconds * 1000).toLong())
        val sameDay = SimpleDateFormat("yyyyMMdd", Locale.ROOT).let { it.format(at) == it.format(Date(now)) }
        return SimpleDateFormat(if (sameDay) "'hari ini' HH:mm" else "d MMM yyyy HH:mm", Locale("id")).format(at)
    }

    fun path(key: String): String = URLEncoder.encode(key, "UTF-8")
}

/** Simpanan: everything JARVIS made or showed — songs, playlists, documents, drafts, pictures, videos, pages, maps, notes, minutes. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun LibraryScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var kind by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var asked by remember { mutableStateOf<JsonObject?>(null) }
    val data = rememberLoad(kind, query) {
        vm.console.get("/api/v1/console/library?kind=$kind&q=${URLEncoder.encode(query, "UTF-8")}").obj()
    }
    fun act(path: String, done: String, body: JsonObject? = null) = scope.launch {
        runCatching { if (body != null) vm.console.post(path, body) else vm.console.post(path) }
            .onSuccess { vm.notify(done); data.reload() }.onFailure { vm.notify(it.message ?: "Gagal") }
    }
    fun file(o: JsonObject, how: String) = scope.launch {
        val ext = o.s("format").ifBlank { "bin" }
        runCatching { vm.console.download(o.s("url"), File(context.cacheDir, "docs/${o.s("title").take(60).replace(Regex("[^A-Za-z0-9 _-]"), "")}.$ext")) }
            .onSuccess { openFile(context, it, how) }.onFailure { vm.notify(it.message ?: "Gagal") }
    }
    ConsolePage("Simpanan", onBack, data.reload) {
        Small("Semua yang pernah dibuat atau ditampilkan JARVIS. Lagu dihapus otomatis setelah 30 hari — tandai ★ Simpan agar tetap ada. " +
            "Bisa juga lewat suara: \"tampilkan lagi gambar tadi\".")
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Library.FILTERS.forEach { (label, k) ->
                Action(label, if (k == kind) JarvisColors.Green else JarvisColors.Muted) { kind = k }
            }
        }
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Cari judul") })
        LoadState(data) { o ->
            val items = o["items"].arr().map { it.obj() }
            if (items.isEmpty()) Small(if (kind.isBlank() && query.isBlank()) "Masih kosong." else "Tidak ada yang cocok.")
            items.forEach { x ->
                val key = Library.path(x.s("key"))
                Card(border = if (x.b("kept")) JarvisColors.Amber else JarvisColors.Border) {
                    Body((if (x.b("kept")) "★ " else "") + x.s("title"), size = 14)
                    Small(listOf(Library.kindLabel(x.s("kind")), x.s("subtitle"), Library.date(x.d("at") ?: 0.0))
                        .filter { it.isNotBlank() }.joinToString(" · "))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Action(Library.showLabel(x.s("kind")), JarvisColors.Green) {
                            act("/api/v1/console/library/$key/show", "Dibuka di layar depan.")
                        }
                        if (Library.downloadable(x.s("url"))) {
                            Action("Buka") { file(x, "view") }
                            Action("Bagikan") { file(x, "share") }
                        }
                        Action(if (x.b("kept")) "Lepas ★" else "★ Simpan", JarvisColors.Amber) {
                            act("/api/v1/console/library/$key/keep", if (x.b("kept")) "Tidak lagi disimpan permanen." else "Disimpan permanen.",
                                buildJsonObject { put("keep", !x.b("kept")) })
                        }
                        if (x.s("kind") != "rapat") Action("Hapus", JarvisColors.Red) { asked = x }
                    }
                }
            }
        }
    }
    asked?.let { x ->
        AlertDialog(
            onDismissRequest = { asked = null },
            title = { Text("Hapus \"${x.s("title").take(60)}\"?") },
            text = { Text("Dihapus permanen dari server, termasuk filenya.") },
            confirmButton = {
                TextButton({
                    val key = Library.path(x.s("key"))
                    scope.launch {
                        runCatching { vm.console.delete("/api/v1/console/library/$key") }
                            .onSuccess { vm.notify("Dihapus.") }.onFailure { vm.notify(it.message ?: "Gagal") }
                        data.reload()
                    }
                    asked = null
                }) { Text("Hapus") }
            },
            dismissButton = { TextButton({ asked = null }) { Text("Batal") } },
        )
    }
}
