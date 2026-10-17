package online.cosger.jarvis.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import online.cosger.jarvis.voice.SttConfig
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

class CoreApiException(message: String) : IOException(message)

/** REST calls to jarvis-core that are not part of the chat socket. */
class CoreApi(private val client: OkHttpClient = OkHttpClient()) {

    /** Short-lived Deepgram token + recognition settings (the real Deepgram key never ships in the APK). */
    suspend fun sttConfig(baseUrl: String, deviceToken: String): SttConfig = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/api/v1/deepgram/token")
            .header("Authorization", "Bearer $deviceToken")
            .build()
        client.newCall(request).execute().use { r ->
            val body = r.body?.string().orEmpty()
            if (!r.isSuccessful) {
                throw CoreApiException(
                    when (r.code) {
                        401 -> "Token perangkat tidak valid"
                        503 -> "Voice belum dikonfigurasi di server"
                        else -> "Server HTTP ${r.code}"
                    }
                )
            }
            parseSttConfig(body, System.currentTimeMillis())
        }
    }

    companion object {
        fun parseSttConfig(body: String, nowMs: Long): SttConfig {
            val o = Json.parseToJsonElement(body).jsonObject
            val token = o["access_token"]?.jsonPrimitive?.contentOrNull
                ?: throw CoreApiException("Jawaban server tidak berisi token")
            val ttl = o["expires_in"]?.jsonPrimitive?.intOrNull ?: 30
            return SttConfig(
                token = token,
                model = o["model"]?.jsonPrimitive?.contentOrNull ?: "nova-2",
                language = o["language"]?.jsonPrimitive?.contentOrNull ?: "id",
                keywords = o["keywords"]?.jsonArray?.mapNotNull { it.jsonPrimitive.contentOrNull } ?: emptyList(),
                expiresAtMs = nowMs + ttl * 1000L,
            )
        }
    }
}
