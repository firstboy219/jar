package online.cosger.jarvis.ui.stage

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.view.WindowManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.FileProvider
import kotlinx.coroutines.launch
import online.cosger.jarvis.notify.Conversations
import online.cosger.jarvis.ui.theme.JarvisColors
import java.io.File

// ---------- web ----------

private val SECOND_LEVEL = setOf("co.id", "go.id", "ac.id", "or.id", "web.id", "my.id", "sch.id", "co.uk", "com.au", "com.sg", "com.my")

/** "news.detik.com" → "detik.com", "klikbca.co.id" stays. Navigation is locked to this. Pure; unit-tested. */
fun baseDomain(host: String): String {
    val parts = host.lowercase().trim('.').split('.')
    if (parts.size <= 2) return parts.joinToString(".")
    val last2 = parts.takeLast(2).joinToString(".")
    return if (last2 in SECOND_LEVEL) parts.takeLast(3).joinToString(".") else last2
}

fun allowedUrl(url: String, domain: String): Boolean {
    val uri = Uri.parse(url)
    val host = uri.host ?: return false
    return uri.scheme == "https" && baseDomain(host) == baseDomain(domain)
}

/**
 * Hardened browser panel. "read": an article/news source JARVIS is talking about. "login": a site the
 * OWNER must sign in to — the owner confirms the domain, types the credentials themselves (JARVIS never
 * sees them; the screen is excluded from screenshots/sharing), then taps "Selesai login".
 * https only, locked to the confirmed domain, no file access, no JavaScript bridge, Safe Browsing on.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebPanel(panel: Panel, actions: StageActions) {
    val context = LocalContext.current
    val url = panel.str("url")
    val domain = panel.str("domain").ifEmpty { Uri.parse(url).host.orEmpty() }
    val login = panel.str("mode") == "login"
    var confirmed by remember(panel.id) { mutableStateOf(!login) }
    if (!allowedUrl(url, domain)) {
        Text("Alamat tidak aman, tidak dibuka: $url", color = JarvisColors.Red, fontSize = 13.sp)
        return
    }
    if (!confirmed) {
        Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
            Text("Halaman masuk", color = JarvisColors.Amber, fontSize = 11.sp, letterSpacing = 2.sp)
            Text(domain, color = JarvisColors.Text, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(8.dp))
            Text("Pastikan alamat ini benar sebelum membuka. Kamu sendiri yang mengetik username & password — JARVIS " +
                "tidak melihatnya, dan layar ini tidak ikut terbagi.", color = JarvisColors.Muted, fontSize = 13.sp)
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PanelButton("Buka", primary = true) { confirmed = true }
                PanelButton("Batal") { actions.event("closed", emptyMap()) }
            }
        }
        return
    }
    if (login) {
        val window = (context as? Activity)?.window
        DisposableEffect(panel.id) {
            window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_SECURE) }
        }
    }
    var current by remember(panel.id) { mutableStateOf(url) }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(JarvisColors.SurfaceHigh).padding(8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("🔒 ${Uri.parse(current).host}", color = JarvisColors.Green, fontSize = 12.sp, modifier = Modifier.weight(1f))
            if (login) PanelButton("Selesai login", primary = true) { actions.event("login_done", emptyMap()) }
            else PanelButton("Buka di browser") {
                runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(current))) }
            }
        }
        Spacer(Modifier.height(6.dp))
        AndroidView({ ctx ->
            WebView(ctx).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.safeBrowsingEnabled = true
                settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        val next = request.url.toString()
                        if (allowedUrl(next, domain)) { current = next; return false }
                        actions.notice("Halaman mencoba pindah ke ${request.url.host} — diblokir demi keamanan.")
                        return true
                    }
                }
                loadUrl(url)
            }
        }, Modifier.fillMaxWidth().weight(1f).clip(RoundedCornerShape(10.dp)), onRelease = { it.destroy() })
    }
}

// ---------- document ----------

@Composable
fun DocPanel(panel: Panel, actions: StageActions) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    val format = panel.str("format")
    fun fetchThen(open: (File) -> Unit) {
        busy = true
        scope.launch {
            runCatching {
                val dir = File(context.cacheDir, "docs")
                actions.console.download(panel.str("url"), File(dir, "${panel.str("title").take(60).replace(Regex("[^A-Za-z0-9 _-]"), "")}.$format"))
            }.onSuccess(open).onFailure { actions.notice("Dokumen gagal diunduh: ${it.message}") }
            busy = false
        }
    }
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        Text(format.uppercase(), color = JarvisColors.Amber, fontSize = 12.sp, letterSpacing = 3.sp)
        Text(panel.str("title"), color = JarvisColors.Text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(14.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PanelButton(if (busy) "Mengunduh…" else "Buka", primary = true) { if (!busy) fetchThen { openFile(context, it, "view") } }
            PanelButton("Bagikan") { if (!busy) fetchThen { openFile(context, it, "share") } }
        }
    }
}

fun openFile(context: Context, file: File, how: String) {
    val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
    val type = when (file.extension) {
        "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        "pdf" -> "application/pdf"
        "apk" -> "application/vnd.android.package-archive"
        else -> "text/plain"
    }
    val intent = if (how == "share") Intent(Intent.ACTION_SEND).apply { this.type = type; putExtra(Intent.EXTRA_STREAM, uri) }
    else Intent(Intent.ACTION_VIEW).apply { setDataAndType(uri, type) }
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    runCatching { context.startActivity(Intent.createChooser(intent, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

// ---------- reply drafts ----------

/** wa.me link: digits only, Indonesian 08… → 628…. Pure; unit-tested. */
fun waLink(phone: String, text: String): String {
    var digits = phone.filter { it.isDigit() }
    if (digits.startsWith("0")) digits = "62" + digits.drop(1)
    return "https://wa.me/$digits?text=" + Uri.encode(text)
}

/**
 * Three reply drafts for the chat the owner is showing. JARVIS never sends: the owner copies, opens
 * WhatsApp/email with the text filled in, or taps "Kirim" which uses WhatsApp's own notification reply
 * — after a confirmation, so nothing leaves without the owner's tap.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun DraftPanel(panel: Panel, actions: StageActions) {
    val context = LocalContext.current
    val variants = panel.list("variants")
    val to = panel.str("to")
    val thread = remember(panel.id) { Conversations.find(to) }
    var confirmSend by remember { mutableStateOf<String?>(null) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (panel.str("summary").isNotBlank()) {
            Text("Membalas ${to.ifBlank { "pesan" }}: ${panel.str("summary")}", color = JarvisColors.Muted, fontSize = 12.sp)
        }
        variants.forEach { v ->
            val text = v.s("text")
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(JarvisColors.SurfaceHigh)
                .border(1.dp, JarvisColors.Border, RoundedCornerShape(12.dp)).padding(10.dp)) {
                Text(v.s("label").uppercase(), color = JarvisColors.Cyan, fontSize = 10.sp, letterSpacing = 2.sp)
                Text(text, color = JarvisColors.Text, fontSize = 14.sp, modifier = Modifier.padding(vertical = 6.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    PanelButton("Salin", primary = true) {
                        context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Draf JARVIS", text))
                        actions.notice("Draf disalin — tempel di aplikasinya.")
                        actions.event("draft_copied", emptyMap())
                    }
                    when (panel.str("channel")) {
                        "email" -> PanelButton("Buka email") {
                            val mail = Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:" + panel.str("email")))
                                .putExtra(Intent.EXTRA_SUBJECT, panel.str("subject")).putExtra(Intent.EXTRA_TEXT, text)
                            runCatching { context.startActivity(mail) }
                        }
                        else -> PanelButton("Buka WhatsApp") {
                            val phone = panel.str("wa_phone")
                            val intent = if (phone.length >= 8) Intent(Intent.ACTION_VIEW, Uri.parse(waLink(phone, text)))
                            else Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text).setPackage("com.whatsapp")
                            runCatching { context.startActivity(intent) }.onFailure {
                                runCatching { context.startActivity(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)) }
                            }
                        }
                    }
                    if (thread?.reply != null) PanelButton("Kirim ke ${thread.title}") { confirmSend = text }
                }
            }
        }
        Text("JARVIS tidak pernah mengirim pesan sendiri — kamu yang memilih dan mengirim.", color = JarvisColors.Muted, fontSize = 11.sp)
    }
    confirmSend?.let { text ->
        AlertDialog(
            onDismissRequest = { confirmSend = null },
            title = { Text("Kirim ke ${thread?.title}?") },
            text = { Text("\"$text\"\n\nDikirim lewat tombol Balas di notifikasi ${thread?.app}.") },
            confirmButton = {
                TextButton({
                    val ok = thread?.let { Conversations.reply(context, it, text) } == true
                    actions.notice(if (ok) "Terkirim ke ${thread?.title}." else "Gagal — notifikasinya sudah hilang. Pakai Salin atau Buka WhatsApp.")
                    if (ok) actions.event("draft_sent", emptyMap())
                    confirmSend = null
                }) { Text("Kirim") }
            },
            dismissButton = { TextButton({ confirmSend = null }) { Text("Batal") } },
        )
    }
}
