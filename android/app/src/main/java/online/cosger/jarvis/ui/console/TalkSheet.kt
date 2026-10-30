package online.cosger.jarvis.ui.console

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.screens.TalkScreen
import online.cosger.jarvis.ui.theme.JarvisColors

/** The conversation as a sheet over the app — everything the Bicara tab had (readiness, transcript, reports, workers, server, stage). */
@Composable
internal fun DeskTalkSheet(vm: JarvisViewModel, onClose: () -> Unit, onOpenServer: () -> Unit, onOpenBackground: () -> Unit, modifier: Modifier) {
    Column(modifier.fillMaxWidth().fillMaxHeight(0.74f).clip(RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp))
        .background(JarvisColors.Background.copy(alpha = 0.94f)).border(1.dp, JarvisColors.Border, RoundedCornerShape(topStart = 20.dp, topEnd = 20.dp))) {
        Row(Modifier.fillMaxWidth().clickable(onClick = onClose).padding(vertical = 6.dp), horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Filled.KeyboardArrowDown, "Tutup", tint = JarvisColors.Muted)
            Text("Tutup", color = JarvisColors.Muted, fontSize = 12.sp)
        }
        Box(Modifier.weight(1f)) { TalkScreen(vm, onOpenServer, onOpenBackground, compact = true) }
    }
}

/** Stage panels the app's own mini player shows (a video in the official YouTube player); the sheet must not play them a second time.
 *  Music is not here: it plays in the phone's media service and its panel only steers it. */
internal val APP_PLAYS = setOf("video")

/** Same scheme, host and port: the only pages the app's web views may show. */
internal fun sameOrigin(serverUrl: String, other: String): Boolean {
    val a = runCatching { java.net.URI(serverUrl.trim()) }.getOrNull() ?: return false
    val b = runCatching { java.net.URI(other.trim()) }.getOrNull() ?: return false
    fun port(u: java.net.URI) = if (u.port != -1) u.port else if (u.scheme == "https") 443 else 80
    return a.scheme != null && a.scheme == b.scheme && a.host != null && a.host.equals(b.host, ignoreCase = true) && port(a) == port(b)
}
