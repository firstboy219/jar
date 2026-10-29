package online.cosger.jarvis.phone

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/** One instruction from jarvis-core (`phone_op`, ADR-077) → [PhoneAgentService] → the `phone_result` message sent back. */
object PhoneOps {
    private fun JsonObject.s(k: String) = this[k]?.jsonPrimitive?.contentOrNull.orEmpty()
    private fun JsonObject.i(k: String) = this[k]?.jsonPrimitive?.intOrNull

    suspend fun handle(context: android.content.Context, req: String, op: String, a: JsonObject, onStop: (Long) -> Unit): String {
        val answer: JsonObject = try {
            if (op == "notif_reply") {   // ADR-087: a reply the owner sent from the app, through the messaging app's own notification reply
                val thread = online.cosger.jarvis.notify.Conversations.find(a.s("title"))
                    ?.takeIf { it.title.equals(a.s("title"), ignoreCase = true) || a.s("title").isBlank() }
                    ?: throw PhoneOpException("percakapan \"${a.s("title")}\" tidak ada di notifikasi HP (buka WhatsApp sekali, lalu coba lagi)")
                val ok = online.cosger.jarvis.notify.Conversations.reply(context, thread, a.s("text").take(2000))
                if (!ok) throw PhoneOpException("notifikasi itu tidak bisa dibalas dari luar (sudah dibuka/dihapus)")
                return buildJsonObject { put("type", "phone_result"); put("req", req); put("ok", true); put("title", thread.title) }.toString()
            }
            val svc = PhoneAgentService.instance
                ?: throw PhoneOpException("Aksesibilitas JARVIS belum aktif di HP (Lainnya → Setelan HP → 5. Operasi aplikasi)")
            when (op) {
                "begin" -> {
                    val run = a["run"]?.jsonPrimitive?.longOrNull ?: 0L
                    val pkgs = a["packages"]?.jsonArray?.mapNotNull { it.jsonPrimitive.contentOrNull }?.toSet().orEmpty()
                    svc.begin(run, a.s("label"), pkgs) { onStop(run) }
                    buildJsonObject { put("ok", true) }
                }
                "end" -> { svc.end(); buildJsonObject { put("ok", true) } }
                "observe" -> svc.observe()
                "open" -> svc.open(a.s("package"))
                "tap" -> svc.tap(a.i("index"))
                "type" -> svc.type(a.i("index"), a.s("text"), a["submit"]?.jsonPrimitive?.booleanOrNull == true)
                "scroll" -> svc.scroll(a.s("direction"), a.i("index"))
                "back" -> svc.back()
                "screenshot" -> svc.screenshot()
                else -> throw PhoneOpException("perintah tidak dikenal: $op")
            }
        } catch (e: PhoneOpException) {
            buildJsonObject { put("error", e.message ?: "gagal") }
        } catch (e: Exception) {
            buildJsonObject { put("error", "HP: ${e.javaClass.simpleName}: ${e.message ?: ""}".take(300)) }
        }
        return buildJsonObject {
            put("type", "phone_result")
            put("req", req)
            answer.forEach { (k, v) -> put(k, v) }
        }.toString()
    }
}
