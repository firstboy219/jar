package online.cosger.jarvis.ui.stage

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.compose.AsyncImage
import coil3.network.NetworkHeaders
import coil3.network.httpHeaders
import coil3.request.ImageRequest
import online.cosger.jarvis.ui.theme.JarvisColors

/** One panel's body, by kind — used on its own and for each block of a board. */
@Composable
fun PanelBody(panel: Panel, actions: StageActions) {
    when (panel.kind) {
        "music", "audio" -> MusicPanel(panel, actions)
        "video" -> VideoPanel(panel, actions)
        "image" -> ImagePanel(panel, actions)
        "map" -> MapPanel(panel, actions)
        "web" -> WebPanel(panel, actions)
        "doc" -> DocPanel(panel, actions)
        "text" -> TextPanel(panel)
        "draft" -> DraftPanel(panel, actions)
        "gallery" -> GalleryPanel(panel)
        "board" -> BoardPanel(panel, actions)
    }
}

/** One picture, fitted; pinch to zoom, drag to look around. JARVIS' own files are fetched with the device token. */
@Composable
fun ImagePanel(panel: Panel, actions: StageActions) {
    val url = panel.str("url")
    var scale by remember(url) { mutableFloatStateOf(1f) }
    var offset by remember(url) { mutableStateOf(Offset.Zero) }
    val request = ImageRequest.Builder(LocalContext.current).data(actions.console.absolute(url)).apply {
        if (url.startsWith("/")) httpHeaders(NetworkHeaders.Builder().apply { actions.console.authHeader().forEach { (k, v) -> set(k, v) } }.build())
    }.build()
    Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.weight(1f).fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .pointerInput(url) {
                detectTransformGestures { _, pan, zoom, _ ->
                    scale = (scale * zoom).coerceIn(1f, 5f)
                    offset = if (scale == 1f) Offset.Zero else offset + pan
                }
            }) {
            AsyncImage(request, panel.str("title"), Modifier.fillMaxSize().graphicsLayer {
                scaleX = scale; scaleY = scale; translationX = offset.x; translationY = offset.y
            }, contentScale = ContentScale.Fit)
        }
        if (panel.str("title").isNotBlank()) {
            Text(panel.str("title"), color = JarvisColors.Text, fontSize = 13.sp, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

/** Notes, lists, a recipe, a summary — plain text, selectable for copying. */
@Composable
fun TextPanel(panel: Panel) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        if (panel.str("title").isNotBlank()) {
            Text(panel.str("title"), color = JarvisColors.Text, fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(bottom = 8.dp))
        }
        SelectionContainer { Text(panel.str("text"), color = JarvisColors.Ice, fontSize = 15.sp, lineHeight = 22.sp) }
    }
}

/** Several things at once — text, pictures, a video, a sound, a map, a web page — stacked and scrollable. */
@Composable
fun BoardPanel(panel: Panel, actions: StageActions) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (panel.str("title").isNotBlank()) {
            Text(panel.str("title"), color = JarvisColors.Text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
        }
        panel.blocks().forEach { block ->
            val box = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(JarvisColors.SurfaceHigh)
                .border(1.dp, JarvisColors.Border, RoundedCornerShape(12.dp)).padding(8.dp)
            when (val h = blockHeight(block.kind)) {
                null -> Column(box) {
                    if (block.str("title").isNotBlank()) Text(block.str("title"), color = JarvisColors.Text, fontSize = 14.sp,
                        fontWeight = FontWeight.SemiBold)
                    SelectionContainer { Text(block.str("text"), color = JarvisColors.Ice, fontSize = 14.sp, lineHeight = 20.sp) }
                }
                else -> Box(box.height(h)) { PanelBody(block, actions) }
            }
        }
    }
}

/** Fixed heights keep players, maps and web pages usable inside a scrolling board; text wraps. */
fun blockHeight(kind: String): Dp? = when (kind) {
    "text" -> null
    "doc" -> 140.dp
    "music", "audio" -> 230.dp
    "image", "video", "gallery" -> 240.dp
    "map" -> 280.dp
    else -> 380.dp // web
}
