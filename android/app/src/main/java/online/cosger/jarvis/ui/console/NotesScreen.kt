package online.cosger.jarvis.ui.console

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.view.ViewGroup
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.theme.JarvisColors

/**
 * Catatan & Tugas (Blueprint v4 Fase 12, ADR-060): the owner's notes, to-dos and meeting minutes, in place of the old Chat tab (the
 * conversation lives on the desk now). Like the desk it is the server's web page (<server>/notes/) inside the app, so the phone and a
 * browser edit the same pages; the device token travels in the fragment, which is never sent to a server.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun NotesScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val appSettings by vm.settings.collectAsState()
    val context = LocalContext.current
    val url = remember(appSettings.serverUrl, appSettings.deviceToken) { notesUrl(appSettings.serverUrl, appSettings.deviceToken) }
    var webView by remember { mutableStateOf<WebView?>(null) }

    BackHandler {
        val w = webView
        if (w != null && w.canGoBack()) w.goBack() else onBack()
    }
    DisposableEffect(Unit) { onDispose { webView?.destroy(); webView = null } }

    Box(Modifier.fillMaxSize().background(JarvisColors.Background)) {
        if (appSettings.serverUrl.isBlank() || appSettings.deviceToken.isBlank()) {
            Text("Belum masuk ke server. Buka Lainnya → Pengaturan aplikasi.", color = JarvisColors.Muted, modifier = Modifier.padding(16.dp))
            return@Box
        }
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                WebView(ctx).apply {
                    layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                    setBackgroundColor(0xFF0B1020.toInt())
                    settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        allowFileAccess = false
                        allowContentAccess = false
                        mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    }
                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                            if (sameOrigin(appSettings.serverUrl, request.url.toString())) return false
                            // anything outside the JARVIS server opens in the browser, never inside this screen
                            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(request.url.toString()))) }
                            return true
                        }
                    }
                    loadUrl(url)
                    webView = this
                }
            },
        )
    }
}

internal fun notesUrl(serverUrl: String, token: String): String =
    serverUrl.trim().trimEnd('/') + "/notes/#t=" + Uri.encode(token) + "&app=1"
