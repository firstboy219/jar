package online.cosger.jarvis.ui.console

import android.Manifest
import android.annotation.SuppressLint
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material.icons.filled.BatteryChargingFull
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.QueryStats
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.GraphicEq
import androidx.compose.material.icons.filled.Hub
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Public
import androidx.compose.material.icons.filled.QueueMusic
import androidx.compose.material.icons.filled.RecordVoiceOver
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SystemUpdate
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.i
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.theme.JarvisColors
import java.io.ByteArrayOutputStream

/** Every menu of the web admin, on the phone (plus phone-only ones), grouped like the web admin's tabs. */
enum class ConsoleRoute(val path: String, val title: String, val hint: String, val icon: ImageVector, val group: String) {
    Dashboard("dashboard", "Dasbor", "status layanan, anggaran, latensi suara, pemakaian", Icons.Filled.Dashboard, "Pantau"),
    Audit("audit", "Audit", "jejak semua tindakan", Icons.AutoMirrored.Filled.ReceiptLong, "Pantau"),
    Notifications("notifications", "Notifikasi", "yang diteruskan dari HP", Icons.Filled.Notifications, "Pantau"),
    Galaxy("galaxy", "Galaksi 3D", "ruang kerjamu sebagai galaksi: tugas, dokumen, memori — terbang, seret, cari", Icons.Filled.Public, "JARVIS"),
    Library("library", "Simpanan", "semua yang pernah dibuat & ditampilkan JARVIS: lagu, playlist, dokumen, gambar…", Icons.Filled.Inventory2, "JARVIS"),
    Memory("memory", "Memori", "cari, tambah, hapus ingatan JARVIS", Icons.Filled.Memory, "JARVIS"),
    Self("self", "Diri JARVIS", "pengetahuan diri, perbaikan, pengembangan diri, error", Icons.Filled.Psychology, "JARVIS"),
    Flow("flow", "Pengawas alur", "obrolan sesuai konteks? masalah & perbaikannya", Icons.Filled.Insights, "JARVIS"),
    Background("background", "Di balik layar", "apa yang JARVIS kerjakan sendiri, kapan, berapa lama", Icons.Filled.Visibility, "JARVIS"),
    Studio("studio", "Hermes Studio", "jadwal, skill, kanban, memori Hermes", Icons.Filled.Hub, "JARVIS"),
    Documents("documents", "Dokumen", "file buatan JARVIS", Icons.Filled.Description, "JARVIS"),
    Playlist("playlist", "Playlist", "lagu yang kamu kumpulkan lewat JARVIS", Icons.Filled.QueueMusic, "JARVIS"),
    Composition("composition", "Komposisi AI", "AI per kategori, anggaran, mesin suara, Mode Kuat", Icons.Filled.Tune, "AI & server"),
    JarvisVoice("jarvis-voice", "Suara JARVIS", "suara bicara (HP / ElevenLabs / Gemini…) + karakternya, dan model dengar", Icons.Filled.GraphicEq, "AI & server"),
    ModelStatsRoute("model-stats", "Statistik model", "model mana yang sering error, secepat apa, semahal apa", Icons.Filled.QueryStats, "AI & server"),
    Server("server", "Pengaturan server", "kunci API, anggaran, jam tenang, password admin", Icons.Filled.AccountTree, "AI & server"),
    Devices("devices", "Perangkat", "token perangkat", Icons.Filled.Devices, "AI & server"),
    Passwords("passwords", "Password", "login tersimpan untuk web & JARVIS", Icons.Filled.Key, "AI & server"),
    Update("update", "Pembaruan aplikasi", "daftar versi & pasang", Icons.Filled.SystemUpdate, "Aplikasi & HP"),
    Voice("voice", "Suaraku", "voiceprint supaya JARVIS mengenali suaramu", Icons.Filled.RecordVoiceOver, "Aplikasi & HP"),
    Phone("phone", "Setelan HP", "supaya JARVIS tidak dimatikan sistem", Icons.Filled.BatteryChargingFull, "Aplikasi & HP"),
    App("app", "Pengaturan aplikasi", "server, token, suara, lokasi", Icons.Filled.Settings, "Aplikasi & HP"),
}

@Composable
fun MoreScreen(onOpen: (ConsoleRoute) -> Unit) {
    ConsolePage("Lainnya", null) {
        Small("Tugas & persetujuan, rapat, dan chat ada di tab bawah. Versi terpasang: ${online.cosger.jarvis.BuildConfig.VERSION_NAME}")
        ConsoleRoute.entries.groupBy { it.group }.forEach { (group, routes) ->
            Label(group)
            routes.forEach { r ->
                Card(Modifier.clickable { onOpen(r) }) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(r.icon, null, tint = JarvisColors.Cyan, modifier = Modifier.size(22.dp))
                        Spacer(Modifier.width(12.dp))
                        androidx.compose.foundation.layout.Column {
                            Body(r.title, size = 15)
                            Small(r.hint)
                        }
                    }
                }
            }
        }
    }
}

// ---------- voiceprint ----------

private val SENTENCES = listOf(
    "Halo JARVIS, ini suaraku. Tolong kenali aku mulai sekarang.",
    "Hari ini aku mau cek jadwal rapat dan kirim laporan proyek.",
    "Tolong ingatkan aku membeli kopi dan mengisi bensin sore nanti.",
    "Berapa lama perjalanan dari rumah ke kantor kalau lewat tol?",
    "Buatkan ringkasan email penting yang masuk tadi pagi.",
    "Aku lebih suka jawaban singkat, jelas, dan langsung ke intinya.",
)

@SuppressLint("MissingPermission")
private suspend fun recordSeconds(seconds: Int): ByteArray = withContext(Dispatchers.IO) {
    val sr = 16_000
    val min = AudioRecord.getMinBufferSize(sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
    val rec = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, min * 4)
    val out = ByteArrayOutputStream()
    val buf = ByteArray(3_200)
    rec.startRecording()
    try {
        while (out.size() < seconds * sr * 2) {
            val n = rec.read(buf, 0, buf.size)
            if (n > 0) out.write(buf, 0, n)
        }
    } finally {
        rec.stop(); rec.release()
    }
    out.toByteArray()
}

@Composable
fun VoiceprintScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val status = rememberLoad { vm.console.get("/api/v1/voiceprint").obj() }
    var recording by remember { mutableStateOf(false) }
    var index by remember { mutableStateOf(0) }
    fun record() = scope.launch {
        vm.prepareMeeting() // the JARVIS mic must be off while recording a sample
        recording = true
        runCatching { vm.console.postBytes("/api/v1/voiceprint", recordSeconds(5)) }
            .onSuccess { index++; status.reload() }.onFailure { vm.notify(it.message ?: "Gagal") }
        recording = false
    }
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { if (it) record() }
    ConsolePage("Suaraku", onBack, status.reload) {
        Small("JARVIS membandingkan setiap ucapan dengan suaramu, supaya obrolan orang lain di dekat HP diabaikan, " +
            "dan di notulen rapat kamu tertulis sebagai \"Pemilik\". Disimpan hanya di server-mu.")
        LoadState(status) { s ->
            Card(border = if (s.b("enrolled")) JarvisColors.Green else JarvisColors.Amber) {
                Body(if (s.b("enrolled")) "Voiceprint aktif (${s.i("samples")} kalimat)" else "Belum aktif — ${s.i("samples") ?: 0} dari 5 kalimat")
            }
        }
        Card {
            Label("Baca kalimat ini dengan suara biasa (5 detik)")
            Body(SENTENCES[index % SENTENCES.size], size = 16)
            Action(if (recording) "Merekam… bicara sekarang" else "Rekam", JarvisColors.Red, enabled = !recording) {
                if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) record()
                else askMic.launch(Manifest.permission.RECORD_AUDIO)
            }
        }
        Action("Hapus voiceprint", JarvisColors.Red) {
            scope.launch { runCatching { vm.console.delete("/api/v1/voiceprint") }; status.reload(); index = 0 }
        }
    }
}

// ---------- Infinix / XOS ----------

/**
 * Transsion XOS (Infinix/Tecno/itel) kills background apps aggressively; without these settings JARVIS
 * stops hearing and stops delivering reports when the screen is off.
 */
@Composable
fun PhoneSetupScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val pm = context.getSystemService(PowerManager::class.java)
    fun open(vararg intents: Intent) {
        for (i in intents) if (runCatching { context.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess) return
    }
    ConsolePage("Setelan HP", onBack) {
        Small("Ponsel ${Build.MANUFACTURER} ${Build.MODEL} · Android ${Build.VERSION.RELEASE}")
        Card(border = if (pm.isIgnoringBatteryOptimizations(context.packageName)) JarvisColors.Green else JarvisColors.Amber) {
            Label("1. Baterai: tanpa batasan")
            Small("Supaya mic & laporan tetap jalan saat layar mati.", JarvisColors.Text)
            Action(if (pm.isIgnoringBatteryOptimizations(context.packageName)) "Sudah diizinkan" else "Izinkan") {
                @SuppressLint("BatteryLife")
                val i = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + context.packageName))
                open(i, Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            }
        }
        Card {
            Label("2. Mulai otomatis (Auto-start)")
            Small("Infinix: Phone Master / XManager → Auto-start → aktifkan JARVIS.", JarvisColors.Text)
            Action("Buka") {
                open(Intent().setComponent(ComponentName("com.transsion.phonemaster", "com.cyin.himgr.autostart.AutoStartActivity")),
                    Intent().setComponent(ComponentName("com.transsion.phonemanager", "com.itel.autobootmanager.activity.AutoBootMgrActivity")),
                    Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + context.packageName)))
            }
        }
        Card {
            Label("3. Pembersih Phone Master")
            Small("Matikan pembersihan otomatis untuk JARVIS (Phone Master → Boost/Cleaner → daftar putih).", JarvisColors.Text)
            Action("Buka pengaturan aplikasi") {
                open(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + context.packageName)))
            }
        }
        Card {
            Label("4. Akses notifikasi")
            Small("Untuk membaca notifikasi dan membantu membalas WhatsApp.", JarvisColors.Text)
            Action("Buka") { open(Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS")) }
        }
        Text("Tanpa langkah ini, XOS bisa mematikan JARVIS diam-diam setelah layar mati.", color = JarvisColors.Muted,
            fontSize = 12.sp, modifier = Modifier.fillMaxWidth().padding(top = 4.dp))
    }
}
