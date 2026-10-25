package online.cosger.jarvis.net

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * REST access to jarvis-core for everything outside the chat socket: the owner console (same data as
 * the web admin, /api/v1/console/…), the AI composition, the brain graph, documents, meetings, voiceprint.
 * Answers are kept as JSON trees; screens read the fields they show.
 */
class ConsoleApi(
    private val baseUrl: () -> String,
    private val token: () -> String,
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS).readTimeout(5, TimeUnit.MINUTES).build(),
) {
    private val json = Json { ignoreUnknownKeys = true }
    private val jsonType = "application/json".toMediaType()

    private fun request(path: String): Request.Builder =
        Request.Builder().url(baseUrl().trimEnd('/') + path).header("Authorization", "Bearer ${token()}")

    private suspend fun call(req: Request): JsonElement = withContext(Dispatchers.IO) {
        client.newCall(req).execute().use { r ->
            val body = r.body?.string().orEmpty()
            if (!r.isSuccessful) throw CoreApiException(errorText(r.code, body))
            if (body.isBlank()) JsonObject(emptyMap()) else json.parseToJsonElement(body)
        }
    }

    suspend fun get(path: String): JsonElement = call(request(path).get().build())
    suspend fun post(path: String, body: JsonElement = JsonObject(emptyMap())): JsonElement =
        call(request(path).post(body.toString().toRequestBody(jsonType)).build())
    suspend fun put(path: String, body: JsonElement): JsonElement =
        call(request(path).put(body.toString().toRequestBody(jsonType)).build())
    suspend fun patch(path: String, body: JsonElement): JsonElement =
        call(request(path).patch(body.toString().toRequestBody(jsonType)).build())
    suspend fun delete(path: String): JsonElement = call(request(path).delete().build())

    /** Raw bytes upload (meeting audio chunk, voiceprint sample). */
    suspend fun putBytes(path: String, bytes: ByteArray, type: String = "application/octet-stream"): JsonElement =
        call(request(path).put(bytes.toRequestBody(type.toMediaType())).build())
    suspend fun postBytes(path: String, bytes: ByteArray, type: String = "application/octet-stream"): JsonElement =
        call(request(path).post(bytes.toRequestBody(type.toMediaType())).build())

    /** POST JSON, get raw bytes back (a sentence in JARVIS's cloud voice); null on any refusal or failure. */
    suspend fun postForBytes(path: String, body: JsonElement): ByteArray? = withContext(Dispatchers.IO) {
        runCatching {
            client.newCall(request(path).post(body.toString().toRequestBody(jsonType)).build()).execute().use { r ->
                if (r.isSuccessful) r.body?.bytes() else null
            }
        }.getOrNull()
    }

    /** Download a file (document, APK) into [target]; returns it. */
    suspend fun download(path: String, target: File): File = withContext(Dispatchers.IO) {
        client.newCall(request(path).get().build()).execute().use { r ->
            if (!r.isSuccessful) throw CoreApiException(errorText(r.code, r.body?.string().orEmpty()))
            target.parentFile?.mkdirs()
            target.outputStream().use { out -> r.body!!.byteStream().copyTo(out) }
        }
        target
    }

    /** A public https file JARVIS pointed to (e.g. a PDF on the web): no device token is sent there. */
    suspend fun downloadExternal(url: String, target: File): File = withContext(Dispatchers.IO) {
        require(url.startsWith("https://")) { "hanya https" }
        client.newCall(Request.Builder().url(url).get().build()).execute().use { r ->
            if (!r.isSuccessful) throw CoreApiException("HTTP ${r.code}")
            target.parentFile?.mkdirs()
            target.outputStream().use { out -> r.body!!.byteStream().copyTo(out) }
        }
        target
    }

    /** Header for players/loaders fetching /api/v1/media/... directly. */
    fun authHeader(): Map<String, String> = mapOf("Authorization" to "Bearer ${token()}")
    fun absolute(path: String): String = if (path.startsWith("https://")) path else baseUrl().trimEnd('/') + path

    companion object {
        fun errorText(code: Int, body: String): String {
            val detail = runCatching {
                Json.parseToJsonElement(body).jsonObject["detail"]?.jsonPrimitive?.contentOrNull
            }.getOrNull()
            return when {
                detail != null -> detail
                code == 401 -> "Token perangkat tidak valid"
                code == 403 -> "Perangkat ini tidak punya akses konsol pemilik"
                code == 404 -> "Tidak ditemukan"
                else -> "Server HTTP $code"
            }
        }
    }
}
