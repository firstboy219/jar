package online.cosger.jarvis.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.IconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import online.cosger.jarvis.ui.ChatMessage
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.theme.JarvisColors

@Composable
fun ChatScreen(vm: JarvisViewModel) {
    val history by vm.history.collectAsStateWithLifecycle()
    val turn by vm.turn.collectAsStateWithLifecycle()
    var draft by remember { mutableStateOf("") }
    val list = rememberLazyListState()
    val busy = turn.phase in setOf(Phase.Thinking, Phase.Acting, Phase.Answering)
    LaunchedEffect(history.size, turn.answer.length) {
        val last = history.size + (if (busy) 1 else 0) - 1
        if (last >= 0) list.animateScrollToItem(last)
    }

    Column(Modifier.fillMaxSize().background(JarvisColors.Background).imePadding()) {
        LazyColumn(
            Modifier.weight(1f).fillMaxWidth(),
            state = list,
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (history.isEmpty()) {
                item { Text("Ketik pesan, atau 'bantuan' untuk perintah cepat.", color = JarvisColors.Muted) }
            }
            items(history) { Bubble(it) }
            if (busy) {
                item {
                    val live = turn.answer.ifBlank {
                        turn.tools.lastOrNull { it.running }?.let { "${it.title}…" } ?: "Sedang berpikir…"
                    }
                    Bubble(ChatMessage(fromUser = false, text = live, route = "…"))
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = draft, onValueChange = { draft = it }, modifier = Modifier.weight(1f),
                placeholder = { Text("Tulis pesan…") }, maxLines = 5,
                shape = RoundedCornerShape(16.dp),
            )
            Spacer(Modifier.width(8.dp))
            IconButton(onClick = { vm.sendText(draft); draft = "" }, enabled = draft.isNotBlank()) {
                Icon(Icons.AutoMirrored.Filled.Send, "Kirim", tint = JarvisColors.Cyan)
            }
        }
    }
}

@Composable
private fun Bubble(m: ChatMessage) {
    Box(Modifier.fillMaxWidth(), contentAlignment = if (m.fromUser) Alignment.CenterEnd else Alignment.CenterStart) {
        Column(
            Modifier.widthIn(max = 320.dp).clip(RoundedCornerShape(16.dp))
                .background(if (m.fromUser) JarvisColors.SurfaceHigh else JarvisColors.Surface)
                .padding(12.dp),
        ) {
            Text(m.text, color = JarvisColors.Text, fontSize = 15.sp, lineHeight = 21.sp)
            routeLabel(m.route)?.let {
                Text(it, color = JarvisColors.Muted, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
            }
        }
    }
}

private fun routeLabel(route: String?): String? = when (route) {
    "core" -> "perintah cepat · tanpa AI"
    "blocked" -> "ditahan · tidak dikirim ke cloud"
    "error" -> "gagal"
    else -> null
}
