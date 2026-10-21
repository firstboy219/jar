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
}

/**
 * The phone's front screen. Pure value + reducer (unit-tested). Shows, in priority order: the panel
 * JARVIS opened (music, video, map, web, doc, draft, gallery), else the 3D brain. Memory pulses are
 * kept for a few seconds so the brain can flash the nodes that were just read or written.
 */
data class StageState(
    val panel: Panel? = null,
    val pulses: Map<String, Pulse> = emptyMap(),
) {
    data class Pulse(val kind: String, val atMs: Long)

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

    fun pulse(ids: List<String>, kind: String, nowMs: Long = System.currentTimeMillis()): StageState =
        copy(pulses = (pulses + ids.associateWith { Pulse(kind, nowMs) })).prune(nowMs)

    private fun prune(nowMs: Long) = copy(pulses = pulses.filterValues { nowMs - it.atMs < PULSE_MS })

    companion object {
        val KINDS = setOf("music", "video", "map", "web", "doc", "draft", "gallery")
        const val PULSE_MS = 6_000L
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
