package online.cosger.jarvis.ui.console

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import online.cosger.jarvis.BuildConfig
import online.cosger.jarvis.JarvisApp
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.theme.JarvisColors

/** A screen of the app the phone should open (a tapped notification, a habit's offer): the host hands it to the page. */
object AppRoute {
    private val _pending = MutableStateFlow<String?>(null)
    val pending: StateFlow<String?> = _pending.asStateFlow()
    fun open(route: String?) { if (!route.isNullOrBlank() && route.startsWith("#/")) _pending.value = route }
    fun taken() { _pending.value = null }
}

/** What the page asks of the phone through JarvisHost; each returns at once and the work happens on the main thread. */
interface AppHostActions {
    fun talk()
    fun open(what: String)
}

/**
 * The app v2 (ADR-087): the server's /app/ page IS the phone's main screen — the same app as on the web, so every feature is reachable
 * from one front page. What only the phone can do stays native and is reached through the JarvisHost bridge: talking (the native
 * microphone, wake word and voice), the older settings screens, the desk, the phone's own location, and later the alarm and the camera.
 * The device token travels in the URL fragment, which is never sent to a server and which the page removes from the address at once.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun AppHostScreen(vm: JarvisViewModel, actions: AppHostActions) {
    val appSettings by vm.settings.collectAsState()
    val context = LocalContext.current
    val url = remember(appSettings.serverUrl, appSettings.deviceToken) { appUrl(appSettings.serverUrl, appSettings.deviceToken) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var pendingFiles by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    var pendingCamera by remember { mutableStateOf<PermissionRequest?>(null) }
    val pickFiles = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
        pendingFiles?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(r.resultCode, r.data))
        pendingFiles = null
    }
    val askMedia = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
        pendingCamera?.let { req -> if (granted.values.all { it }) req.grant(req.resources) else req.deny() }
        pendingCamera = null
    }
    val route by AppRoute.pending.collectAsState()
    LaunchedEffect(route, webView) {
        val r = route ?: return@LaunchedEffect
        val w = webView ?: return@LaunchedEffect
        w.evaluateJavascript("window.__jarvisGo && window.__jarvisGo(${org.json.JSONObject.quote(r)})", null)
        AppRoute.taken()
    }
    BackHandler {
        val w = webView
        if (w != null && w.canGoBack()) w.goBack() else (context as? android.app.Activity)?.moveTaskToBack(true)
    }
    DisposableEffect(Unit) { onDispose { webView?.destroy(); webView = null } }

    Box(Modifier.fillMaxSize().background(JarvisColors.Background)) {
        if (appSettings.serverUrl.isBlank() || appSettings.deviceToken.isBlank()) {
            Text("Belum masuk ke server. Buka pengaturan aplikasi.", color = JarvisColors.Muted, modifier = Modifier.align(Alignment.Center).padding(16.dp))
            return@Box
        }
        AndroidView(modifier = Modifier.fillMaxSize(), factory = { ctx ->
            WebView(ctx).apply {
                layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                setBackgroundColor(0xFF06090F.toInt())
                settings.apply {
                    javaScriptEnabled = true
                    domStorageEnabled = true
                    mediaPlaybackRequiresUserGesture = false
                    allowFileAccess = false
                    allowContentAccess = false
                    mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    cacheMode = WebSettings.LOAD_DEFAULT
                    userAgentString = "$userAgentString JarvisApp/${BuildConfig.VERSION_NAME}"
                }
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        if (sameOrigin(appSettings.serverUrl, request.url.toString())) return false
                        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, request.url)) }   // outside JARVIS: the browser
                        return true
                    }
                }
                webChromeClient = object : WebChromeClient() {
                    override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                        pendingFiles?.onReceiveValue(null)
                        pendingFiles = callback
                        val intent = params.createIntent().apply { putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) }
                        return runCatching { pickFiles.launch(intent); true }.getOrElse { pendingFiles = null; false }
                    }
                    override fun onPermissionRequest(request: PermissionRequest) {
                        // the page's own camera/microphone (a document photo, the web voice fallback): our origin only, after Android's consent
                        if (!sameOrigin(appSettings.serverUrl, request.origin.toString())) { request.deny(); return }
                        val need = request.resources.mapNotNull {
                            when (it) {
                                PermissionRequest.RESOURCE_VIDEO_CAPTURE -> Manifest.permission.CAMERA
                                PermissionRequest.RESOURCE_AUDIO_CAPTURE -> Manifest.permission.RECORD_AUDIO
                                else -> null
                            }
                        }
                        if (need.isEmpty()) { request.deny(); return }
                        if (need.all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }) request.grant(request.resources)
                        else { pendingCamera = request; askMedia.launch(need.toTypedArray()) }
                    }
                }
                addJavascriptInterface(JarvisBridge(this, actions), "JarvisHost")
                loadUrl(url)
                webView = this
            }
        })
    }
}

/** The page's window to the phone. Only strings and booleans cross; nothing else of the app is exposed. */
private class JarvisBridge(private val view: WebView, private val actions: AppHostActions) {
    private val spokenTokens = java.util.concurrent.ConcurrentHashMap.newKeySet<String>()
    @JavascriptInterface fun talk() { view.post { actions.talk() } }
    @JavascriptInterface fun open(what: String?) { val w = what.orEmpty().take(80); view.post { actions.open(w) } }
    @JavascriptInterface fun version(): String = BuildConfig.VERSION_NAME
    /** The alarm settings just saved on the page → the phone's own clock (ADR-087). */
    @JavascriptInterface fun syncAlarm(json: String?) { online.cosger.jarvis.alarm.AlarmScheduler.save(view.context, json.orEmpty().take(2000)) }
    @JavascriptInterface fun speak(text: String?) { val t = text.orEmpty().take(6000); view.post { (view.context.applicationContext as JarvisApp).engine.speakText(t) } }
    // the Qur'an's translation read by the phone's own voice; the page asks spoken(token) to move on to the next verse
    @JavascriptInterface fun speakLocal(text: String?, token: String?) {
        val t = text.orEmpty().take(6000); val k = token.orEmpty().take(40)
        view.post { (view.context.applicationContext as JarvisApp).engine.speakLocal(t) { if (k.isNotEmpty()) spokenTokens.add(k) } }
    }
    @JavascriptInterface fun spoken(token: String?): Boolean = spokenTokens.remove(token.orEmpty())
    @JavascriptInterface fun stopSpeaking() { view.post { (view.context.applicationContext as JarvisApp).engine.stopSpeaking() } }
    /** Fingerprint approval (ADR-087): the page keeps the admin password here after a successful approval it typed … */
    @JavascriptInterface fun rememberPassword(pw: String?) { (view.context.applicationContext as JarvisApp).engine.settingsStore.setAdminSecret(pw) }
    @JavascriptInterface fun hasBiometric(): Boolean = (view.context.applicationContext as JarvisApp).engine.settingsStore.adminSecret() != null
    /** … and gets it back only after a strong biometric (or the phone's own lock); "" when cancelled or the phone has no lock. */
    @JavascriptInterface fun biometric(reason: String?) {
        val secret = (view.context.applicationContext as JarvisApp).engine.settingsStore.adminSecret()
        view.post {
            online.cosger.jarvis.ui.console.unlockSecret(view.context, reason.orEmpty().take(120), secret) { pw ->
                view.evaluateJavascript("window.__jarvisBio && window.__jarvisBio(${org.json.JSONObject.quote(pw)})", null)
            }
        }
    }
    /** One of the approved apps opened on the owner's tap ("Buka Pluang", "Buka Gojek, lanjutkan"); false when it is not installed. */
    @JavascriptInterface fun openApp(name: String?): Boolean {
        val pkg = OPENABLE_APPS[name.orEmpty()] ?: return false
        val intent = view.context.packageManager.getLaunchIntentForPackage(pkg) ?: return false
        intent.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
        view.post { view.context.startActivity(intent) }
        return true
    }
    /** A site JARVIS will read from the web, signed into once by the owner himself (ADR-087 batch H); https only. */
    @JavascriptInterface fun openWeb(url: String?): Boolean {
        val u = url.orEmpty().take(500)
        if (online.cosger.jarvis.web.WebRules.host(u) == null) return false
        view.post { online.cosger.jarvis.web.WebLoginActivity.open(view.context, u) }
        return true
    }
    /** The owner's tap on "Buka di HP" on a web task that needs him: the session's own page is shown (ADR-087 batch I). */
    @JavascriptInterface fun showWeb(session: String?, reason: String?): Boolean {
        val id = session.orEmpty().take(40)
        if (online.cosger.jarvis.web.WebSessions.get(id) == null) return false
        view.post { online.cosger.jarvis.web.WebSessions.show(view.context, id, reason.orEmpty()) }
        return true
    }
    /** A YouTube video in a small window over other apps (picture-in-picture); the official player stays visible (ADR-087 phase J). */
    @JavascriptInterface fun pipVideo(id: String?, start: String?): Boolean {
        val v = id.orEmpty().take(11)
        if (!Regex("[A-Za-z0-9_-]{11}").matches(v)) return false
        view.post { online.cosger.jarvis.media.VideoPipActivity.open(view.context, v, start?.toIntOrNull() ?: 0) }
        return true
    }
    // ---- the app's mini player steers the phone's one music player (media/MusicPlayer: plays on every screen, lock-screen controls) ----
    @JavascriptInterface fun musicState(): String = online.cosger.jarvis.media.MusicPlayer.stateJson()
    @JavascriptInterface fun musicCmd(cmd: String?, arg: String?) {
        view.post {
            val m = online.cosger.jarvis.media.MusicPlayer
            when (cmd) {
                "play" -> m.resume(); "pause" -> m.pause(); "toggle" -> m.toggle(); "restart" -> m.restart()
                "seek" -> m.seekTo(arg?.toLongOrNull() ?: 0L); "stop" -> m.stop()
            }
        }
    }
    @JavascriptInterface fun musicPlay(json: String?) {
        val o = runCatching { kotlinx.serialization.json.Json.parseToJsonElement(json.orEmpty().take(4000)) as kotlinx.serialization.json.JsonObject }.getOrNull() ?: return
        fun s(k: String) = (o[k] as? kotlinx.serialization.json.JsonPrimitive)?.content.orEmpty()
        val url = s("url")
        if (!(url.startsWith("/api/v1/media/") || url.startsWith("https://"))) return
        view.post {
            val engine = (view.context.applicationContext as JarvisApp).engine
            online.cosger.jarvis.media.MusicPlayer.play(view.context, online.cosger.jarvis.media.MusicPlayer.Track(s("id").take(80), url, s("title").take(200), s("artist").take(200), s("cover")),
                engine.console.absolute("/"), engine.console.authHeader())
        }
    }
    @JavascriptInterface fun pickSpeaker(): Boolean = online.cosger.jarvis.media.MediaRoutes.pickSpeaker(view.context)
    @JavascriptInterface fun castTv(id: String?, start: String?): Boolean = online.cosger.jarvis.media.MediaRoutes.castTv(view.context, id.orEmpty().take(11), start?.toIntOrNull() ?: 0)
    /** The phone's last known place as {"lat","lon"} — for "tandai di sini" — or "" when it is not known or not allowed. */
    @JavascriptInterface fun location(): String {
        val app = view.context.applicationContext as JarvisApp
        val loc = app.location.cachedOrNull() ?: return ""
        return org.json.JSONObject().put("lat", loc.lat).put("lon", loc.lon).put("accuracy_m", loc.accuracyM ?: 0.0).toString()
    }
}

/** The apps the page may open (the same approved list the phone agent works in, ADR-087); nothing else can be launched from the page. */
internal val OPENABLE_APPS = mapOf(
    "gojek" to "com.gojek.app", "gopay" to "com.gojek.gopay", "pluang" to "com.EmasDigi", "kopikenangan" to "com.kopikenangan",
    "qpon" to "com.qpon.platform", "jobstreet" to "com.jobstreet.jobstreet",
)

internal fun appUrl(serverUrl: String, token: String): String =
    serverUrl.trim().trimEnd('/') + "/app/#t=" + Uri.encode(token) + "&app=1"
