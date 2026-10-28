package online.cosger.jarvis.ui.console

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedButton
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
import kotlinx.coroutines.launch
import online.cosger.jarvis.net.ServerEvent
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.theme.JarvisColors

/** ADR-079: a project asks the owner to pick one option (which train); the next stage starts when one is picked. No admin password: it is the owner's own project. */
@Composable
fun OwnerChoiceDialog(vm: JarvisViewModel, c: ServerEvent.OwnerChoice, onLater: () -> Unit) {
    var error by remember(c.id) { mutableStateOf<String?>(null) }
    var busy by remember(c.id) { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    AlertDialog(
        onDismissRequest = onLater,
        title = { Text(c.title.ifBlank { "Pilih dulu" }) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (c.prompt.isNotBlank()) Text(c.prompt, fontSize = 13.sp, color = JarvisColors.Muted)
                Spacer(Modifier.height(4.dp))
                c.options.forEach { o ->
                    OutlinedButton(
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth(),
                        onClick = {
                            busy = true
                            scope.launch {
                                error = vm.answerChoice(c.id, o.index)
                                busy = false
                            }
                        },
                    ) {
                        Column(Modifier.fillMaxWidth()) {
                            Text(o.label, fontWeight = FontWeight.SemiBold)
                            if (o.detail.isNotBlank()) Text(o.detail, fontSize = 12.sp, color = JarvisColors.Muted)
                            if (o.time.isNotBlank()) Text("🕒 ${o.time} WIB", fontSize = 12.sp, color = JarvisColors.Cyan)
                        }
                    }
                }
                error?.let { Text(it, color = JarvisColors.Red, fontSize = 13.sp) }
            }
        },
        confirmButton = { TextButton(enabled = !busy, onClick = onLater) { Text("Nanti") } },
    )
}
