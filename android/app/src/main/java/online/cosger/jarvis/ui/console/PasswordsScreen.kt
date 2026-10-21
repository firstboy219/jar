package online.cosger.jarvis.ui.console

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s
import online.cosger.jarvis.ui.theme.JarvisColors

/**
 * Password manager: logins for sites JARVIS opens, so the owner types them once. Encrypted on JARVIS'
 * server; opening this screen and revealing a password need the fingerprint. "Boleh dipakai JARVIS" lets
 * Hermes sign in for the owner — its browser fills the password without the AI ever seeing it.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PasswordsScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var unlocked by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { requireOwner(context, "Buka password manager") { unlocked = true } }
    if (!unlocked) {
        ConsolePage("Password", onBack) {
            Small("Password manager dilindungi sidik jari / PIN HP.")
            Action("Buka dengan sidik jari") { requireOwner(context, "Buka password manager") { unlocked = true } }
        }
        return
    }
    val entries = rememberLoad { vm.console.get("/api/v1/vault").arr() }
    val revealed = remember { mutableStateMapOf<String, String>() }
    var url by remember { mutableStateOf("") }
    var user by remember { mutableStateOf("") }
    var pass by remember { mutableStateOf("") }
    var label by remember { mutableStateOf("") }
    var agent by remember { mutableStateOf(false) }
    fun act(block: suspend () -> Unit) = scope.launch {
        runCatching { block() }.onFailure { vm.notify(it.message ?: "Gagal") }
        entries.reload()
    }
    ConsolePage("Password", onBack, entries.reload) {
        Card {
            Label("Tambah login")
            OutlinedTextField(url, { url = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Alamat situs (mis. ibank.klikbca.co.id)") })
            OutlinedTextField(user, { user = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Username / email") })
            OutlinedTextField(pass, { pass = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Password") },
                visualTransformation = PasswordVisualTransformation())
            OutlinedTextField(label, { label = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Nama (opsional)") })
            Row(verticalAlignment = Alignment.CenterVertically) {
                androidx.compose.foundation.layout.Column(Modifier.weight(1f)) {
                    Body("Boleh dipakai JARVIS", size = 13)
                    Small("Hermes boleh masuk ke situs ini untukmu; password diisi otomatis tanpa terlihat oleh AI.")
                }
                Switch(agent, { agent = it })
            }
            Action("Simpan", JarvisColors.Green, enabled = url.isNotBlank() && user.isNotBlank() && pass.isNotBlank()) {
                act {
                    vm.console.post("/api/v1/vault", buildJsonObject {
                        put("url", url); put("username", user); put("password", pass); put("label", label); put("allow_agent", agent)
                    })
                    url = ""; user = ""; pass = ""; label = ""; agent = false
                    vm.notify("Login disimpan (terenkripsi).")
                }
            }
        }
        LoadState(entries) { list ->
            if (list.isEmpty()) Small("Belum ada login. Login yang kamu ketik di panel web JARVIS juga bisa disimpan otomatis.")
            list.forEach { e ->
                val o = e.obj()
                val id = o.s("id")
                Card(border = if (o.b("allow_agent")) JarvisColors.Cyan else JarvisColors.Border) {
                    Body(o.s("label"))
                    Small("${o.s("origin")} · ${o.s("username")}")
                    revealed[id]?.let { Small("Password: $it", JarvisColors.Amber) }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Small("Boleh dipakai JARVIS", JarvisColors.Text)
                        Spacer(Modifier.weight(1f))
                        Switch(o.b("allow_agent"), { on ->
                            act { vm.console.patch("/api/v1/vault/$id", buildJsonObject { put("allow_agent", on) }) }
                        })
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Action(if (revealed.containsKey(id)) "Sembunyikan" else "Lihat") {
                            if (revealed.containsKey(id)) revealed.remove(id)
                            else requireOwner(context, "Lihat password ${o.s("label")}") {
                                act { revealed[id] = vm.console.post("/api/v1/vault/$id/reveal").obj().s("password") }
                            }
                        }
                        Action("Hapus", JarvisColors.Red) { act { vm.console.delete("/api/v1/vault/$id") } }
                    }
                }
            }
        }
    }
}
