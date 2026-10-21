package online.cosger.jarvis.ui.screens

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.core.app.NotificationManagerCompat
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import online.cosger.jarvis.BuildConfig
import online.cosger.jarvis.net.Connection
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.theme.JarvisColors

@Composable
fun SettingsScreen(vm: JarvisViewModel, onSaved: () -> Unit = {}) {
    val s by vm.settings.collectAsStateWithLifecycle()
    val connection by vm.connection.collectAsStateWithLifecycle()
    var server by remember(s.serverUrl) { mutableStateOf(s.serverUrl) }
    var token by remember { mutableStateOf("") }
    var speak by remember(s.speakReplies) { mutableStateOf(s.speakReplies) }
    val askLocation = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        // Without any location permission the toggle would silently do nothing — turn it off instead.
        if (granted.values.none { it }) vm.setShareLocation(false)
    }

    Column(
        Modifier.fillMaxSize().background(JarvisColors.Background).verticalScroll(rememberScrollState()).padding(16.dp),
    ) {
        Text("Pengaturan", color = JarvisColors.Text, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Text(
            when (connection) {
                Connection.Connected -> "● Terhubung"
                Connection.Connecting -> "● Menghubungkan…"
                Connection.Unauthorized -> "● Token ditolak server — buat token baru di web admin"
                Connection.Disconnected -> "● Terputus"
            },
            color = when (connection) {
                Connection.Connected -> JarvisColors.Green
                Connection.Unauthorized -> JarvisColors.Red
                else -> JarvisColors.Amber
            },
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(20.dp))

        OutlinedTextField(server, { server = it }, Modifier.fillMaxWidth(), label = { Text("Server") }, singleLine = true)
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            token, { token = it }, Modifier.fillMaxWidth(),
            label = { Text(if (s.isConfigured) "Token perangkat (tersimpan — isi untuk mengganti)" else "Token perangkat") },
            placeholder = { Text("jdv_…") }, singleLine = true, visualTransformation = PasswordVisualTransformation(),
        )
        Text(
            "Buat token di web admin → Perangkat. Token disimpan terenkripsi di HP ini.",
            color = JarvisColors.Muted, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp),
        )
        Spacer(Modifier.height(16.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Bacakan jawaban (suara)", color = JarvisColors.Text, modifier = Modifier.weight(1f))
            Switch(speak, { speak = it })
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Bagikan lokasi ke JARVIS", color = JarvisColors.Text)
                Text(
                    "Dikirim bersama setiap perintah (alamat dihitung di HP), untuk pertanyaan seperti " +
                        "\"cuaca di sini\" atau \"di mana saya\".",
                    color = JarvisColors.Muted, fontSize = 12.sp,
                )
            }
            Switch(s.shareLocation, { on ->
                vm.setShareLocation(on)
                if (on && vm.locationPermissionMissing()) askLocation.launch(LOCATION_PERMISSIONS)
            })
        }
        Spacer(Modifier.height(8.dp))
        NotificationSetting(s.readNotifications, vm::setReadNotifications)
        Spacer(Modifier.height(8.dp))
        val askCalendar = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
            vm.setUseCalendar(ok)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Pakai agenda kalender", color = JarvisColors.Text)
                Text("Judul, jam & tempat agenda 24 jam ke depan, supaya JARVIS bisa mengingatkan dan bersiap.",
                    color = JarvisColors.Muted, fontSize = 12.sp)
            }
            Switch(s.useCalendar, { on ->
                if (!on) vm.setUseCalendar(false) else askCalendar.launch(android.Manifest.permission.READ_CALENDAR)
            })
        }
        Spacer(Modifier.height(8.dp))
        val askMicForWake = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
            if (ok) vm.setWakeWord(true, s.wakeSensitive)
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Panggil dengan \"Hey Jarvis\"", color = JarvisColors.Text)
                Text("Saat mic mati, HP menunggu kata panggil (diproses di HP, tidak dikirim). Menambah pemakaian baterai.",
                    color = JarvisColors.Muted, fontSize = 12.sp)
            }
            Switch(s.wakeWord, { on ->
                if (!on) vm.setWakeWord(false, s.wakeSensitive) else askMicForWake.launch(android.Manifest.permission.RECORD_AUDIO)
            })
        }
        if (s.wakeWord) Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Lebih peka", color = JarvisColors.Text)
                Text("Kalau \"Hey Jarvis\" sering tidak terdengar (logat), tapi bisa lebih sering salah panggil.",
                    color = JarvisColors.Muted, fontSize = 12.sp)
            }
            Switch(s.wakeSensitive, { vm.setWakeWord(true, it) })
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Boleh memotong JARVIS", color = JarvisColors.Text)
                Text("Bicara saat JARVIS bicara langsung menghentikannya. Hanya aktif saat memakai headset (tanpa headset suara JARVIS terdengar mic).",
                    color = JarvisColors.Muted, fontSize = 12.sp)
            }
            Switch(s.bargeIn, { vm.setBargeIn(it) })
        }
        Spacer(Modifier.height(20.dp))
        Button(
            onClick = {
                vm.saveSettings(server, token.ifBlank { s.deviceToken }, speak)
                token = ""
                onSaved()
            },
            enabled = token.isNotBlank() || s.isConfigured,
            modifier = Modifier.fillMaxWidth(),
        ) { Text("Simpan & hubungkan") }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onClick = vm::newConversation, modifier = Modifier.fillMaxWidth()) { Text("Mulai percakapan baru") }
        Spacer(Modifier.height(24.dp))
        Text("Versi ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})", color = JarvisColors.Muted, fontSize = 12.sp)
    }
}


/** "Baca notifikasi": needs Android's special "Akses notifikasi" grant, which only the owner can give. */
@Composable
private fun NotificationSetting(enabled: Boolean, onChange: (Boolean) -> Unit) {
    val context = LocalContext.current
    var granted by remember { mutableStateOf(false) }
    LifecycleResumeEffect(Unit) { // re-check when coming back from Android settings
        granted = context.packageName in NotificationManagerCompat.getEnabledListenerPackages(context)
        onPauseOrDispose { }
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text("Baca notifikasi", color = JarvisColors.Text)
            Text(
                when {
                    !enabled -> "JARVIS memberi tahu notifikasi penting tanpa ditanya. Kode OTP tidak pernah dikirim."
                    !granted -> "Belum diizinkan — ketuk untuk membuka Akses notifikasi dan aktifkan JARVIS."
                    else -> "Aktif. Promo dilewati; jam tenang diatur di web admin."
                },
                color = if (enabled && !granted) JarvisColors.Amber else JarvisColors.Muted, fontSize = 12.sp,
                modifier = Modifier.clickable(enabled = enabled && !granted) {
                    context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                },
            )
        }
        Switch(enabled, { on ->
            onChange(on)
            if (on && !granted) context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        })
    }
}
