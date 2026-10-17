package online.cosger.jarvis.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull
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
    /** A worker task changed state (queued/running/completed/failed/cancelled). */
    data class Task(val id: Long, val title: String, val status: String) : ServerEvent { override val sessionId: String? = null }
    /** Snapshot of active tasks sent on connect. */
    data class Tasks(val items: List<Task>) : ServerEvent { override val sessionId: String? = null }
    /** Live progress of one worker (wraps a thought/tool/context event). */
    data class TaskEvent(val taskId: Long, val event: ServerEvent) : ServerEvent { override val sessionId: String? = null }
    /** A worker result JARVIS must say out loud until the owner confirms hearing it. */
    data class Report(val id: Long, val taskId: Long?, val text: String, val attempt: Int, val repeat: Boolean) : ServerEvent {
        override val sessionId: String? = null
    }
    data class ReportAck(val id: Long) : ServerEvent { override val sessionId: String? = null }
    /** Something JARVIS says on its own once (e.g. about a new notification); no confirmation needed. */
    data class Announce(val text: String) : ServerEvent { override val sessionId: String? = null }
    /** Pictures/videos JARVIS wants the owner to see. */
    data class Media(val caption: String, val items: List<MediaItem>) : ServerEvent { override val sessionId: String? = null }
    data class ReportUnheard(val id: Long) : ServerEvent { override val sessionId: String? = null }
    data object Pong : ServerEvent { override val sessionId: String? = null }
    data object AuthOk : ServerEvent { override val sessionId: String? = null }
}

data class ContextItem(val text: String, val category: String, val score: Double)

data class MediaItem(val kind: String, val url: String, val title: String, val thumbnail: String?, val source: String) {
    val isVideo: Boolean get() = kind == "video"
    /** What to draw: the image itself, or a video's thumbnail. */
    val preview: String? get() = if (isVideo) thumbnail else url
}

/** Phone position shared with JARVIS when the owner enabled it. */
data class DeviceLocation(
    val lat: Double, val lon: Double, val accuracyM: Double?, val ageSeconds: Long, val address: String?,
)

object Protocol {
    private val json = Json { ignoreUnknownKeys = true }

    private fun JsonObject.str(key: String): String = this[key]?.jsonPrimitive?.contentOrNull ?: ""

    private fun JsonObject.long(key: String): Long? = this[key]?.jsonPrimitive?.longOrNull

    fun parse(raw: String): ServerEvent? {
        val o = runCatching { json.parseToJsonElement(raw).jsonObject }.getOrNull() ?: return null
        return parseObject(o)
    }

    private fun parseObject(o: JsonObject): ServerEvent? {
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
            "task" -> ServerEvent.Task(o.long("id") ?: return null, o.str("title"), o.str("status"))
            "tasks" -> ServerEvent.Tasks(
                o["items"]?.jsonArray?.mapNotNull {
                    val t = it.jsonObject
                    t.long("id")?.let { id -> ServerEvent.Task(id, t.str("title"), t.str("status")) }
                } ?: emptyList(),
            )
            "task_event" -> {
                val inner = o["event"]?.jsonObject?.let(::parseObject) ?: return null
                ServerEvent.TaskEvent(o.long("task_id") ?: return null, inner)
            }
            "report" -> ServerEvent.Report(
                o.long("id") ?: return null, o.long("task_id"), o.str("text"),
                o["attempt"]?.jsonPrimitive?.intOrNull ?: 1, o["repeat"]?.jsonPrimitive?.booleanOrNull == true,
            )
            "report_ack" -> ServerEvent.ReportAck(o.long("id") ?: return null)
            "announce" -> ServerEvent.Announce(o.str("text"))
            "media" -> ServerEvent.Media(
                o.str("caption"),
                o["items"]?.jsonArray?.mapNotNull {
                    val m = it.jsonObject
                    val url = m.str("url")
                    if (!url.startsWith("https://")) null
                    else MediaItem(m.str("kind").ifEmpty { "image" }, url, m.str("title"),
                        m["thumbnail"]?.jsonPrimitive?.contentOrNull?.takeIf { t -> t.startsWith("https://") }, m.str("source"))
                } ?: emptyList(),
            )
            "report_unheard" -> ServerEvent.ReportUnheard(o.long("id") ?: return null)
            "pong" -> ServerEvent.Pong
            "auth_ok" -> ServerEvent.AuthOk
            else -> null
        }
    }

    fun command(text: String, sessionId: String, location: DeviceLocation? = null, screenJpegBase64: String? = null): String = buildJsonObject {
        put("user_command", text)
        put("session_id", sessionId)
        screenJpegBase64?.let { put("screen", it) }
        if (location != null) {
            put("location", buildJsonObject {
                put("lat", location.lat)
                put("lon", location.lon)
                location.accuracyM?.let { put("accuracy_m", it) }
                put("age_s", location.ageSeconds)
                location.address?.let { put("address", it.take(300)) }
            })
        }
    }.toString()

    fun control(type: String, idKey: String, id: Long): String = buildJsonObject {
        put("type", type)
        put(idKey, id)
    }.toString()

    fun notification(app: String, pkg: String, title: String, text: String, postedAtMs: Long): String = buildJsonObject {
        put("type", "notification")
        put("notification", buildJsonObject {
            put("app", app.take(80))
            put("package", pkg.take(200))
            put("title", title.take(300))
            put("text", text.take(2000))
            put("posted_at", postedAtMs)
        })
    }.toString()

    const val PING = """{"type":"ping"}"""
}
