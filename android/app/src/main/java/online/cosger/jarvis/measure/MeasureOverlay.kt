package online.cosger.jarvis.measure

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View

/** The points, the lines between them and their lengths, drawn over the camera image (screen positions computed each frame). */
class MeasureOverlay(context: Context) : View(context) {
    @Volatile var points: List<Pair<Float, Float>?> = emptyList()
    @Volatile var lengths: List<String> = emptyList()
    private val dot = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.parseColor("#3FD0FF"); style = Paint.Style.FILL }
    private val ring = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; style = Paint.Style.STROKE; strokeWidth = 4f }
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.parseColor("#3FD0FF"); strokeWidth = 7f }
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = 46f; isFakeBoldText = true; setShadowLayer(8f, 0f, 0f, Color.BLACK) }
    private val cross = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; strokeWidth = 3f }

    override fun onDraw(c: Canvas) {
        val cx = width / 2f; val cy = height / 2f
        c.drawLine(cx - 30, cy, cx + 30, cy, cross); c.drawLine(cx, cy - 30, cx, cy + 30, cross)   // the aim: tapping anywhere also works
        val pts = points
        for (i in 0 until pts.size - 1) {
            val a = pts[i] ?: continue
            val b = pts[i + 1] ?: continue
            c.drawLine(a.first, a.second, b.first, b.second, line)
            lengths.getOrNull(i)?.let { c.drawText(it, (a.first + b.first) / 2 + 16, (a.second + b.second) / 2 - 16, text) }
        }
        for (p in pts) p?.let { c.drawCircle(it.first, it.second, 16f, dot); c.drawCircle(it.first, it.second, 16f, ring) }
    }
}
