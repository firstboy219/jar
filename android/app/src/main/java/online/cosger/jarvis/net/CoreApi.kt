package online.cosger.jarvis.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException

class CoreApiException(message: String) : IOException(message)

/** REST calls to jarvis-core that are not part of the chat socket. */
class CoreApi(private val client: OkHttpClient = OkHttpClient()) {

    /** Short-lived Deepgram token (the real Deepgram key never ships in the APK). */
    suspend fun deepgramToken(baseUrl: String, deviceToken: String): String = withContext(Dispatchers.IO) {
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
            Json.parseToJsonElement(body).jsonObject["access_token"]?.jsonPrimitive?.content
                ?: throw CoreApiException("Jawaban server tidak berisi token")
        }
    }
}
