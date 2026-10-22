package online.cosger.jarvis.ui.stage

import android.annotation.SuppressLint
import android.net.Uri
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.annotation.OptIn
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.OkHttpClient
import online.cosger.jarvis.ui.theme.JarvisColors

/** ExoPlayer that sends the device token when fetching JARVIS' own media (/api/v1/media/...). */
@OptIn(UnstableApi::class)
@Composable
internal fun rememberPlayer(url: String, actions: StageActions, autoplay: Boolean = true): ExoPlayer {
    val context = LocalContext.current
    val player = remember(url) {
        val http = OkHttpDataSource.Factory(OkHttpClient()).setDefaultRequestProperties(
            if (url.startsWith("/")) actions.console.authHeader() else emptyMap())
        ExoPlayer.Builder(context).setMediaSourceFactory(DefaultMediaSourceFactory(http)).build().apply {
            setMediaItem(MediaItem.fromUri(actions.console.absolute(url)))
            prepare()
            playWhenReady = autoplay
        }
    }
    DisposableEffect(player) { onDispose { player.release() } }
    // Ducking: quieter while the owner speaks, so JARVIS (and the owner) can hear each other.
    LaunchedEffect(actions.hearing) { player.volume = if (actions.hearing) 0.2f else 1f }
    return player
}

@Composable
fun MusicPanel(panel: Panel, actions: StageActions) {
    val player = rememberPlayer(panel.str("url"), actions, panel.autoplay)
    var playing by remember { mutableStateOf(panel.autoplay) }
    var position by remember { mutableFloatStateOf(0f) }
    DisposableEffect(player) {
        val ended = object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                if (state == Player.STATE_ENDED) actions.event("ended", emptyMap())  // a playlist moves on
            }
        }
        player.addListener(ended)
        onDispose { player.removeListener(ended) }
    }
    LaunchedEffect(player) {
        while (true) {
            val d = player.duration
            if (d > 0) position = player.currentPosition.toFloat() / d
            playing = player.isPlaying
            delay(500)
        }
    }
    Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        val cover = panel.str("cover_url")
        if (cover.startsWith("https://")) {
            AsyncImage(cover, null, Modifier.size(120.dp).clip(RoundedCornerShape(16.dp)), contentScale = ContentScale.Crop)
            Spacer(Modifier.height(10.dp))
        }
        Text(panel.str("title"), color = JarvisColors.Text, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
        Text(panel.str("artist"), color = JarvisColors.Muted, fontSize = 13.sp)
        Slider(position, { v -> position = v; if (player.duration > 0) player.seekTo((v * player.duration).toLong()) },
            colors = SliderDefaults.colors(thumbColor = JarvisColors.Cyan, activeTrackColor = JarvisColors.Cyan))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PanelButton(if (playing) "Jeda" else "Putar", primary = true) {
                if (player.isPlaying) { player.pause(); actions.event("paused", emptyMap()) } else player.play()
            }
            PanelButton("Dari awal") { player.seekTo(0); player.play() }
        }
        PlaylistBar(panel, actions)
        Spacer(Modifier.height(8.dp))
        if (panel.str("license").isNotBlank()) {  // music from open sources; any other sound (audio) has none
            Text("Lisensi ${panel.str("license")} · ${Uri.parse(panel.str("source_url")).host ?: ""}", color = JarvisColors.Muted, fontSize = 10.sp)
        }
    }
}

private val YOUTUBE = Regex("^https://(?:www\\.|m\\.)?(?:youtube\\.com/(?:watch\\?(?:.*&)?v=|shorts/|embed/)|youtu\\.be/)([A-Za-z0-9_-]{11})")

/** The 11-character video id of a YouTube watch/short/embed/youtu.be URL, or null. Pure; unit-tested. */
fun youtubeId(url: String): String? = YOUTUBE.find(url)?.groupValues?.get(1)

/**
 * The official YouTube player, served by JARVIS' own server (`/embed/youtube/<id>`): YouTube refuses an embed whose
 * page has no real https origin/referrer (error 152/153 — what a page made inside the WebView has). Pure; unit-tested.
 */
fun youtubeEmbedUrl(origin: String, id: String, autoplay: Boolean): String =
    "${origin.trimEnd('/')}/embed/youtube/$id?autoplay=${if (autoplay) 1 else 0}"

/** What the embed page reports in its title: "playing", "paused", "ended", or "error:<code>". */
fun youtubeErrorText(title: String): String? = when (title.removePrefix("error:")) {
    title -> null
    "101", "150" -> "Pemilik video ini tidak mengizinkannya diputar di aplikasi lain."
    "100" -> "Video ini sudah dihapus atau dibuat privat."
    "api", "api-timeout" -> "Pemutar YouTube tidak termuat — cek koneksi, Muat ulang, atau Putar di YouTube."
    else -> "Video tidak bisa diputar di sini (kode ${title.removePrefix("error:")})."
}

/** YouTube only in its official, visible embedded player (its terms forbid background/extracted playback). */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun VideoPanel(panel: Panel, actions: StageActions) {
    val context = LocalContext.current
    val url = panel.str("url")
    val yt = youtubeId(url)
    var reload by remember(url) { mutableIntStateOf(0) }
    var problem by remember(url) { mutableStateOf<String?>(null) }
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center) {
        if (yt != null) {
            val origin = actions.console.absolute("/").trimEnd('/')
            key(url, reload) { // a new video must get a new player (the old one kept playing before)
                AndroidView({ ctx ->
                    WebView(ctx).apply {
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true // the YouTube player keeps its state there; without it: blank
                        settings.mediaPlaybackRequiresUserGesture = false
                        settings.allowFileAccess = false
                        settings.allowContentAccess = false
                        settings.cacheMode = android.webkit.WebSettings.LOAD_NO_CACHE // the player page changes with fixes
                        setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null) // video frames need the GPU, else black
                        webChromeClient = object : WebChromeClient() { // required for HTML5 video in a WebView
                            override fun onReceivedTitle(view: WebView, title: String?) {
                                val t = title.orEmpty()
                                if (t == "ended") actions.event("ended", emptyMap())  // a playlist moves on
                                if (t == "ready" || t == "playing") problem = null
                                youtubeErrorText(t)?.let { problem = it }
                            }
                        }
                        webViewClient = object : WebViewClient() {
                            // a tap on the YouTube logo/title leaves the player: open the YouTube app instead
                            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                                if (!request.isForMainFrame) return false
                                openYoutube(view.context, request.url.toString())
                                return true
                            }
                        }
                        setBackgroundColor(android.graphics.Color.BLACK)
                        loadUrl(youtubeEmbedUrl(origin, yt, panel.autoplay))
                    }
                }, Modifier.fillMaxWidth().aspectRatio(16f / 9f), // no clip: a clipped video surface can stay black
                    onRelease = { it.stopLoading(); it.destroy() })
            }
        } else {
            val player = rememberPlayer(url, actions, panel.autoplay)
            AndroidView({ ctx -> PlayerView(ctx).apply { this.player = player } },
                Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(12.dp)))
        }
        Spacer(Modifier.height(8.dp))
        Text(panel.str("title"), color = JarvisColors.Text, fontSize = 14.sp, maxLines = 2)
        problem?.let { Text(it, color = JarvisColors.Amber, fontSize = 12.sp) }
        PlaylistBar(panel, actions)
        if (yt != null) {
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PanelButton("Putar di YouTube", primary = true) { openYoutube(context, "https://www.youtube.com/watch?v=$yt") }
                PanelButton("Muat ulang") { reload++ }
            }
        }
    }
}

/** When a playlist is playing: where we are, what comes next, previous/next. */
@Composable
fun PlaylistBar(panel: Panel, actions: StageActions) {
    val pl = panel.payload["playlist"] as? JsonObject ?: return
    val index = pl.i("index") ?: 0
    val total = pl.i("total") ?: 0
    Spacer(Modifier.height(6.dp))
    Text("${pl.s("name")} · lagu ${index + 1} dari $total", color = JarvisColors.Cyan, fontSize = 11.sp)
    val next = pl["next"].arr().mapNotNull { (it as? JsonPrimitive)?.content }
    if (next.isNotEmpty()) Text("Berikutnya: " + next.take(2).joinToString(" · "), color = JarvisColors.Muted, fontSize = 11.sp, maxLines = 1)
    Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (index > 0) PanelButton("Sebelumnya") { actions.event("prev", emptyMap()) }
        if (index + 1 < total) PanelButton("Berikutnya") { actions.event("next", emptyMap()) }
    }
}

/** Opens the YouTube app (or the browser) — always works, even when the embedded player does not. */
fun openYoutube(context: android.content.Context, url: String) {
    runCatching {
        context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, Uri.parse(url))
            .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}

@Composable
fun GalleryPanel(panel: Panel) {
    val items = panel.list("items").filter { it.s("url").startsWith("https://") }
    LazyVerticalGrid(GridCells.Fixed(2), Modifier.fillMaxSize(), horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)) {
        items(items) { item ->
            AsyncImage(item.s("url"), item.s("title"), Modifier.fillMaxWidth().aspectRatio(1f).clip(RoundedCornerShape(10.dp)),
                contentScale = ContentScale.Crop)
        }
    }
}

