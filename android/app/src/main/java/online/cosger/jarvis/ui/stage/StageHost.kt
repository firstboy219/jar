package online.cosger.jarvis.ui.stage

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import online.cosger.jarvis.net.ConsoleApi
import online.cosger.jarvis.ui.theme.JarvisColors

/** Everything a panel may need from the app, so panels stay simple composables. */
class StageActions(
    val console: ConsoleApi,
    val event: (String, Map<String, Int>) -> Unit,
    val notice: (String) -> Unit,
    val hearing: Boolean,
)

/**
 * The contextual front screen ("Panggung"): the panel JARVIS opened for the current conversation, or
 * the 3D brain when nothing is open. Priority (camera > panel > brain) is decided by the Talk screen.
 */
@Composable
fun StageHost(state: StageState, brain: BrainGraph?, thinking: Boolean, actions: StageActions, modifier: Modifier = Modifier,
              onNode: (String) -> Unit = {}) {
    val panel = state.panel
    if (panel == null) {
        BrainView(brain, state.pulses, thinking, modifier, onNode)
        return
    }
    Column(
        modifier.clip(RoundedCornerShape(18.dp)).background(JarvisColors.Surface)
            .border(1.dp, JarvisColors.Border, RoundedCornerShape(18.dp)),
    ) {
        Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 6.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(TITLES[panel.kind] ?: panel.kind.uppercase(), color = JarvisColors.Cyan, fontSize = 10.sp, letterSpacing = 2.sp)
            Spacer(Modifier.width(8.dp))
            Text(panel.caption, color = JarvisColors.Muted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f))
            Box(Modifier.size(36.dp).clickable { actions.event("closed", emptyMap()) }, contentAlignment = Alignment.Center) {
                Icon(Icons.Filled.Close, "Tutup", tint = JarvisColors.Muted, modifier = Modifier.size(18.dp))
            }
        }
        Box(Modifier.fillMaxSize().padding(start = 10.dp, end = 10.dp, bottom = 10.dp)) {
            when (panel.kind) {
                "music" -> MusicPanel(panel, actions)
                "video" -> VideoPanel(panel, actions)
                "map" -> MapPanel(panel, actions)
                "web" -> WebPanel(panel, actions)
                "doc" -> DocPanel(panel, actions)
                "draft" -> DraftPanel(panel, actions)
                "gallery" -> GalleryPanel(panel)
            }
        }
    }
}

private val TITLES = mapOf("music" to "MUSIK", "video" to "VIDEO", "map" to "PETA", "web" to "WEB", "doc" to "DOKUMEN",
                           "draft" to "DRAF BALASAN", "gallery" to "GAMBAR")

@Composable
internal fun PanelButton(text: String, primary: Boolean = false, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val color = if (primary) JarvisColors.Cyan else JarvisColors.Muted
    Text(
        text, color = if (primary) JarvisColors.Background else JarvisColors.Text, fontSize = 13.sp,
        fontWeight = if (primary) FontWeight.SemiBold else FontWeight.Normal,
        modifier = modifier.clip(RoundedCornerShape(20.dp))
            .background(if (primary) color else JarvisColors.SurfaceHigh)
            .border(1.dp, color.copy(alpha = 0.6f), RoundedCornerShape(20.dp))
            .clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 8.dp),
    )
}
