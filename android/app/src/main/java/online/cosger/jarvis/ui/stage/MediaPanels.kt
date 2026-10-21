package online.cosger.jarvis.ui.stage

import android.annotation.SuppressLint
import android.net.Uri
import android.webkit.WebView
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
import androidx.compose.runtime.mutableFloatStateOf
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

private val YOUTUBE = Regex("^https://(www\\.|m\\.)?(youtube\\.com/watch\\?v=|youtu\\.be/)([A-Za-z0-9_-]{11})")

/** YouTube only in its official, visible embedded player (its terms forbid background/extracted playback). */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun VideoPanel(panel: Panel, actions: StageActions) {
    val url = panel.str("url")
    val yt = YOUTUBE.find(url)?.groupValues?.get(3)
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center) {
        if (yt != null) {
            AndroidView({ ctx ->
                WebView(ctx).apply {
                    settings.javaScriptEnabled = true
                    settings.mediaPlaybackRequiresUserGesture = false
                    settings.allowFileAccess = false
                    loadDataWithBaseURL("https://www.youtube.com",
                        "<html><body style='margin:0;background:#000'><iframe width='100%' height='100%' " +
                            "src='https://www.youtube.com/embed/$yt?autoplay=${if (panel.autoplay) 1 else 0}&playsinline=1' frameborder='0' " +
                            "allow='autoplay; encrypted-media; picture-in-picture' allowfullscreen></iframe></body></html>",
                        "text/html", "utf-8", null)
                }
            }, Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(12.dp)),
                onRelease = { it.destroy() })
        } else {
            val player = rememberPlayer(url, actions, panel.autoplay)
            AndroidView({ ctx -> PlayerView(ctx).apply { this.player = player } },
                Modifier.fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(12.dp)))
        }
        Spacer(Modifier.height(8.dp))
        Text(panel.str("title"), color = JarvisColors.Text, fontSize = 14.sp)
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

