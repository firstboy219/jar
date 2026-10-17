package online.cosger.jarvis.ui.screens

import androidx.compose.foundation.background
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
