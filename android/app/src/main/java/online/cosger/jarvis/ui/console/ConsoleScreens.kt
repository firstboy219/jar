package online.cosger.jarvis.ui.console

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
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

private fun time(iso: String) = iso.take(16).replace('T', ' ')

// ---------- Dasbor ----------

@Composable
fun DashboardScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val status = rememberLoad { vm.console.get("/api/v1/console/status").arr() }
    val llm = rememberLoad { vm.console.get("/api/v1/console/llm-usage").obj() }
    ConsolePage("Dasbor", onBack, { status.reload(); llm.reload() }) {
        LoadState(llm) { u ->
            val b = u["budget"].obj()
            Card {
                Label("Anggaran AI ${b.s("month")}")
                Body("$${"%.4f".format(b.d("spent_usd") ?: 0.0)} dari $${"%.0f".format(b.d("budget_usd") ?: 0.0)} (${b.d("pct") ?: 0}%)")
                Small(when ((b.i("level") ?: 0)) {
                    100 -> "Habis: model berbayar berhenti, model gratis/lokal tetap jalan."
                    95 -> "Hampir habis: semua kategori memakai rute termurah."
                    80 -> "80%: tugas latar belakang dipindah ke model gratis/lokal."
                    else -> "Aman."
                })
            }
        }
        LoadState(status) { list ->
            Card {
                Label("Status layanan")
                list.forEach { s ->
                    val o = s.obj()
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Body(if (o.b("ok")) "✅" else "❌")
                        Body(" ${o.s("name")}", size = 13)
                    }
                    Small(o.s("detail"))
                }
            }
        }
        LoadState(llm) { u ->
            Card {
                Label("Latensi suara (target < 1,5 dtk)")
                u["latency"].arr().take(8).forEach { m ->
                    val t = m.obj()["trace"].obj()
                    Small("${time(m.obj().s("created_at"))} · dengar ${t.i("stt_ms") ?: "-"} ms · kata pertama ${t.i("first_token_ms") ?: "-"} ms · " +
                        "bicara ${t.i("first_say_ms") ?: "-"} ms · ${t["route"].obj().s("model").ifEmpty { "-" }}")
                }
            }
            Card {
                Label("Pemakaian per model (30 hari)")
                u["rows"].arr().take(20).forEach { r ->
                    val o = r.obj()
                    Small("${o.s("day")} · ${o.s("category")} · ${o.s("model")} · ${o.i("calls")}x · $${"%.4f".format(o.d("cost_usd") ?: 0.0)}")
                }
            }
        }
    }
}

// ---------- Tugas & Persetujuan ----------

@Composable
fun TasksScreen(vm: JarvisViewModel, onBack: (() -> Unit)?) {
    val scope = rememberCoroutineScope()
    val gate = rememberOwnerGate()
    val approvals = rememberLoad { vm.console.get("/api/v1/console/approvals").arr() }
    val tasks = rememberLoad { vm.console.get("/api/v1/console/tasks").obj() }
    fun act(block: suspend () -> Unit) = scope.launch {
        runCatching { block() }.onFailure { vm.notify(it.message ?: "Gagal") }
        approvals.reload(); tasks.reload()
    }
    ConsolePage("Tugas & Persetujuan", onBack, { approvals.reload(); tasks.reload() }) {
        LoadState(approvals) { list ->
            val pending = list.map { it.obj() }.filter { it.s("status") == "awaiting_approval" }
            Label(if (pending.isEmpty()) "Tidak ada yang menunggu persetujuan" else "Menunggu persetujuan · ${pending.size}",
                if (pending.isEmpty()) JarvisColors.Muted else JarvisColors.Amber)
            pending.forEach { a ->
                val high = a.s("risk") == "high"
                Card(border = if (high) JarvisColors.Red else JarvisColors.Amber) {
                    Body("#${a.i("id")} ${a.s("title")}")
                    Small("${a.s("kind")} · risiko ${a.s("risk")} · oleh ${a.s("requested_by")} · ${time(a.s("created_at"))}")
                    a["detail"].obj().let { d ->
                        (d.s("command").ifEmpty { d.s("detail") }.ifEmpty { d.s("description") }).takeIf { it.isNotBlank() }?.let {
                            Small(it.take(400), JarvisColors.Text)
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Action("Setujui", JarvisColors.Green) {
                            val go = { act { vm.console.post("/api/v1/console/approvals/${a.i("id")}", buildJsonObject { put("approve", true) }) } }
                            if (high) gate("Setujui tindakan berisiko tinggi #${a.i("id")}") { go() } else go()
                        }
                        Action("Tolak", JarvisColors.Red) {
                            act { vm.console.post("/api/v1/console/approvals/${a.i("id")}", buildJsonObject { put("approve", false) }) }
                        }
                    }
                }
            }
        }
        LoadState(tasks) { t ->
            Label("Tugas")
            t["tasks"].arr().take(30).forEach { x ->
                val o = x.obj()
                Card {
                    Body("#${o.i("id")} ${o.s("title")}")
                    Small("${o.s("status")} · ${o.s("category")}${if (o.b("private")) " · privat" else ""} · ${time(o.s("created_at"))}")
                    if (o.s("result").isNotBlank()) Small(o.s("result").take(300), JarvisColors.Text)
                    if (o.s("error").isNotBlank()) Small(o.s("error").take(200), JarvisColors.Red)
                    if (o.s("status") in setOf("queued", "running")) Action("Batalkan", JarvisColors.Red) {
                        act { vm.console.post("/api/v1/console/tasks/${o.i("id")}/cancel") }
                    }
                }
            }
            Label("Laporan")
            t["reports"].arr().take(20).forEach { x ->
                val o = x.obj()
                Card {
                    Body(o.s("text"), size = 13)
                    Small("${o.s("status")} · disampaikan ${o.i("attempts")}x · ${time(o.s("created_at"))}")
                    if (o.s("status") in setOf("pending", "delivered", "unheard")) Action("Tandai sudah dengar") {
                        act { vm.console.post("/api/v1/console/reports/${o.i("id")}/ack") }
                    }
                }
            }
        }
    }
}


// ---------- Memori ----------

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MemoryScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var search by remember { mutableStateOf("") }
    var newText by remember { mutableStateOf("") }
    val memories = rememberLoad(search) {
        vm.console.get("/api/v1/console/memories" + if (search.isNotBlank()) "?q=" + Uri.encode(search) else "").arr()
    }
    ConsolePage("Memori", onBack, memories.reload) {
        OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), label = { Text("Cari memori") }, singleLine = true)
        Action("Cari") { search = query }
        OutlinedTextField(newText, { newText = it }, Modifier.fillMaxWidth(), label = { Text("Tambah fakta/preferensi") })
        Action("Simpan", enabled = newText.isNotBlank()) {
            scope.launch {
                runCatching { vm.console.post("/api/v1/console/memories", buildJsonObject { put("text", newText); put("category", "personal"); put("kind", "fact") }) }
                    .onSuccess { newText = ""; memories.reload() }.onFailure { vm.notify(it.message ?: "Gagal") }
            }
        }
        LoadState(memories) { list ->
            Small("${list.size} memori")
            list.forEach { x ->
                val o = x.obj()
                Card {
                    Body(o.s("text"), size = 13)
                    Small("${o.s("category")} · ${o.s("kind")} · ${o.s("source")}${o.d("score")?.let { " · skor %.2f".format(it) } ?: ""}" +
                        if (o.b("stale")) " · usang" else "")
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Action(if (o.b("stale")) "Masih berlaku" else "Tandai usang", JarvisColors.Muted) {
                            scope.launch {
                                runCatching { vm.console.patch("/api/v1/console/memories/${o.s("id")}", buildJsonObject { put("stale", !o.b("stale")) }) }
                                memories.reload()
                            }
                        }
                        Action("Hapus", JarvisColors.Red) {
                            scope.launch { runCatching { vm.console.delete("/api/v1/console/memories/${o.s("id")}") }; memories.reload() }
                        }
                    }
                }
            }
        }
    }
}

// ---------- Komposisi AI ----------

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun CompositionScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val gate = rememberOwnerGate()
    val comp = rememberLoad { vm.console.get("/api/v1/composition").obj() }
    var testResult by remember { mutableStateOf<String?>(null) }
    val edits = remember { mutableStateMapOf<String, String>() }
    fun save(body: JsonObject, reason: String) = gate(reason) {
        scope.launch {
            runCatching { vm.console.put("/api/v1/composition", body) }
                .onSuccess { vm.notify("Komposisi AI diperbarui."); comp.reload(); vm.refreshComposition() }
                .onFailure { vm.notify(it.message ?: "Gagal") }
        }
    }
    ConsolePage("Komposisi AI", onBack, comp.reload) {
        LoadState(comp) { c ->
            Card(border = JarvisColors.Cyan) {
                Label("Inti permanen")
                Body(c["core"].arr().joinToString(" · ") { (it as JsonPrimitive).content })
                Small("Hermes (otak kerja), Qdrant (memori) dan n8n (otomasi) selalu dipakai, apa pun model yang dipilih.")
            }
            Card {
                Label("Preset — sekarang: ${c.s("preset")}")
                c["presets"].arr().forEach { p ->
                    val o = p.obj()
                    Body(o.s("title"))
                    Small(o.s("summary"))
                    Action(if (c.s("preset") == o.s("name")) "Dipakai" else "Pakai ini", enabled = c.s("preset") != o.s("name")) {
                        save(buildJsonObject { put("preset", o.s("name")) }, "Ganti komposisi AI ke ${o.s("title")}")
                    }
                }
            }
            Card {
                Label("Mesin suara")
                val stt = c["stt"].obj()
                stt["options"].obj().forEach { (k, v) ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Action(if (stt.s("engine") == k) "● ${(v as JsonPrimitive).content}" else (v as JsonPrimitive).content,
                            if (stt.s("engine") == k) JarvisColors.Green else JarvisColors.Muted) {
                            save(buildJsonObject { put("changes", buildJsonObject { put("stt", k) }) }, "Ganti mesin suara")
                        }
                    }
                }
                Small("Bisu dulu (mute) agar pergantian mesin suara berlaku.")
            }
            Card {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Body("Mode Kuat", size = 15)
                    androidx.compose.foundation.layout.Spacer(Modifier.weight(1f))
                    Switch(c.b("strong_mode"), { on -> save(buildJsonObject { put("changes", buildJsonObject { put("strong_mode", on) }) }, "Mode Kuat") })
                }
                Small("Semua tugas memakai model kategori Analisis (lebih teliti, lebih mahal).")
            }
            val budget = c["budget"].obj()
            Small("Anggaran bulan ini: $${"%.4f".format(budget.d("spent_usd") ?: 0.0)} dari $${"%.0f".format(budget.d("budget_usd") ?: 0.0)}")
            c["categories"].arr().forEach { cat ->
                val o = cat.obj()
                val name = o.s("name")
                Card(border = if (o.b("locked")) JarvisColors.Green else JarvisColors.Border) {
                    Label(o.s("title"))
                    Small(o.s("description"))
                    val routes = o["routes"].arr().joinToString("  →  ") { r -> r.obj().let { "${it.s("provider")}/${it.s("model")}" } }
                    Body(routes + "  →  lokal", size = 12)
                    Small("Terpakai $${"%.4f".format(o.d("spent_usd") ?: 0.0)}" + (o.d("budget_usd")?.let { " dari $${"%.0f".format(it)}" } ?: ""))
                    if (!o.b("locked")) {
                        OutlinedTextField(edits[name] ?: "", { edits[name] = it }, Modifier.fillMaxWidth(), singleLine = true,
                            label = { Text("Model utama (mis. openrouter/anthropic/claude-haiku-5.5)") })
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Action("Simpan model", enabled = (edits[name] ?: "").contains("/")) {
                                val v = edits[name]!!.trim()
                                val provider = v.substringBefore("/")
                                val model = v.substringAfter("/")
                                val rest = o["routes"].arr()
                                save(buildJsonObject {
                                    put("changes", buildJsonObject {
                                        put("categories", buildJsonObject {
                                            put(name, buildJsonObject {
                                                put("routes", buildJsonArray {
                                                    add(buildJsonObject { put("provider", provider); put("model", model) })
                                                    rest.take(3).forEach { add(it) }
                                                })
                                            })
                                        })
                                    })
                                }, "Ganti model ${o.s("title")}")
                            }
                            Action("Tes") {
                                testResult = "Menguji ${o.s("title")}…"
                                scope.launch {
                                    testResult = runCatching {
                                        val r = vm.console.post("/api/v1/composition/test", buildJsonObject { put("category", name) }).obj()
                                        if (r.b("ok")) "${o.s("title")}: ${r["route"].obj().s("model")} menjawab dalam ${r.i("ms")} ms — “${r.s("text").take(120)}”"
                                        else "${o.s("title")} gagal: ${r.s("error").take(200)}"
                                    }.getOrElse { it.message }
                                }
                            }
                        }
                    } else Small("Selalu model lokal (data privat tidak pernah keluar server).", JarvisColors.Green)
                }
            }
        }
        testResult?.let { Card(border = JarvisColors.Violet) { Small(it, JarvisColors.Text) } }
    }
}

// ---------- Hermes Studio ----------

@Composable
fun StudioScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val studio = rememberLoad { vm.console.get("/api/v1/console/hermes-studio").obj() }
    ConsolePage("Hermes Studio", onBack, studio.reload) {
        LoadState(studio) { st ->
            Label("Jadwal yang dibuat Hermes")
            st["cron"].arr().ifEmpty { listOf(JsonPrimitive("-")) }.forEach { j ->
                if (j is JsonObject) Card {
                    Body(j.s("name"))
                    Small("${j.s("schedule")} · ${if (j.b("enabled")) "aktif" else "nonaktif"} · terakhir ${time(j.s("last_run"))} (${j.s("last_status")})")
                    Small(j.s("prompt").take(240), JarvisColors.Text)
                } else Small("Belum ada jadwal.")
            }
            Label("Skill buatan Hermes")
            st["skills"].arr().ifEmpty { listOf(JsonPrimitive("-")) }.forEach { k ->
                if (k is JsonObject) Card { Body(k.s("name")); Small(k.s("description")) } else Small("Belum ada skill buatan sendiri.")
            }
            Label("Papan kanban")
            st["kanban"].arr().ifEmpty { listOf(JsonPrimitive("-")) }.forEach { t ->
                if (t is JsonObject) Card { Body(t.s("title")); Small("${t.s("board")} · ${t.s("status")}") } else Small("Papan kosong.")
            }
            Label("Memori bawaan Hermes")
            Small((st.s("memory") + "\n" + st.s("user")).trim().ifEmpty { "-" }, JarvisColors.Text)
        }
    }
}

// ---------- Diri JARVIS ----------

@Composable
fun SelfScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val self = rememberLoad { vm.console.get("/api/v1/console/self").obj() }
    ConsolePage("Diri JARVIS", onBack, self.reload) {
        Action("Cek & perbaiki diri sekarang") {
            scope.launch { runCatching { vm.console.post("/api/v1/console/selfcheck") }.onSuccess { vm.notify("Cek diri dimulai; hasilnya disampaikan JARVIS.") } }
        }
        LoadState(self) { s ->
            Card { Label("Yang JARVIS tahu tentang dirinya"); Small(s.s("self"), JarvisColors.Text) }
            s["situation"].obj().takeIf { it.isNotEmpty() }?.let { sit ->
                Card { Label("Situasi yang dipahami"); Small("${sit.s("where")} · ${sit.s("doing")} · butuh ${sit.s("likely_need")}", JarvisColors.Text) }
            }
            Label("Perbaikan diri")
            s["improvements"].arr().take(30).forEach { x ->
                val o = x.obj()
                Card {
                    Body(o.s("summary"), size = 13)
                    Small("${o.s("kind")} · ${o.s("status")} · ${time(o.s("created_at"))}")
                    if (o.s("status") in setOf("applied", "proposed", "awaiting_approval")) Action("Batalkan", JarvisColors.Red) {
                        scope.launch { runCatching { vm.console.post("/api/v1/console/improvements/${o.i("id")}/revert") }; self.reload() }
                    }
                }
            }
        }
    }
}

// ---------- Perangkat ----------

@Composable
fun DevicesScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val gate = rememberOwnerGate()
    val devices = rememberLoad { vm.console.get("/api/v1/console/devices").arr() }
    var name by remember { mutableStateOf("") }
    var newToken by remember { mutableStateOf<String?>(null) }
    ConsolePage("Perangkat", onBack, devices.reload) {
        OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("Nama perangkat baru") }, singleLine = true)
        Action("Buat token", enabled = name.isNotBlank()) {
            gate("Buat token perangkat baru") {
                scope.launch {
                    runCatching { vm.console.post("/api/v1/console/devices", buildJsonObject { put("name", name); put("scope", "owner") }).obj() }
                        .onSuccess { newToken = it.s("token"); name = ""; devices.reload() }.onFailure { vm.notify(it.message ?: "Gagal") }
                }
            }
        }
        newToken?.let { Card(border = JarvisColors.Amber) { Label("Token (sekali tampil)"); Small(it, JarvisColors.Text) } }
        LoadState(devices) { list ->
            list.forEach { d ->
                val o = d.obj()
                Card {
                    Body(o.s("name"))
                    Small("${if (o.s("scope") == "owner") "pemilik" else "dasar"} · aktif ${time(o.s("last_seen_at")).ifEmpty { "belum" }}" +
                        if (o.s("revoked_at").isNotEmpty()) " · DICABUT" else "")
                    if (o.s("revoked_at").isEmpty()) Action("Cabut", JarvisColors.Red) {
                        gate("Cabut token ${o.s("name")}") {
                            scope.launch { runCatching { vm.console.delete("/api/v1/console/devices/${o.s("id")}") }; devices.reload() }
                        }
                    }
                }
            }
        }
    }
}

// ---------- Pembaruan aplikasi ----------

@Composable
fun AppUpdateScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val releases = rememberLoad { vm.console.get("/api/v1/console/releases").obj()["releases"].arr() }
    var busy by remember { mutableStateOf<String?>(null) }
    ConsolePage("Pembaruan aplikasi", onBack, releases.reload) {
        Small("Versi terpasang: ${online.cosger.jarvis.BuildConfig.VERSION_NAME}")
        LoadState(releases) { list ->
            list.reversed().forEach { r ->
                val o = r.obj()
                Card(border = if (o.s("version") == online.cosger.jarvis.BuildConfig.VERSION_NAME) JarvisColors.Green else JarvisColors.Border) {
                    Body("JARVIS ${o.s("version")}")
                    Small("${time(o.s("date"))} · ${"%.1f".format((o.d("size") ?: 0.0) / 1e6)} MB")
                    if (o.s("notes").isNotBlank()) Small(o.s("notes"), JarvisColors.Text)
                    Action(if (busy == o.s("file")) "Mengunduh…" else "Unduh & pasang", enabled = busy == null) {
                        if (Build.VERSION.SDK_INT >= 26 && !context.packageManager.canRequestPackageInstalls()) {
                            context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + context.packageName)))
                            vm.notify("Izinkan JARVIS memasang aplikasi, lalu tekan Unduh lagi.")
                            return@Action
                        }
                        busy = o.s("file")
                        scope.launch {
                            runCatching { vm.console.download("/api/v1/console/releases/${o.s("file")}", File(context.cacheDir, "docs/${o.s("file")}")) }
                                .onSuccess { openFile(context, it, "view") }.onFailure { vm.notify(it.message ?: "Gagal") }
                            busy = null
                        }
                    }
                }
            }
        }
    }
}

// ---------- Audit, Notifikasi, Dokumen ----------

@Composable
fun AuditScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val events = rememberLoad { vm.console.get("/api/v1/console/audit").arr() }
    ConsolePage("Audit", onBack, events.reload) {
        LoadState(events) { list ->
            list.forEach { e ->
                val o = e.obj()
                Small("${time(o.s("at"))} · ${o.s("actor")} · ${o.s("action")} ${o.s("target")}", JarvisColors.Text)
            }
        }
    }
}

@Composable
fun NotificationsScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val list = rememberLoad { vm.console.get("/api/v1/console/notifications").arr() }
    ConsolePage("Notifikasi HP", onBack, list.reload) {
        LoadState(list) { items ->
            items.forEach { n ->
                val o = n.obj()
                Card {
                    Body("${o.s("app")}: ${o.s("title")}", size = 13)
                    Small(o.s("text").take(200), JarvisColors.Text)
                    Small("${time(o.s("posted_at"))} · ${o.s("decision").ifEmpty { "-" }}${if (o.b("sensitive")) " · sensitif" else ""}")
                }
            }
        }
    }
}

@Composable
fun DocumentsScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val docs = rememberLoad { vm.console.get("/api/v1/console/documents").arr() }
    ConsolePage("Dokumen", onBack, docs.reload) {
        LoadState(docs) { list ->
            if (list.isEmpty()) Small("Belum ada dokumen. Minta JARVIS: \"buatkan laporan/notulen/tabel …\".")
            list.forEach { d ->
                val o = d.obj()
                Card {
                    Body(o.s("title"))
                    Small("${o.s("format").uppercase()} · ${"%.0f".format((o.d("size") ?: 0.0) / 1024)} KB · ${time(o.s("created_at"))}")
                    Action("Buka") {
                        scope.launch {
                            runCatching { vm.console.download(o.s("url"), File(context.cacheDir, "docs/${o.s("id")}.${o.s("format")}")) }
                                .onSuccess { openFile(context, it, "view") }.onFailure { vm.notify(it.message ?: "Gagal") }
                        }
                    }
                }
            }
        }
    }
}

// ---------- Pengaturan server (.env) ----------

@Composable
fun ServerSettingsScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val gate = rememberOwnerGate()
    val settings = rememberLoad { vm.console.get("/api/v1/console/settings").obj() }
    val values = remember { mutableStateMapOf<String, String>() }
    var result by remember { mutableStateOf<String?>(null) }
    ConsolePage("Pengaturan server", onBack, settings.reload) {
        Small("Kunci rahasia tidak pernah ditampilkan; isi hanya bila ingin mengganti. Layanan terkait di-restart otomatis.")
        LoadState(settings) { s ->
            s["fields"].arr().forEach { f ->
                val o = f.obj()
                val key = o.s("key")
                OutlinedTextField(values[key] ?: (if (o.b("secret")) "" else o.s("value")), { values[key] = it }, Modifier.fillMaxWidth(),
                    label = { Text(o.s("label") + if (o.b("secret")) (if (o.b("is_set")) " (terisi)" else " (kosong)") else "") },
                    singleLine = true, visualTransformation = if (o.b("secret")) PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
                    supportingText = { Text(o.s("help")) })
            }
            Action("Simpan & terapkan", enabled = values.isNotEmpty()) {
                gate("Simpan pengaturan server") {
                    scope.launch {
                        runCatching { vm.console.post("/api/v1/console/settings", buildJsonObject { values.forEach { (k, v) -> put(k, v) } }).obj() }
                            .onSuccess { r ->
                                val errors = r["errors"].arr().joinToString { (it as JsonPrimitive).content }
                                result = if (errors.isNotEmpty()) "Gagal: $errors" else "Disimpan: ${r["saved"].arr().joinToString { (it as JsonPrimitive).content }}"
                                if (errors.isEmpty()) values.clear()
                                settings.reload()
                            }.onFailure { result = it.message }
                    }
                }
            }
            result?.let { Card(border = JarvisColors.Cyan) { Small(it, JarvisColors.Text) } }
        }
    }
}

// ---------- kartu memori dari otak 3D ----------

@Composable
fun MemoryCardDialog(vm: JarvisViewModel, id: String, onDismiss: () -> Unit) {
    val card = rememberLoad(id) { vm.console.get("/api/v1/brain/$id").obj() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Memori") },
        text = { LoadState(card) { c -> Text("${c.s("text")}\n\n${c.s("category")} · ${c.s("kind")} · ${time(c.s("updated_at"))}") } },
        confirmButton = { TextButton(onDismiss) { Text("Tutup") } },
    )
}
