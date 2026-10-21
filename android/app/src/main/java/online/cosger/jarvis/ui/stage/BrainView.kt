package online.cosger.jarvis.ui.stage

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import online.cosger.jarvis.ui.theme.JarvisColors
import kotlin.math.cos
import kotlin.math.sin

/** A node after rotation + perspective, for drawing and hit-testing. Pure math, unit-tested. */
data class Projected(val index: Int, val x: Float, val y: Float, val depth: Float, val scale: Float)

fun project(nodes: List<BrainGraph.Node>, yaw: Float, pitch: Float, width: Float, height: Float): List<Projected> {
    val cx = width / 2f
    val cy = height / 2f
    val r = minOf(width, height) * 0.42f
    val cyw = cos(yaw); val syw = sin(yaw); val cp = cos(pitch); val sp = sin(pitch)
    return nodes.mapIndexed { i, n ->
        // rotate around the vertical axis, then tilt
        val x1 = n.x * cyw + n.z * syw
        val z1 = -n.x * syw + n.z * cyw
        val y1 = n.y * cp - z1 * sp
        val z2 = n.y * sp + z1 * cp
        val scale = 2.6f / (2.6f + z2)
        Projected(i, cx + x1 * r * scale, cy + y1 * r * scale, z2, scale)
    }.sortedByDescending { it.depth } // far first, near last
}

/**
 * JARVIS' "brain" (Iron Man style): every memory is a glowing node placed by meaning, linked to its
 * nearest neighbours; it turns slowly, can be dragged, and nodes flash when an agent reads (cyan) or
 * writes (amber) them. ~30 fps and ≤ 150 nodes keep it light on a mid-range phone.
 */
@Composable
fun BrainView(
    graph: BrainGraph?,
    pulses: Map<String, StageState.Pulse>,
    thinking: Boolean,
    modifier: Modifier = Modifier,
    onNode: (String) -> Unit = {},
) {
    var yaw by remember { mutableFloatStateOf(0f) }
    var pitch by remember { mutableFloatStateOf(-0.25f) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(thinking) {
        while (true) {
            delay(33)
            yaw += if (thinking) 0.018f else 0.006f
            now = System.currentTimeMillis()
        }
    }
    val nodes = graph?.nodes.orEmpty()
    Box(modifier) {
        Canvas(
            Modifier.matchParentSize()
                .pointerInput(graph) {
                    detectDragGestures { _, drag ->
                        yaw += drag.x / 300f
                        pitch = (pitch + drag.y / 300f).coerceIn(-1.2f, 1.2f)
                    }
                }
                .pointerInput(graph) {
                    detectTapGestures { tap ->
                        val hit = project(nodes, yaw, pitch, size.width.toFloat(), size.height.toFloat())
                            .minByOrNull { (it.x - tap.x) * (it.x - tap.x) + (it.y - tap.y) * (it.y - tap.y) }
                        if (hit != null && (hit.x - tap.x) * (hit.x - tap.x) + (hit.y - tap.y) * (hit.y - tap.y) < 48f * 48f) {
                            onNode(nodes[hit.index].id)
                        }
                    }
                },
        ) {
            val glow = if (thinking) JarvisColors.Violet else JarvisColors.Cyan
            drawCircle(Brush.radialGradient(listOf(glow.copy(alpha = 0.16f), Color.Transparent), center, size.minDimension / 2f),
                radius = size.minDimension / 2f)
            if (nodes.isEmpty()) return@Canvas
            val pts = project(nodes, yaw, pitch, size.width, size.height)
            val byIndex = pts.associateBy { it.index }
            graph!!.edges.forEach { (a, b) ->
                val p = byIndex[a] ?: return@forEach
                val q = byIndex[b] ?: return@forEach
                val alpha = (0.10f + 0.18f * ((p.scale + q.scale) / 2f - 0.6f)).coerceIn(0.04f, 0.35f)
                drawLine(glow.copy(alpha = alpha), Offset(p.x, p.y), Offset(q.x, q.y), strokeWidth = 1.2f)
            }
            pts.forEach { p ->
                val n = nodes[p.index]
                val base = Color(graph.colors[n.category] ?: 0xFF39C6FF)
                val pulse = pulses[n.id]
                val flash = pulse?.let { 1f - ((now - it.atMs) / StageState.PULSE_MS.toFloat()).coerceIn(0f, 1f) } ?: 0f
                val active = n.id in graph.active
                val radius = (3.2f + 3.5f * p.scale) * (if (active) 1.4f else 1f) * (1f + flash)
                val color = when {
                    flash > 0f && pulse?.kind == "write" -> JarvisColors.Amber
                    flash > 0f -> JarvisColors.Ice
                    else -> base
                }
                val alpha = (0.35f + 0.55f * (p.scale - 0.6f)).coerceIn(0.25f, 1f)
                if (active || flash > 0f) {
                    drawCircle(Brush.radialGradient(listOf(color.copy(alpha = 0.5f), Color.Transparent), Offset(p.x, p.y), radius * 4),
                        radius = radius * 4, center = Offset(p.x, p.y))
                }
                drawCircle(color.copy(alpha = alpha), radius = radius, center = Offset(p.x, p.y))
            }
        }
        Text(
            if (nodes.isEmpty()) "OTAK JARVIS · belum ada memori" else "OTAK JARVIS · ${graph?.total ?: nodes.size} memori",
            color = JarvisColors.Muted, fontSize = 10.sp, letterSpacing = 2.sp,
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 6.dp),
        )
    }
}
