package online.cosger.jarvis.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import online.cosger.jarvis.ui.Phase

object JarvisColors {
    val Background = Color(0xFF070B12)
    val Surface = Color(0xFF0E1520)
    val SurfaceHigh = Color(0xFF152030)
    val Border = Color(0xFF1F2C3E)
    val Text = Color(0xFFE6EEF7)
    val Muted = Color(0xFF7D8DA3)
    val Cyan = Color(0xFF39C6FF)
    val Ice = Color(0xFFB8ECFF)
    val Green = Color(0xFF3DDC97)
    val Amber = Color(0xFFFFB547)
    val Violet = Color(0xFF8F7CFF)
    val Red = Color(0xFFFF5D6C)

    fun forPhase(phase: Phase): Color = when (phase) {
        Phase.Idle, Phase.Done -> Cyan
        Phase.Listening -> Green
        Phase.Thinking -> Violet
        Phase.Acting -> Amber
        Phase.Answering -> Ice
        Phase.Failed -> Red
    }
}

@Composable
fun JarvisTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = JarvisColors.Cyan,
            onPrimary = JarvisColors.Background,
            background = JarvisColors.Background,
            onBackground = JarvisColors.Text,
            surface = JarvisColors.Surface,
            onSurface = JarvisColors.Text,
            surfaceVariant = JarvisColors.SurfaceHigh,
            onSurfaceVariant = JarvisColors.Muted,
            outline = JarvisColors.Border,
            error = JarvisColors.Red,
        ),
        content = content,
    )
}
