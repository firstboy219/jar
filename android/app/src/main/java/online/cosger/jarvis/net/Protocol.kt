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
    /** [spoken]: the reply was already said sentence by sentence ([Say] events) — do not say it again. */
    /** [speech]: the copy made for the ear (rupiah, dates, pronunciations; Fase 3) — [text] is what the screen shows.
     *  [localVoice]: private/sensitive — only the phone's own voice may say it. */
    data class Reply(val text: String, val route: String, override val sessionId: String?, val spoken: Boolean = false,
                     val speech: String? = null, val localVoice: Boolean = false) : ServerEvent
    /** One finished sentence of the answer, to speak right away (BR-001: talk while still thinking). */
    data class Say(val text: String, override val sessionId: String?, val localVoice: Boolean = false) : ServerEvent
    /** What the server heard in an utterance the phone sent (on-phone VAD + server speech recognition). */
    data class Transcript(val text: String, val seq: Long?, val isOwner: Boolean?, val error: String?, override val sessionId: String?,
                          val voiceEvent: Long? = null, val dropped: String? = null) : ServerEvent
    /** The phone's front screen ("Panggung"): show/update/close a panel (music, video, map, web, doc, draft, gallery). */
    data class Stage(val id: String, val panel: String, val mode: String, val payload: JsonObject, val caption: String) : ServerEvent {
        override val sessionId: String? = null
    }
    /** The desk's meeting card (or "selesai rapat") asks this phone to start / stop recording a meeting (ADR-054). */
    data class MeetingCmd(val cmd: String, val title: String = "", val confidential: Boolean = false,
                          val participants: List<String> = emptyList(), val agenda: String = "") : ServerEvent {
        override val sessionId: String? = null
    }
    /** Memories just read or written — the 3D brain flashes them. */
    /** Memories an agent just read or wrote; labels = their text (shown as "memori terlibat"). */
    data class BrainPulse(val ids: List<String>, val kind: String, val labels: List<String> = emptyList()) : ServerEvent {
        override val sessionId: String? = null
    }
    /** Hermes paused before a risky command and asks the owner (Approval Center). */
    data class Approval(val id: Long, val title: String, val risk: String) : ServerEvent { override val sessionId: String? = null }
    data class Error(val message: String, override val sessionId: String?) : ServerEvent
    /** A worker task changed state (queued/running/completed/failed/cancelled). */
    data class Task(val id: Long, val title: String, val status: String) : ServerEvent { override val sessionId: String? = null }
    /** Snapshot of active tasks sent on connect. */
    data class Tasks(val items: List<Task>) : ServerEvent { override val sessionId: String? = null }
    /** Live progress of one worker (wraps a thought/tool/context event). */
    data class TaskEvent(val taskId: Long, val event: ServerEvent) : ServerEvent { override val sessionId: String? = null }
    /** A worker result JARVIS must say out loud until the owner confirms hearing it. */
    data class Report(val id: Long, val taskId: Long?, val text: String, val attempt: Int, val repeat: Boolean,
                      val speech: String? = null, val localVoice: Boolean = false) : ServerEvent {
        override val sessionId: String? = null
    }
    data class ReportAck(val id: Long) : ServerEvent { override val sessionId: String? = null }
    /** JARVIS speaks first because of the situation it observed (place, time, agenda, habits). */
    data class Proactive(val text: String, val speech: String? = null, val localVoice: Boolean = false) : ServerEvent {
        override val sessionId: String? = null
    }
    /** Something JARVIS says on its own once (e.g. about a new notification); no confirmation needed. */
    data class Announce(val text: String, val speech: String? = null, val localVoice: Boolean = false) : ServerEvent {
        override val sessionId: String? = null
    }
    /** Pictures/videos JARVIS wants the owner to see. */
    data class Media(val caption: String, val items: List<MediaItem>) : ServerEvent { override val sessionId: String? = null }
    data class ReportUnheard(val id: Long) : ServerEvent { override val sessionId: String? = null }
    /** ADR-077: one instruction for the accessibility service (observe, tap, type, scroll, back, open, screenshot, begin, end). */
    data class PhoneOp(val req: String, val op: String, val args: JsonObject) : ServerEvent { override val sessionId: String? = null }
    /** ADR-077: JARVIS asks to operate an app (status "awaiting") — or the ask was settled (approved / rejected / expired). */
    data class PhoneApproval(val id: Long, val status: String, val label: String, val goal: String, val requestedBy: String,
                             val expiresInS: Long) : ServerEvent { override val sessionId: String? = null }
    /** ADR-079: a notification for the phone's notification shade (a project's pick is waiting, a run ended …) — never spoken. */
    data class Notify(val title: String, val text: String, val kind: String, val route: String = "") : ServerEvent { override val sessionId: String? = null }
    /** ADR-087: a feature's settings changed on the server (from the web or the app) — the phone re-reads what it keeps itself (the alarm). */
    data class SettingsChanged(val key: String) : ServerEvent { override val sessionId: String? = null }
    /** ADR-087: the live trip (its next leg) for the ongoing notification; status done/cancelled clears it. */
    data class Trip(val id: Long, val status: String, val title: String, val text: String, val route: String) : ServerEvent { override val sessionId: String? = null }
    /** ADR-079: a project asks the owner to pick one option (status "open"), or the pick was settled (answered / expired / cancelled). */
    data class OwnerChoice(val id: Long, val status: String, val title: String, val prompt: String, val options: List<ChoiceOption>,
                           val expiresInS: Long) : ServerEvent { override val sessionId: String? = null }
    data object Pong : ServerEvent { override val sessionId: String? = null }
    data object AuthOk : ServerEvent { override val sessionId: String? = null }
}

data class ChoiceOption(val index: Int, val label: String, val detail: String, val time: String)

data class ContextItem(val text: String, val category: String, val score: Double)

data class MediaItem(val kind: String, val url: String, val title: String, val thumbnail: String?, val source: String) {
    val isVideo: Boolean get() = kind == "video"
    /** What to draw: the image itself, or a video's thumbnail. */
    val preview: String? get() = if (isVideo) thumbnail else url
}

/** Phone position shared with JARVIS when the owner enabled it. */
data class DeviceLocation(
    val lat: Double, val lon: Double, val accuracyM: Double?, val ageSeconds: Long, val address: String?,
    val speedMps: Double? = null,
)

object Protocol {
    private val json = Json { ignoreUnknownKeys = true }

    private fun JsonObject.str(key: String): String = this[key]?.jsonPrimitive?.contentOrNull ?: ""

    private fun JsonObject.long(key: String): Long? = this[key]?.jsonPrimitive?.longOrNull
    private fun JsonObject.speech(): String? = this["speech"]?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() }
    private fun JsonObject.localVoice(): Boolean = this["local_voice"]?.jsonPrimitive?.booleanOrNull == true

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
            "reply" -> ServerEvent.Reply(o.str("text"), o.str("route"), sid, o["spoken"]?.jsonPrimitive?.booleanOrNull == true,
                o.speech(), o.localVoice())
            "say" -> ServerEvent.Say(o.str("text"), sid, o.localVoice())
            "transcript" -> ServerEvent.Transcript(
                o.str("text"), o.long("seq"), o["is_owner"]?.jsonPrimitive?.booleanOrNull,
                o["error"]?.jsonPrimitive?.contentOrNull, sid, o.long("voice_event"), o["dropped"]?.jsonPrimitive?.contentOrNull,
            )
            "stage" -> ServerEvent.Stage(
                o.str("id"), o.str("panel"), o.str("mode").ifEmpty { "show" },
                o["payload"] as? JsonObject ?: JsonObject(emptyMap()), o.str("caption"),
            )
            "meeting_cmd" -> ServerEvent.MeetingCmd(
                o.str("cmd"), o.str("title"), o["confidential"]?.jsonPrimitive?.booleanOrNull == true,
                o["participants"]?.jsonArray?.mapNotNull { it.jsonPrimitive.contentOrNull } ?: emptyList(), o.str("agenda"),
            )
            "brain_pulse" -> ServerEvent.BrainPulse(
                o["ids"]?.jsonArray?.mapNotNull { it.jsonPrimitive.contentOrNull } ?: emptyList(), o.str("kind"),
                o["labels"]?.jsonArray?.mapNotNull { it.jsonPrimitive.contentOrNull } ?: emptyList(),
            )
            "approval" -> ServerEvent.Approval(o.long("id") ?: return null, o.str("title"), o.str("risk"))
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
                o.speech(), o.localVoice(),
            )
            "report_ack" -> ServerEvent.ReportAck(o.long("id") ?: return null)
            "announce" -> ServerEvent.Announce(o.str("text"), o.speech(), o.localVoice())
            "proactive" -> ServerEvent.Proactive(o.str("text"), o.speech(), o.localVoice())
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
            "phone_op" -> ServerEvent.PhoneOp(o.str("req"), o.str("op"), o)
            "phone_approval" -> ServerEvent.PhoneApproval(o.long("id") ?: return null, o.str("status").ifEmpty { "awaiting" }, o.str("label"),
                o.str("goal"), o.str("requested_by"), o.long("expires_in_s") ?: 900)
            "notify" -> ServerEvent.Notify(o.str("title"), o.str("text"), o.str("kind"), o.str("route"))
            "settings" -> ServerEvent.SettingsChanged(o.str("key"))
            "trip" -> ServerEvent.Trip(o["id"]?.jsonPrimitive?.longOrNull ?: 0, o.str("status"), o.str("title"), o.str("text"), o.str("route"))
            "owner_choice" -> ServerEvent.OwnerChoice(
                o.long("id") ?: return null, o.str("status").ifEmpty { "open" }, o.str("title"), o.str("prompt"),
                o["options"]?.jsonArray?.mapNotNull {
                    val c = it.jsonObject
                    c.long("i")?.let { i -> ChoiceOption(i.toInt(), c.str("label"), c.str("detail"), c.str("waktu")) }
                } ?: emptyList(),
                o.long("expires_in_s") ?: 0,
            )
            "pong" -> ServerEvent.Pong
            "auth_ok" -> ServerEvent.AuthOk
            else -> null
        }
    }

    fun command(
        text: String, sessionId: String, location: DeviceLocation? = null, screenJpegBase64: String? = null,
        imageSource: String? = null, confidence: Double? = null, speakers: Int? = null, screenText: String? = null,
        attachments: List<String> = emptyList(),
    ): String = buildJsonObject {
        put("user_command", text)
        put("session_id", sessionId)
        if (attachments.isNotEmpty()) put("attachments", kotlinx.serialization.json.JsonArray(
            attachments.take(5).map { kotlinx.serialization.json.JsonPrimitive(it) }))
        screenText?.takeIf { it.isNotBlank() }?.let { put("screen_text", it.take(20_000)) }
        screenJpegBase64?.let {
            put("screen", it)
            put("image_source", imageSource ?: "screen")
        }
        if (confidence != null || speakers != null) put("stt", buildJsonObject {
            confidence?.let { put("confidence", it) }
            speakers?.let { put("speakers", it) }
        })
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

    /** One utterance cut by the phone's VAD: PCM16 mono 16 kHz, transcribed on the server (v0.7). */
    fun utterance(
        sessionId: String, seq: Long, pcm: ByteArray, location: DeviceLocation? = null, screenJpegBase64: String? = null,
        imageSource: String? = null, screenText: String? = null,
    ): String = buildJsonObject {
        put("type", "utterance")
        put("session_id", sessionId)
        put("seq", seq)
        put("audio", java.util.Base64.getEncoder().encodeToString(pcm))
        screenText?.takeIf { it.isNotBlank() }?.let { put("screen_text", it.take(20_000)) }
        screenJpegBase64?.let {
            put("screen", it)
            put("image_source", imageSource ?: "screen")
        }
        location?.let { l ->
            put("location", buildJsonObject {
                put("lat", l.lat); put("lon", l.lon)
                l.accuracyM?.let { put("accuracy_m", it) }
                put("age_s", l.ageSeconds)
                l.address?.let { put("address", it.take(300)) }
            })
        }
    }.toString()

    /** The owner acted on a stage panel: closed, login_done, route_selected, draft_copied, draft_sent, paused. */
    fun stageEvent(id: String, event: String, detail: Map<String, Int> = emptyMap()): String = buildJsonObject {
        put("type", "stage_event")
        put("id", id)
        put("event", event)
        if (detail.isNotEmpty()) put("detail", buildJsonObject { detail.forEach { (k, v) -> put(k, v) } })
    }.toString()

    fun control(type: String, idKey: String, id: Long): String = buildJsonObject {
        put("type", type)
        put(idKey, id)
    }.toString()

    /** Context heartbeat for situational awareness (see core/app/awareness.py). */
    fun context(c: online.cosger.jarvis.data.PhoneContext): String = buildJsonObject {
        put("type", "context")
        put("context", buildJsonObject {
            c.location?.let { l ->
                put("location", buildJsonObject {
                    put("lat", l.lat); put("lon", l.lon)
                    l.accuracyM?.let { put("accuracy_m", it) }
                    put("age_s", l.ageSeconds)
                    l.address?.let { put("address", it.take(300)) }
                })
            }
            put("activity", c.activity)
            c.speedKmh?.let { put("speed_kmh", it) }
            c.battery?.let { put("battery", it) }
            c.charging?.let { put("charging", it) }
            c.headset?.let { put("headset", it) }
            c.screenOn?.let { put("screen_on", it) }
            c.network?.let { put("network", it) }
            put("unmuted", c.unmuted)
            put("app_version", c.appVersion)
            put("calendar", kotlinx.serialization.json.buildJsonArray {
                c.calendar.take(8).forEach { e ->
                    add(buildJsonObject {
                        put("title", e.title.take(200)); put("start_ms", e.startMs)
                        e.endMs?.let { put("end_ms", it) }
                        e.location?.let { put("location", it.take(200)) }
                    })
                }
            })
        })
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
