package online.cosger.jarvis.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** Events from jarvis-core over WSS (see docs/api.md). Parsed leniently: unknown types are ignored. */
sealed interface ServerEvent {
    val sessionId: String?

    data class Status(val state: String, override val sessionId: String?) : ServerEvent
    data class Thought(val text: String, override val sessionId: String?) : ServerEvent
    data class Tool(
        val id: String, val name: String, val title: String, val label: String,
        val emoji: String, val running: Boolean, override val sessionId: String?,
    ) : ServerEvent
    data class Context(val query: String, val items: List<ContextItem>, override val sessionId: String?) : ServerEvent
    data class Delta(val text: String, override val sessionId: String?) : ServerEvent
    data class Reply(val text: String, val route: String, override val sessionId: String?) : ServerEvent
    data class Error(val message: String, override val sessionId: String?) : ServerEvent
    data object Pong : ServerEvent { override val sessionId: String? = null }
    data object AuthOk : ServerEvent { override val sessionId: String? = null }
}

data class ContextItem(val text: String, val category: String, val score: Double)

object Protocol {
    private val json = Json { ignoreUnknownKeys = true }

    private fun JsonObject.str(key: String): String = this[key]?.jsonPrimitive?.contentOrNull ?: ""

    fun parse(raw: String): ServerEvent? {
        val o = runCatching { json.parseToJsonElement(raw).jsonObject }.getOrNull() ?: return null
        val sid = o["session_id"]?.jsonPrimitive?.contentOrNull
        return when (o.str("type")) {
            "status" -> ServerEvent.Status(o.str("state"), sid)
            "thought" -> ServerEvent.Thought(o.str("text"), sid)
            "tool" -> ServerEvent.Tool(
                o.str("id"), o.str("name"), o.str("title"), o.str("label"), o.str("emoji"),
                o.str("status") != "completed", sid,
            )
            "context" -> ServerEvent.Context(
                o.str("query"),
                o["items"]?.jsonArray?.map {
                    val item = it.jsonObject
                    ContextItem(item.str("text"), item.str("category"), item["score"]?.jsonPrimitive?.doubleOrNull ?: 0.0)
                } ?: emptyList(),
                sid,
            )
            "delta" -> ServerEvent.Delta(o.str("text"), sid)
            "reply" -> ServerEvent.Reply(o.str("text"), o.str("route"), sid)
            "error" -> ServerEvent.Error(o.str("message"), sid)
            "pong" -> ServerEvent.Pong
            "auth_ok" -> ServerEvent.AuthOk
            else -> null
        }
    }

    fun command(text: String, sessionId: String): String = buildJsonObject {
        put("user_command", text)
        put("session_id", sessionId)
    }.toString()

    const val PING = """{"type":"ping"}"""
}
