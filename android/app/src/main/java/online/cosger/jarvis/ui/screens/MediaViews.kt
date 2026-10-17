package online.cosger.jarvis.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil3.compose.AsyncImage
import online.cosger.jarvis.net.MediaItem
import online.cosger.jarvis.ui.MediaShow
import online.cosger.jarvis.ui.theme.JarvisColors

/** One batch of pictures/videos JARVIS is showing, with its caption. Images open full screen; videos open in YouTube. */
@Composable
fun MediaCard(show: MediaShow, onDismiss: (Long) -> Unit) {
    val context = LocalContext.current
    var zoomed by remember { mutableStateOf<MediaItem?>(null) }
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(JarvisColors.Surface)
            .border(1.dp, JarvisColors.Violet.copy(alpha = 0.6f), RoundedCornerShape(14.dp)).padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("DIPERLIHATKAN", color = JarvisColors.Violet, fontSize = 10.sp, letterSpacing = 2.sp, modifier = Modifier.weight(1f))
            Icon(Icons.Filled.Close, "Tutup", Modifier.size(18.dp).clickable { onDismiss(show.seq) }, tint = JarvisColors.Muted)
        }
        if (show.caption.isNotBlank()) {
            Text(show.caption, color = JarvisColors.Text, fontSize = 14.sp, modifier = Modifier.padding(vertical = 6.dp))
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(show.items) { item ->
                Column(Modifier.width(200.dp).clickable {
                    if (item.isVideo || item.kind == "link") {
                        context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(item.url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    } else zoomed = item
                }) {
                    Box(Modifier.width(200.dp).height(130.dp).clip(RoundedCornerShape(10.dp)).background(JarvisColors.SurfaceHigh),
                        contentAlignment = Alignment.Center) {
                        item.preview?.let {
                            AsyncImage(model = it, contentDescription = item.title, contentScale = ContentScale.Crop,
                                modifier = Modifier.fillMaxSize())
                        }
                        if (item.isVideo) {
                            Box(Modifier.size(44.dp).clip(CircleShape).background(Color.Black.copy(alpha = 0.55f)), contentAlignment = Alignment.Center) {
                                Icon(Icons.Filled.PlayArrow, "Putar video", tint = Color.White)
                            }
                        }
                    }
                    if (item.title.isNotBlank()) {
                        Text(item.title, color = JarvisColors.Muted, fontSize = 11.sp, maxLines = 2, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(top = 4.dp))
                    }
                }
            }
        }
    }
    zoomed?.let { item ->
        Dialog(onDismissRequest = { zoomed = null }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Box(Modifier.fillMaxSize().background(Color.Black).clickable { zoomed = null }, contentAlignment = Alignment.Center) {
                AsyncImage(model = item.url, contentDescription = item.title, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth())
                if (item.source.isNotBlank()) {
                    Text(item.source, color = Color.White.copy(alpha = 0.7f), fontSize = 11.sp,
                        modifier = Modifier.align(Alignment.BottomCenter).padding(16.dp))
                }
            }
        }
    }
}
