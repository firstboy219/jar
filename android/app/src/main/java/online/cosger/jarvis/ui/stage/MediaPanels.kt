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
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import coil3.compose.AsyncImage
import kotlinx.coroutines.delay
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
 * The official embedded YouTube player page. Loaded with JARVIS' own https origin (YouTube refuses embeds
 * without a valid origin/referrer — "error 153"), with its normal controls so the owner can always tap play.
 */
fun youtubeEmbedHtml(id: String, origin: String, autoplay: Boolean): String =
    "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>" +
        "<style>html,body{margin:0;height:100%;background:#000}iframe{border:0;width:100%;height:100%}</style></head><body>" +
        "<iframe src='https://www.youtube.com/embed/$id?autoplay=${if (autoplay) 1 else 0}&playsinline=1&controls=1&rel=0" +
        "&modestbranding=1&enablejsapi=1&origin=${Uri.encode(origin)}' " +
        "referrerpolicy='strict-origin-when-cross-origin' " +
        "allow='autoplay; encrypted-media; picture-in-picture; fullscreen' allowfullscreen></iframe></body></html>"

/** YouTube only in its official, visible embedded player (its terms forbid background/extracted playback). */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun VideoPanel(panel: Panel, actions: StageActions) {
    val context = LocalContext.current
    val url = panel.str("url")
    val yt = youtubeId(url)
    var reload by remember(url) { mutableIntStateOf(0) }
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center) {
        if (yt != null) {
            val origin = actions.console.absolute("/").trimEnd('/')
            key(reload) {
                AndroidView({ ctx ->
                    WebView(ctx).apply {
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true // the YouTube player keeps its state there; without it: blank
                        settings.mediaPlaybackRequiresUserGesture = false
                        settings.allowFileAccess = false
                        settings.allowContentAccess = false
                        webChromeClient = WebChromeClient() // required for HTML5 video in a WebView
                        webViewClient = object : WebViewClient() {
                            // a tap on the YouTube logo/title leaves the player: open the YouTube app instead
                            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                                if (!request.isForMainFrame) return false
                                openYoutube(view.context, request.url.toString())
                                return true
                            }
                        }
                        setBackgroundColor(android.graphics.Color.BLACK)
                        loadDataWithBaseURL("$origin/", youtubeEmbedHtml(yt, origin, panel.autoplay), "text/html", "utf-8", null)
                    }
                }, Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(12.dp)),
                    onRelease = { it.stopLoading(); it.destroy() })
            }
        } else {
            val player = rememberPlayer(url, actions, panel.autoplay)
            AndroidView({ ctx -> PlayerView(ctx).apply { this.player = player } },
                Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(12.dp)))
        }
        Spacer(Modifier.height(8.dp))
        Text(panel.str("title"), color = JarvisColors.Text, fontSize = 14.sp, maxLines = 2)
        if (yt != null) {
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PanelButton("Putar di YouTube", primary = true) { openYoutube(context, "https://www.youtube.com/watch?v=$yt") }
                PanelButton("Muat ulang") { reload++ }
            }
        }
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

