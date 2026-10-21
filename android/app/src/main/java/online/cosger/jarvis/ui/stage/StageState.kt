package online.cosger.jarvis.ui.stage

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import online.cosger.jarvis.net.ServerEvent

/** One panel JARVIS put on the front screen. */
data class Panel(val id: String, val kind: String, val payload: JsonObject, val caption: String) {
    fun str(key: String): String = payload[key]?.jsonPrimitive?.contentOrNull.orEmpty()
    fun int(key: String): Int? = payload[key]?.jsonPrimitive?.intOrNull
    fun list(key: String): List<JsonObject> = (payload[key] as? JsonArray)?.mapNotNull { it as? JsonObject } ?: emptyList()

    /** Media starts playing by itself unless it is not the first player on a board. */
    val autoplay: Boolean get() = payload["autoplay"]?.jsonPrimitive?.booleanOrNull != false

    /** A board's blocks as panels of their own (rendered by the same composables). */
    fun blocks(): List<Panel> {
        var mediaSeen = false
        return list("blocks").mapIndexedNotNull { i, b ->
            val kind = b["kind"]?.jsonPrimitive?.contentOrNull ?: return@mapIndexedNotNull null
            if (kind !in StageState.BLOCKS) return@mapIndexedNotNull null
            val media = kind in setOf("music", "audio", "video")
            val body = JsonObject(b - "kind" + ("autoplay" to JsonPrimitive(media && !mediaSeen)))
            if (media) mediaSeen = true
            Panel("$id-$i", kind, body, "")
        }
    }
}

/**
 * The phone's front screen. Pure value + reducer (unit-tested). The 3D brain is always the background;
 * on top, the panel JARVIS opened (music, audio, video, image, gallery, map, web, doc, text, draft, or a
 * board with several of them). Memory pulses are kept for a few seconds so the brain can flash the nodes
 * just read or written; the memories involved stay listed for two minutes.
 */
data class StageState(
    val panel: Panel? = null,
    val pulses: Map<String, Pulse> = emptyMap(),
    val involved: List<Involved> = emptyList(),
) {
    data class Pulse(val kind: String, val atMs: Long, val label: String = "")

    /** A memory JARVIS just used (read) or learned (write) — listed under the brain for a while. */
    data class Involved(val id: String, val label: String, val kind: String, val atMs: Long)

    fun reduce(e: ServerEvent.Stage, nowMs: Long = System.currentTimeMillis()): StageState = when (e.mode) {
        "close" -> close(e.id)
        "update" -> if (panel?.id == e.id) copy(panel = panel.copy(payload = e.payload)) else this
        else -> if (e.panel in KINDS) copy(panel = Panel(e.id, e.panel, e.payload, e.caption)) else this
    }.prune(nowMs)

    fun close(id: String): StageState = if (panel?.id == id) copy(panel = null) else this

    /** Route chips on the map panel. */
    fun select(index: Int): StageState {
        val p = panel ?: return this
        return copy(panel = p.copy(payload = JsonObject(p.payload + ("selected" to JsonPrimitive(index)))))
    }

    fun pulse(ids: List<String>, kind: String, labels: List<String> = emptyList(), nowMs: Long = System.currentTimeMillis()): StageState {
        val label = { i: Int -> labels.getOrNull(i).orEmpty() }
        val fresh = ids.mapIndexedNotNull { i, id -> label(i).takeIf { it.isNotBlank() }?.let { Involved(id, it, kind, nowMs) } }
        return copy(
            pulses = pulses + ids.mapIndexed { i, id -> id to Pulse(kind, nowMs, label(i)) },
            involved = (fresh + involved.filter { old -> fresh.none { it.id == old.id } }).take(MAX_INVOLVED),
        ).prune(nowMs)
    }

    private fun prune(nowMs: Long) = copy(
        pulses = pulses.filterValues { nowMs - it.atMs < PULSE_MS },
        involved = involved.filter { nowMs - it.atMs < INVOLVED_MS },
    )

    companion object {
        val KINDS = setOf("music", "audio", "video", "image", "map", "web", "doc", "text", "draft", "gallery", "board")
        const val PULSE_MS = 6_000L
        const val INVOLVED_MS = 120_000L
        const val MAX_INVOLVED = 6
        val BLOCKS = KINDS - setOf("board", "draft")
    }
}

/** Memories laid out in 3D on the server (PCA of their embeddings, two hemispheres). */
data class BrainGraph(
    val nodes: List<Node>,
    val edges: List<Pair<Int, Int>>,
    val active: Set<String>,
    val colors: Map<String, Long>,
    val total: Int,
) {
    data class Node(val id: String, val x: Float, val y: Float, val z: Float, val category: String, val label: String)

    companion object {
        fun parse(json: JsonElement): BrainGraph {
            val o = json.jsonObject
            val nodes = o["nodes"]?.jsonArray?.map {
                val n = it.jsonObject
                Node(n.s("id"), n.f("x"), n.f("y"), n.f("z"), n.s("category"), n.s("label"))
            } ?: emptyList()
            val edges = o["edges"]?.jsonArray?.mapNotNull { e ->
                val a = e.jsonArray
                val i = a.getOrNull(0)?.jsonPrimitive?.intOrNull
                val j = a.getOrNull(1)?.jsonPrimitive?.intOrNull
                if (i != null && j != null && i < nodes.size && j < nodes.size) i to j else null
            } ?: emptyList()
            val colors = o["categories"]?.jsonObject?.mapValues { (_, v) ->
                v.jsonPrimitive.contentOrNull?.removePrefix("#")?.toLongOrNull(16)?.or(0xFF000000) ?: 0xFF39C6FF
            } ?: emptyMap()
            return BrainGraph(nodes, edges, o["active"]?.jsonArray?.mapNotNull { it.jsonPrimitive.contentOrNull }?.toSet() ?: emptySet(),
                colors, o["total"]?.jsonPrimitive?.intOrNull ?: nodes.size)
        }

        private fun JsonObject.s(k: String) = this[k]?.jsonPrimitive?.contentOrNull.orEmpty()
        private fun JsonObject.f(k: String) = this[k]?.jsonPrimitive?.doubleOrNull?.toFloat() ?: 0f
    }
}

/** Small JSON readers shared by the stage panels and console screens. */
fun JsonElement?.obj(): JsonObject = this as? JsonObject ?: JsonObject(emptyMap())
fun JsonElement?.arr(): List<JsonElement> = (this as? JsonArray)?.toList() ?: emptyList()
fun JsonObject.s(key: String): String = (this[key] as? JsonPrimitive)?.contentOrNull.orEmpty()
fun JsonObject.d(key: String): Double? = (this[key] as? JsonPrimitive)?.doubleOrNull
fun JsonObject.i(key: String): Int? = (this[key] as? JsonPrimitive)?.intOrNull
fun JsonObject.b(key: String): Boolean = (this[key] as? JsonPrimitive)?.booleanOrNull == true
