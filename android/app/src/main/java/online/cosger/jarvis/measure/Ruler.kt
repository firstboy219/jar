package online.cosger.jarvis.measure

import kotlin.math.sqrt

/** The arithmetic of the AR ruler. Pure; unit-tested. */
object Ruler {
    data class P(val x: Float, val y: Float, val z: Float)

    fun distance(a: P, b: P): Float {
        val dx = a.x - b.x; val dy = a.y - b.y; val dz = a.z - b.z
        return sqrt(dx * dx + dy * dy + dz * dz)
    }

    /** Metres between consecutive points. */
    fun segments(points: List<P>): List<Float> = points.zipWithNext { a, b -> distance(a, b) }

    /** "1,42 m" / "86 cm". */
    fun label(m: Float): String = if (m < 1f) "${Math.round(m * 100)} cm" else String.format(java.util.Locale("id", "ID"), "%.2f m", m)

    /** A world point to the screen (column-major 4×4 view-projection); null when it is behind the camera. */
    fun project(vp: FloatArray, p: P, w: Int, h: Int): Pair<Float, Float>? {
        val x = vp[0] * p.x + vp[4] * p.y + vp[8] * p.z + vp[12]
        val y = vp[1] * p.x + vp[5] * p.y + vp[9] * p.z + vp[13]
        val cw = vp[3] * p.x + vp[7] * p.y + vp[11] * p.z + vp[15]
        if (cw <= 1e-4f) return null
        return ((x / cw + 1f) / 2f * w) to ((1f - y / cw) / 2f * h)
    }
}
