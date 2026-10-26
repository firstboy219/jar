package online.cosger.jarvis.ui.console

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.view.ViewGroup
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.theme.JarvisColors

/**
 * The 3D canvas (Blueprint v4 Fase 5, ADR-049/050): the web viewer at <server>/canvas/ inside the app. The same code runs on
 * the web and here; what the phone adds stays native and outside this screen (microphone and VAD, camera, notifications, location,
 * meetings keep working in their own tabs). The device token travels in the URL fragment, which is never sent to a server and
 * which the viewer removes from the address at once.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun GalaxyScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val appSettings by vm.settings.collectAsState()
    val context = LocalContext.current
    val url = remember(appSettings.serverUrl, appSettings.deviceToken) { galaxyUrl(appSettings.serverUrl, appSettings.deviceToken) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var pendingCamera by remember { mutableStateOf<PermissionRequest?>(null) }
    var title by remember { mutableStateOf("Galaksi 3D") }

    // the camera is only for the viewer's hand-gesture mode, only for our own origin, and only after the owner's Android consent
    val askCamera = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        pendingCamera?.let { req ->
            if (granted) req.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) else req.deny()
        }
        pendingCamera = null
    }

    BackHandler {
        val w = webView
        if (w != null && w.canGoBack()) w.goBack() else onBack()
    }
    DisposableEffect(Unit) { onDispose { webView?.destroy(); webView = null } }

    Column(Modifier.fillMaxSize().background(JarvisColors.Background)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(40.dp).clickable(onClick = onBack), contentAlignment = Alignment.Center) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, "Kembali", tint = JarvisColors.Text)
            }
            Text(title, color = JarvisColors.Text, fontSize = 18.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Box(Modifier.size(40.dp).clickable { webView?.reload() }, contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Refresh, "Muat ulang", tint = JarvisColors.Muted)
            }
        }
        if (appSettings.serverUrl.isBlank() || appSettings.deviceToken.isBlank()) {
            Text("Belum masuk ke server. Buka Lainnya → Pengaturan aplikasi.", color = JarvisColors.Muted, modifier = Modifier.padding(16.dp))
            return@Column
        }
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { ctx ->
                WebView(ctx).apply {
                    layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                    setBackgroundColor(0xFF02030A.toInt())
                    settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        mediaPlaybackRequiresUserGesture = false
                        allowFileAccess = false
                        allowContentAccess = false
                        mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        cacheMode = WebSettings.LOAD_DEFAULT
                    }
                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                            if (sameOrigin(appSettings.serverUrl, request.url.toString())) return false
                            // anything outside the JARVIS server opens in the browser, never inside this screen
                            runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(request.url.toString()))) }
                            return true
                        }
                    }
                    webChromeClient = object : WebChromeClient() {
                        override fun onReceivedTitle(view: WebView?, t: String?) { if (!t.isNullOrBlank()) title = t }
                        override fun onPermissionRequest(request: PermissionRequest) {
                            val ours = sameOrigin(appSettings.serverUrl, request.origin.toString())
                            val wantsCameraOnly = request.resources.all { it == PermissionRequest.RESOURCE_VIDEO_CAPTURE }
                            if (!ours || !wantsCameraOnly) { request.deny(); return }
                            if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                                request.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
                            } else {
                                pendingCamera = request
                                askCamera.launch(Manifest.permission.CAMERA)
                            }
                        }
                    }
                    loadUrl(url)
                    webView = this
                }
            },
        )
    }
}

/** ".../canvas/#t=<token>&app=1" — the viewer takes the token from the fragment and removes it (lib.js takeAppParams). */
internal fun galaxyUrl(serverUrl: String, token: String): String =
    serverUrl.trim().trimEnd('/') + "/canvas/#t=" + Uri.encode(token) + "&app=1"

/** Same scheme, host and port: the only pages this screen may show. */
internal fun sameOrigin(serverUrl: String, other: String): Boolean {
    val a = runCatching { java.net.URI(serverUrl.trim()) }.getOrNull() ?: return false
    val b = runCatching { java.net.URI(other.trim()) }.getOrNull() ?: return false
    fun port(u: java.net.URI) = if (u.port != -1) u.port else if (u.scheme == "https") 443 else 80
    return a.scheme != null && a.scheme == b.scheme && a.host != null && a.host.equals(b.host, ignoreCase = true) && port(a) == port(b)
}
