package online.cosger.jarvis.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.InsertDriveFile
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.compose.AsyncImage
import online.cosger.jarvis.attach.AttachmentPrep
import online.cosger.jarvis.attach.PendingAttachment
import online.cosger.jarvis.ui.ChatMessage
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.theme.JarvisColors
import java.io.File

private val FILE_TYPES = arrayOf(
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/*", "application/json", "image/*",
)

@Composable
fun ChatScreen(vm: JarvisViewModel) {
    val context = LocalContext.current
    val history by vm.history.collectAsStateWithLifecycle()
    val turn by vm.turn.collectAsStateWithLifecycle()
    var draft by remember { mutableStateOf("") }
    var pending by remember { mutableStateOf(listOf<PendingAttachment>()) }
    var menu by remember { mutableStateOf(false) }
    var cameraUri by remember { mutableStateOf<Uri?>(null) }
    val list = rememberLazyListState()
    val busy = turn.phase in setOf(Phase.Thinking, Phase.Acting, Phase.Answering)
    fun add(uris: List<Uri>) {
        val room = AttachmentPrep.MAX_FILES - pending.size
        if (uris.size > room) vm.notify("Maksimal ${AttachmentPrep.MAX_FILES} lampiran sekali kirim.")
        pending = pending + uris.take(room.coerceAtLeast(0)).map { vm.describeAttachment(it) }
    }
    val pickPhotos = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(AttachmentPrep.MAX_FILES)) { add(it) }
    val pickFiles = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { add(it) }
    val takePhoto = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        cameraUri?.takeIf { ok }?.let { add(listOf(it)) }
    }
    fun launchCamera() {
        val file = File(context.cacheDir, "docs/kamera-${System.currentTimeMillis()}.jpg").apply { parentFile?.mkdirs() }
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
        cameraUri = uri
        takePhoto.launch(uri)
    }
    val askCamera = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { if (it) launchCamera() }
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
                item { Text("Ketik pesan, atau lampirkan foto/dokumen dengan tombol klip. 'bantuan' untuk perintah cepat.", color = JarvisColors.Muted) }
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
        if (pending.isNotEmpty()) {
            Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                pending.forEach { p -> AttachmentChip(p) { pending = pending - p } }
            }
        }
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Box {
                IconButton(onClick = { menu = true }) { Icon(Icons.Filled.AttachFile, "Lampirkan", tint = JarvisColors.Cyan) }
                DropdownMenu(menu, { menu = false }) {
                    DropdownMenuItem(text = { Text("Foto dari galeri") }, leadingIcon = { Icon(Icons.Filled.Image, null) }, onClick = {
                        menu = false
                        pickPhotos.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                    })
                    DropdownMenuItem(text = { Text("Ambil foto") }, leadingIcon = { Icon(Icons.Filled.PhotoCamera, null) }, onClick = {
                        menu = false
                        if (context.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) launchCamera()
                        else askCamera.launch(Manifest.permission.CAMERA)
                    })
                    DropdownMenuItem(text = { Text("Dokumen / file") }, leadingIcon = { Icon(Icons.Filled.InsertDriveFile, null) }, onClick = {
                        menu = false
                        pickFiles.launch(FILE_TYPES)
                    })
                }
            }
            OutlinedTextField(
                value = draft, onValueChange = { draft = it }, modifier = Modifier.weight(1f),
                placeholder = { Text(if (pending.isEmpty()) "Tulis pesan…" else "Mau diapakan lampirannya?") }, maxLines = 5,
                shape = RoundedCornerShape(16.dp),
            )
            Spacer(Modifier.width(8.dp))
            IconButton(onClick = { vm.sendMessage(draft, pending); draft = ""; pending = emptyList() },
                enabled = draft.isNotBlank() || pending.isNotEmpty()) {
                Icon(Icons.AutoMirrored.Filled.Send, "Kirim", tint = JarvisColors.Cyan)
            }
        }
    }
}

/** A picked file/picture waiting to be sent: thumbnail or icon, its name, and a way to remove it. */
@Composable
private fun AttachmentChip(p: PendingAttachment, onRemove: () -> Unit) {
    Row(
        Modifier.clip(RoundedCornerShape(12.dp)).background(JarvisColors.SurfaceHigh).padding(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (p.isImage) AsyncImage(p.uri, p.name, Modifier.size(40.dp).clip(RoundedCornerShape(8.dp)), contentScale = ContentScale.Crop)
        else Icon(Icons.Filled.InsertDriveFile, null, Modifier.size(32.dp), tint = JarvisColors.Muted)
        Spacer(Modifier.width(8.dp))
        Text(p.name, color = JarvisColors.Text, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.widthIn(max = 150.dp))
        Icon(Icons.Filled.Close, "Hapus lampiran", Modifier.padding(start = 6.dp).size(18.dp).clickable(onClick = onRemove),
            tint = JarvisColors.Muted)
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
    "report" -> "laporan hasil kerja"
    "announce" -> "dari notifikasi"
    "proactive" -> "JARVIS menyapa duluan"
    "blocked" -> "ditahan · tidak dikirim ke cloud"
    "error" -> "gagal"
    else -> null
}
