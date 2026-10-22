package online.cosger.jarvis.ui.console

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Checkbox
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.d
import online.cosger.jarvis.ui.stage.i
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.openFile
import online.cosger.jarvis.ui.stage.s
import online.cosger.jarvis.ui.theme.JarvisColors
import java.io.File

private fun mmss(s: Long) = "%02d:%02d".format(s / 60, s % 60)

/**
 * Rapat: record a meeting (with everyone's consent — Indonesian law since 2026 makes recording without
 * it risky), then read the minutes: summary, decisions, action items, transcript by speaker, the .docx,
 * and ask questions about what was said.
 */
@Composable
fun MeetingsScreen(vm: JarvisViewModel, onBack: (() -> Unit)?, onOpen: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val rec by vm.meetings.state.collectAsStateWithLifecycle()
    val list = rememberLoad(rec.recording, rec.finishing) { vm.console.get("/api/v1/meetings").arr() }
    var title by remember { mutableStateOf("") }
    var confidential by remember { mutableStateOf(false) }
    var consent by remember { mutableStateOf(false) }
    var participants by remember { mutableStateOf("") }
    var agenda by remember { mutableStateOf("") }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(rec.recording) { while (rec.recording) { now = System.currentTimeMillis(); delay(1_000) } }
    fun begin() = scope.launch {
        vm.prepareMeeting()
        vm.meetings.start(title, confidential, participants.split(',', '\n').map { it.trim() }.filter { it.isNotEmpty() }, agenda)
            .onFailure { vm.notify("Rapat tidak bisa dimulai: ${it.message}") }
        title = ""; consent = false; participants = ""; agenda = ""
    }
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { if (it) begin() }

    ConsolePage("Rapat", onBack, list.reload) {
        if (rec.recording || rec.finishing) {
            Card(border = JarvisColors.Red) {
                Label(if (rec.finishing) "Menyelesaikan rekaman…" else if (rec.paused) "Dijeda" else "● Merekam", JarvisColors.Red)
                Body(rec.title)
                Body(mmss(rec.elapsedS(now)), size = 28)
                if (!rec.finishing && !rec.paused) {
                    // what the microphone hears right now: it must move when people talk
                    Box(Modifier.fillMaxWidth().height(8.dp).clip(RoundedCornerShape(4.dp)).background(JarvisColors.SurfaceHigh)) {
                        Box(Modifier.fillMaxWidth(rec.level.coerceIn(0.02f, 1f)).height(8.dp)
                            .background(if (rec.tooQuiet) JarvisColors.Amber else JarvisColors.Green))
                    }
                    if (rec.tooQuiet) Small("Hampir tidak ada suara ${rec.quietS.toInt()} detik terakhir — dekatkan HP ke pembicara atau naikkan volume pembicara.", JarvisColors.Amber)
                    else Small("Suara terdengar. Letakkan HP di tengah meja, jangan tertutup.")
                }
                Small("Potongan ${rec.chunks} · terunggah ${rec.uploaded}" + if (rec.uploaded < rec.chunks) " (menunggu jaringan)" else "")
                if (!rec.finishing) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Action(if (rec.paused) "Lanjut" else "Jeda") { if (rec.paused) vm.meetings.resume() else vm.meetings.pause() }
                    Action("Tandai penting", JarvisColors.Amber) { vm.meetings.mark(); vm.notify("Ditandai di menit ${mmss(rec.elapsedS())}") }
                    Action("Stop & buat notulen", JarvisColors.Red) {
                        vm.meetings.stop { r ->
                            vm.notify(if (r.isSuccess) "Rekaman selesai. Notulen sedang dibuat — JARVIS akan mengabari." else "Gagal: ${r.exceptionOrNull()?.message}")
                            list.reload()
                        }
                    }
                }
                rec.error?.let { Small(it, JarvisColors.Red) }
            }
        } else {
            Card {
                Label("Rekam rapat baru")
                OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("Judul (opsional)") }, singleLine = true)
                OutlinedTextField(participants, { participants = it }, Modifier.fillMaxWidth(),
                    label = { Text("Peserta (nama, pisahkan koma)") }, singleLine = true,
                    supportingText = { Text("Membantu JARVIS menulis nama dengan benar dan menyebut siapa yang bertugas.") })
                OutlinedTextField(agenda, { agenda = it }, Modifier.fillMaxWidth(), label = { Text("Agenda / topik (opsional)") },
                    supportingText = { Text("Istilah, proyek, atau produk yang akan dibahas — dipakai untuk mengenali kata yang sulit.") })
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Body("Rahasia (hanya model lokal)", size = 13)
                    Spacer(Modifier.weight(1f))
                    Switch(confidential, { confidential = it })
                }
                Small("Rahasia: transkrip & notulen dikerjakan di server sendiri, tidak ke cloud (lebih lambat).")
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(consent, { consent = it })
                    Small("Semua peserta sudah tahu dan setuju rapat ini direkam.", JarvisColors.Text)
                }
                Small("Audio panggilan Zoom/Meet/WhatsApp tidak bisa direkam aplikasi — taruh HP di dekat pembicara atau pakai speaker.")
                Action("Mulai rekam", JarvisColors.Red, enabled = consent) {
                    if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) begin()
                    else askMic.launch(Manifest.permission.RECORD_AUDIO)
                }
            }
        }
        LoadState(list) { items ->
            if (items.isEmpty()) Small("Belum ada rapat.")
            items.forEach { m ->
                val o = m.obj()
                Card {
                    Body(o.s("title"))
                    Small("${o.s("started_at").take(16).replace('T', ' ')} · ${((o.d("duration_s") ?: 0.0) / 60).toInt()} mnt · ${statusText(o.s("status"))}" +
                        if (o.b("confidential")) " · rahasia" else "")
                    if (o.s("ringkasan").isNotBlank()) Small(o.s("ringkasan").take(200), JarvisColors.Text)
                    Action("Buka") { onOpen(o.s("id")) }
                }
            }
        }
    }
}

private fun statusText(s: String) = when (s) {
    "recording" -> "merekam"; "queued" -> "antre"; "transcribing" -> "menyalin suara…"; "summarizing" -> "menyusun notulen…"
    "done" -> "selesai"; "failed" -> "gagal"; else -> s
}

@Composable
fun MeetingDetailScreen(vm: JarvisViewModel, id: String, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val m = rememberLoad(id) { vm.console.get("/api/v1/meetings/$id").obj() }
    var tab by remember { mutableStateOf("ringkasan") }
    var question by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf<String?>(null) }
    var filter by remember { mutableStateOf("") }
    ConsolePage("Rapat", onBack, m.reload) {
        LoadState(m) { o ->
            Body(o.s("title"), size = 17)
            Small("${statusText(o.s("status"))}${o.s("engine").takeIf { it.isNotBlank() }?.let { " · suara: $it" } ?: ""}${if (o.b("confidential")) " · rahasia" else ""}")
            if (o.s("status") != "done") {
                Small(if (o.s("status") == "failed") o.s("error") else "Sedang diproses; JARVIS akan mengabari bila notulen siap.", JarvisColors.Amber)
                return@LoadState
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("ringkasan" to "Ringkasan", "transkrip" to "Transkrip", "tanya" to "Tanya").forEach { (k, label) ->
                    Action(label, if (tab == k) JarvisColors.Cyan else JarvisColors.Muted) { tab = k }
                }
                if (o.s("document_id").isNotBlank()) Action("Dokumen", JarvisColors.Amber) {
                    scope.launch {
                        runCatching { vm.console.download("/api/v1/documents/${o.s("document_id")}", File(context.cacheDir, "docs/notulen-$id.docx")) }
                            .onSuccess { openFile(context, it, "view") }.onFailure { vm.notify(it.message ?: "Gagal") }
                    }
                }
            }
            val sum = o["summary"].obj()
            when (tab) {
                "ringkasan" -> {
                    Card { Label("Ringkasan"); Small(sum.s("ringkasan"), JarvisColors.Text) }
                    Card { Label("Keputusan"); sum["keputusan"].arr().forEach { Small("• " + (it as JsonPrimitive).content, JarvisColors.Text) } }
                    Card(border = JarvisColors.Amber) {
                        Label("Action items", JarvisColors.Amber)
                        sum["action_items"].arr().forEach { a ->
                            val x = a.obj()
                            Small("• ${x.s("siapa")}: ${x.s("apa")}" + (x.s("tenggat").takeIf { it.isNotBlank() }?.let { " (tenggat $it)" } ?: ""), JarvisColors.Text)
                        }
                    }
                    Card { Label("Pertanyaan terbuka"); sum["pertanyaan"].arr().forEach { Small("• " + (it as JsonPrimitive).content, JarvisColors.Text) } }
                }
                "transkrip" -> {
                    val names = o["speakers"].obj().values.map { (it as? JsonPrimitive)?.content.orEmpty() }.filter { it.isNotBlank() }.distinct()
                    if (names.size > 1 || names.any { it.startsWith("Pembicara") }) {
                        Card {
                            Label("Siapa pembicaranya?")
                            Small("Ganti \"Pembicara 2\" dengan nama aslinya; notulen dibuat ulang.")
                            names.filter { it != "Pemilik" }.forEach { old ->
                                var new by remember(old) { mutableStateOf("") }
                                OutlinedTextField(new, { new = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text(old) })
                                if (new.isNotBlank()) Action("Simpan nama untuk $old") {
                                    scope.launch {
                                        runCatching { vm.console.post("/api/v1/meetings/$id/speakers", buildJsonObject { put("from", old); put("to", new.trim()) }) }
                                            .onSuccess { vm.notify("Nama diganti; notulen diperbarui."); m.reload() }
                                            .onFailure { vm.notify(it.message ?: "Gagal") }
                                    }
                                }
                            }
                        }
                    }
                    OutlinedTextField(filter, { filter = it }, Modifier.fillMaxWidth(), label = { Text("Cari di transkrip") }, singleLine = true)
                    o["transcript"].arr().map { it.obj() }.filter { filter.isBlank() || it.s("text").contains(filter, ignoreCase = true) }.forEach { seg ->
                        Small("${mmss((seg.d("start") ?: 0.0).toLong())} ${seg.s("speaker")}: ${seg.s("text")}", JarvisColors.Text)
                    }
                }
                else -> {
                    OutlinedTextField(question, { question = it }, Modifier.fillMaxWidth(), label = { Text("Tanya tentang rapat ini") })
                    Action("Tanya", enabled = question.length > 2) {
                        answer = "Mencari…"
                        scope.launch {
                            answer = runCatching {
                                vm.console.post("/api/v1/meetings/$id/ask", buildJsonObject { put("question", question) }).obj().s("answer")
                            }.getOrElse { it.message }
                        }
                    }
                    answer?.let { Card(border = JarvisColors.Violet) { Small(it, JarvisColors.Text) } }
                }
            }
            Action("Hapus rapat ini", JarvisColors.Red) {
                scope.launch { runCatching { vm.console.delete("/api/v1/meetings/$id") }.onSuccess { onBack() } }
            }
            o.i("chunks")?.let { Small("$it potongan audio · dihapus otomatis setelah 30 hari") }
        }
    }
}
