package online.cosger.jarvis.ui.screens

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import online.cosger.jarvis.ui.Phase
import online.cosger.jarvis.ui.theme.JarvisColors
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * JARVIS' "mind": a glowing core with rotating arc rings and orbiting thought particles.
 * Phase drives color and energy (listening reacts to the mic level; thinking swirls; acting spins fast).
 * [activity] (0..1) is how much is happening right now, e.g. bursts as thought tokens arrive.
 */
@Composable
fun ThoughtOrb(phase: Phase, micLevel: Float, activity: Float, modifier: Modifier = Modifier) {
    val color by animateColorAsState(JarvisColors.forPhase(phase), tween(600), label = "orbColor")
    val energyTarget = when (phase) {
        Phase.Idle, Phase.Done -> 0.15f
        Phase.Listening -> 0.35f + micLevel * 0.65f
        Phase.Thinking -> 0.65f + activity * 0.35f
        Phase.Acting -> 0.9f
        Phase.Answering -> 0.55f
        Phase.Failed -> 0.1f
    }
    val energy by animateFloatAsState(energyTarget, tween(350), label = "orbEnergy")

    val t = rememberInfiniteTransition(label = "orb")
    val time by t.animateFloat(0f, 1f, infiniteRepeatable(tween(12_000, easing = LinearEasing)), label = "time")
    val breath by t.animateFloat(0f, 1f, infiniteRepeatable(tween(3_600, easing = LinearEasing)), label = "breath")

    val particles = remember { List(36) { Particle.random(it) } }

    Canvas(modifier) {
        val c = center
        val r = size.minDimension / 2f
        val pulse = 0.5f + 0.5f * sin(breath * 2 * PI).toFloat()
        val coreR = r * (0.22f + 0.05f * pulse + 0.10f * energy)

        // outer glow
        drawCircle(
            Brush.radialGradient(listOf(color.copy(alpha = 0.28f * (0.4f + energy)), Color.Transparent), c, r),
            radius = r, center = c,
        )
        // rotating arc rings (speed scales with energy)
        val spin = time * 360f
        ring(c, r * 0.62f, color.copy(alpha = 0.55f), spin * (1f + 3f * energy), 4, 38f, r * 0.018f)
        ring(c, r * 0.76f, color.copy(alpha = 0.35f), -spin * (0.6f + 2f * energy), 7, 18f, r * 0.010f)
        ring(c, r * 0.90f, color.copy(alpha = 0.18f), spin * 0.4f, 24, 6f, r * 0.006f)

        // thought particles on tilted orbits
        particles.forEach { p ->
            val angle = (p.phase + time * p.speed * (0.4f + 2.2f * energy)) * 2 * PI
            val orbit = r * (p.radius * (0.85f + 0.25f * energy))
            val pos = Offset(
                c.x + (orbit * cos(angle)).toFloat(),
                c.y + (orbit * sin(angle) * p.tilt).toFloat(),
            )
            val a = (0.25f + 0.75f * energy) * p.brightness
            drawCircle(color.copy(alpha = a * 0.35f), radius = p.size * r * 2.6f, center = pos)
            drawCircle(color.copy(alpha = a), radius = p.size * r, center = pos)
        }

        // core
        drawCircle(
            Brush.radialGradient(listOf(Color.White.copy(alpha = 0.95f), color, color.copy(alpha = 0f)), c, coreR * 1.6f),
            radius = coreR * 1.6f, center = c,
        )
        drawCircle(color.copy(alpha = 0.9f), radius = coreR * 0.55f, center = c)
    }
}

private fun DrawScope.ring(
    c: Offset, radius: Float, color: Color, rotation: Float, segments: Int, sweep: Float, width: Float,
) {
    val step = 360f / segments
    for (i in 0 until segments) {
        drawArc(
            color = color,
            startAngle = rotation + i * step,
            sweepAngle = sweep.coerceAtMost(step * 0.8f),
            useCenter = false,
            topLeft = Offset(c.x - radius, c.y - radius),
            size = Size(radius * 2, radius * 2),
            style = Stroke(width = width, cap = StrokeCap.Round),
        )
    }
}

private data class Particle(
    val phase: Float, val speed: Float, val radius: Float, val tilt: Float, val size: Float, val brightness: Float,
) {
    companion object {
        fun random(seed: Int): Particle {
            val rnd = java.util.Random(seed * 7919L)
            return Particle(
                phase = rnd.nextFloat(),
                speed = 0.5f + rnd.nextFloat() * 1.5f,
                radius = 0.32f + rnd.nextFloat() * 0.6f,
                tilt = 0.35f + rnd.nextFloat() * 0.65f,
                size = 0.006f + rnd.nextFloat() * 0.012f,
                brightness = 0.4f + rnd.nextFloat() * 0.6f,
            )
        }
    }
}
