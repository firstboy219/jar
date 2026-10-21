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

/** Fill the login form of the current page (no JavaScript bridge: values are injected, nothing comes back). */
fun fillScript(username: String, password: String): String {
    fun q(v: String) = kotlinx.serialization.json.JsonPrimitive(v).toString()
    return """(function(u,p){
      function set(el,v){var d=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');d.set.call(el,v);
        el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
      var pw=[].slice.call(document.querySelectorAll('input[type=password]')).filter(function(e){return e.offsetParent!==null;})[0];
      var all=[].slice.call(document.querySelectorAll('input')).filter(function(e){return e.offsetParent!==null&&/^(text|email|tel|)$/.test(e.type);});
      var user=null;for(var i=0;i<all.length;i++){if(pw&&(all[i].compareDocumentPosition(pw)&4))user=all[i];}
      if(!user&&!pw)return 'none';
      if(user&&u)set(user,u); if(pw)set(pw,p); return pw?'filled':'user-only';
    })(${q(username)},${q(password)});"""
}

/** Remember what the owner typed into a login form until the next page (window.name survives the redirect). */
const val CAPTURE_SCRIPT = """(function(){
  if(window.__jarvisCapture)return; window.__jarvisCapture=true;
  function grab(){var pw=document.querySelector('input[type=password]'); if(!pw||!pw.value)return;
    var all=[].slice.call(document.querySelectorAll('input')).filter(function(e){return /^(text|email|tel|)$/.test(e.type)&&e.value;});
    var u='';for(var i=0;i<all.length;i++){if(all[i].compareDocumentPosition(pw)&4)u=all[i].value;}
    window.name='__jarvis__'+JSON.stringify({u:u,p:pw.value,o:location.origin});}
  document.addEventListener('submit',grab,true);
  document.addEventListener('click',function(e){var t=e.target&&e.target.closest&&e.target.closest('button,input[type=submit]');if(t)grab();},true);
  document.addEventListener('keydown',function(e){if(e.key==='Enter')grab();},true);
})();"""

/** Read & clear a login captured on the previous page. */
const val TAKE_SCRIPT = """(function(){var n=window.name||'';if(n.indexOf('__jarvis__')!==0)return '';window.name='';return n.substring(10);})();"""

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
    val scope = rememberCoroutineScope()
    var webView by remember { mutableStateOf<WebView?>(null) }
    var saved by remember(panel.id) { mutableStateOf<List<kotlinx.serialization.json.JsonObject>>(emptyList()) }
    var offerSave by remember(panel.id) { mutableStateOf<kotlinx.serialization.json.JsonObject?>(null) }
    var autofillAsked by remember(panel.id) { mutableStateOf(false) }
    // Login mode: offer the saved login for this site (fingerprint first), fill it in.
    fun autofill(view: WebView) {
        if (!login || autofillAsked) return
        autofillAsked = true
        online.cosger.jarvis.ui.console.requireOwner(context, "Isi login tersimpan untuk $domain") {
            scope.launch {
                runCatching {
                    actions.console.post("/api/v1/vault/match", kotlinx.serialization.json.buildJsonObject {
                        put("url", kotlinx.serialization.json.JsonPrimitive(current)) }).arr().map { it.obj() }
                }.onSuccess { list ->
                    saved = list
                    list.firstOrNull()?.let { view.evaluateJavascript(fillScript(it.s("username"), it.s("password")), null) }
                    if (list.isNotEmpty()) actions.notice("Login ${list.first().s("username")} diisi dari password manager.")
                }
            }
        }
    }
    fun checkCaptured(view: WebView) {
        view.evaluateJavascript(TAKE_SCRIPT) { raw ->
            val text = runCatching { kotlinx.serialization.json.Json.parseToJsonElement(raw).let { (it as kotlinx.serialization.json.JsonPrimitive).content } }.getOrDefault("")
            if (text.isBlank()) return@evaluateJavascript
            val cred = runCatching { kotlinx.serialization.json.Json.parseToJsonElement(text).obj() }.getOrNull() ?: return@evaluateJavascript
            val known = saved.any { it.s("username") == cred.s("u") && it.s("password") == cred.s("p") }
            if (!known && cred.s("p").isNotBlank()) offerSave = cred
        }
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(JarvisColors.SurfaceHigh).padding(8.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("🔒 ${Uri.parse(current).host}", color = JarvisColors.Green, fontSize = 12.sp, modifier = Modifier.weight(1f))
            if (login) PanelButton("Selesai login", primary = true) {
                android.webkit.CookieManager.getInstance().flush() // stay signed in next time
                webView?.let(::checkCaptured)
                actions.event("login_done", emptyMap())
            }
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
                // Sessions persist across visits: next time the site usually still knows the owner.
                android.webkit.CookieManager.getInstance().setAcceptCookie(true)
                android.webkit.CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        val next = request.url.toString()
                        if (allowedUrl(next, domain)) { current = next; return false }
                        actions.notice("Halaman mencoba pindah ke ${request.url.host} — diblokir demi keamanan.")
                        return true
                    }

                    override fun onPageFinished(view: WebView, pageUrl: String) {
                        if (!login) return
                        checkCaptured(view)
                        view.evaluateJavascript(CAPTURE_SCRIPT, null)
                        autofill(view)
                    }
                }
                loadUrl(url)
                webView = this
            }
        }, Modifier.fillMaxWidth().weight(1f).clip(RoundedCornerShape(10.dp)), onRelease = { it.destroy() })
    }
    offerSave?.let { cred ->
        var allowAgent by remember { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = { offerSave = null },
            title = { Text("Simpan login untuk ${Uri.parse(cred.s("o")).host}?") },
            text = {
                Column {
                    Text("Username: ${cred.s("u").ifBlank { "(tidak terbaca)" }}\nTersimpan terenkripsi di server JARVIS; lain kali terisi otomatis.")
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("Boleh dipakai JARVIS", modifier = Modifier.weight(1f))
                        androidx.compose.material3.Switch(allowAgent, { allowAgent = it })
                    }
                }
            },
            confirmButton = {
                TextButton({
                    val c = cred
                    offerSave = null
                    scope.launch {
                        runCatching {
                            actions.console.post("/api/v1/vault", kotlinx.serialization.json.buildJsonObject {
                                put("url", kotlinx.serialization.json.JsonPrimitive(c.s("o")))
                                put("username", kotlinx.serialization.json.JsonPrimitive(c.s("u").ifBlank { "(akun)" }))
                                put("password", kotlinx.serialization.json.JsonPrimitive(c.s("p")))
                                put("allow_agent", kotlinx.serialization.json.JsonPrimitive(allowAgent))
                            })
                        }.onSuccess { actions.notice("Login disimpan di password manager.") }
                            .onFailure { actions.notice("Gagal menyimpan: ${it.message}") }
                    }
                }) { Text("Simpan") }
            },
            dismissButton = { TextButton({ offerSave = null }) { Text("Jangan") } },
        )
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
                val target = File(dir, "${panel.str("title").ifBlank { "dokumen" }.take(60).replace(Regex("[^A-Za-z0-9 _-]"), "")}.$format")
                val url = panel.str("url")
                if (url.startsWith("https://")) actions.console.downloadExternal(url, target) else actions.console.download(url, target)
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
