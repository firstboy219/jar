package online.cosger.jarvis.ui.console

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.launch
import online.cosger.jarvis.net.ServerEvent
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.theme.JarvisColors

/** ADR-077: JARVIS asks to operate an app on this phone. Approved only with the ADMIN PASSWORD (the owner's rule). */
@Composable
fun PhoneApprovalDialog(vm: JarvisViewModel, a: ServerEvent.PhoneApproval, onLater: () -> Unit) {
    var password by remember(a.id) { mutableStateOf("") }
    var error by remember(a.id) { mutableStateOf<String?>(null) }
    var busy by remember(a.id) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    AlertDialog(
        onDismissRequest = {},
        title = { Text("Izinkan JARVIS membuka ${a.label}?") },
        text = {
            Column {
                Text(a.goal, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                Text("JARVIS akan membuka ${a.label} di HP ini dan mengetuk/mengetik sendiri sampai tugas ini selesai. Ada spanduk " +
                    "\"Hentikan\" di layar selama ia bekerja. PIN, kata sandi, dan OTP tetap KAMU yang ketik. " +
                    "Berlaku ${a.expiresInS / 60} menit.", fontSize = 13.sp, color = JarvisColors.Muted)
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = password, onValueChange = { password = it; error = null }, singleLine = true,
                    label = { Text("Password admin") }, visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    isError = error != null, modifier = Modifier.fillMaxWidth(),
                )
                error?.let { Text(it, color = JarvisColors.Red, fontSize = 13.sp) }
            }
        },
        confirmButton = {
            TextButton(enabled = password.isNotBlank() && !busy, onClick = {
                busy = true
                scope.launch {
                    error = vm.approvePhoneRun(a.id, password)
                    if (error != null) password = ""
                    busy = false
                }
            }) { Text(if (busy) "Memeriksa…" else "Setujui") }
        },
        dismissButton = {
            Column {
                TextButton(enabled = !busy, onClick = { vm.rejectPhoneRun(a.id) }) { Text("Tolak") }
                TextButton(enabled = !busy, onClick = onLater) { Text("Nanti") }
            }
        },
    )
}
