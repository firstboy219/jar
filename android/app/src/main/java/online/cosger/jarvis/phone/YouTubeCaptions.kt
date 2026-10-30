package online.cosger.jarvis.phone

import android.annotation.SuppressLint
import android.content.Context
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * ADR-087 (Video): a YouTube video's subtitles, fetched from the PHONE's own connection — YouTube refuses the server's address ("confirm
 * you're not a bot"). Only the watch page and the subtitle text are read; no video or audio is downloaded. The server parses the text.
 */
object YouTubeCaptions {
    data class Track(val lang: String, val url: String, val auto: Boolean)

    private val client by lazy { OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).build() }
    private const val UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
    private val ID = Regex("[A-Za-z0-9_-]{11}")
    private const val MAX_CHARS = 400_000

    private fun get(url: String): String = client.newCall(
        Request.Builder().url(url).header("User-Agent", UA).header("Accept-Language", "id-ID,id;q=0.9,en;q=0.8").build(),
    ).execute().use { r ->
        if (!r.isSuccessful) throw PhoneOpException("YouTube menjawab HTTP ${r.code}")
        r.body?.string().orEmpty()
    }

    /** The JSON array that follows `"captionTracks":` in the watch page (brackets matched). Pure; unit-tested. */
    fun tracksJson(page: String): String? {
        val start = page.indexOf("\"captionTracks\":").takeIf { it >= 0 }?.let { page.indexOf('[', it) } ?: return null
        var depth = 0
        var inStr = false
        var i = start
        while (i < page.length) {
            val c = page[i]
            if (inStr) {
                if (c == '\\') i++ else if (c == '"') inStr = false
            } else when (c) {
                '"' -> inStr = true
                '[' -> depth++
                ']' -> { depth--; if (depth == 0) return page.substring(start, i + 1) }
            }
            i++
        }
        return null
    }

    fun tracks(page: String): List<Track> = tracksJson(page)?.let { raw ->
        runCatching {
            Json.parseToJsonElement(raw).jsonArray.mapNotNull { e ->
                val o = e.jsonObject
                val url = o["baseUrl"]?.jsonPrimitive?.contentOrNull ?: return@mapNotNull null
                Track(o["languageCode"]?.jsonPrimitive?.contentOrNull.orEmpty(), url, o["kind"]?.jsonPrimitive?.contentOrNull == "asr")
            }
        }.getOrDefault(emptyList())
    }.orEmpty()

    /** The best track for the wanted languages: a written one before an automatic one, in the order given. Pure. */
    fun pick(tracks: List<Track>, langs: List<String>): Track? =
        langs.firstNotNullOfOrNull { l -> tracks.firstOrNull { it.lang == l && !it.auto } ?: tracks.firstOrNull { it.lang == l } } ?: tracks.firstOrNull()

    private fun field(page: String, name: String): String =
        Regex("\"videoDetails\":\\{[^{}]*?\"$name\":\"((?:[^\"\\\\]|\\\\.)*)\"").find(page)?.groupValues?.get(1)
            ?.let { runCatching { Json.parseToJsonElement("\"$it\"").jsonPrimitive.content }.getOrDefault(it) }.orEmpty()

    /**
     * The subtitles: the watch page's own track list first; YouTube now often answers that address with nothing (its subtitle requests
     * carry a token only its player makes), so then the official player itself is asked ([viaPlayer]).
     */
    suspend fun fetch(context: Context, server: String, video: String, langs: List<String>): JsonObject {
        if (!ID.matches(video)) throw PhoneOpException("id video tidak valid")
        val direct = runCatching { withContext(Dispatchers.IO) { fetchDirect(video, langs) } }
        direct.getOrNull()?.let { return it }
        val viaPlayer = runCatching { viaPlayer(context, server, video, langs) }
        viaPlayer.getOrNull()?.let { return it }
        throw PhoneOpException(viaPlayer.exceptionOrNull()?.message ?: direct.exceptionOrNull()?.message ?: "subtitle tidak bisa diambil")
    }

    /** The subtitle address the player asks for, with json3 as the format. Pure; unit-tested. */
    fun asJson3(url: String): String =
        if (Regex("[?&]fmt=").containsMatchIn(url)) url.replace(Regex("([?&])fmt=[^&]*"), "$1fmt=json3") else "$url&fmt=json3"

    /** The language of a subtitle request (`tlang` when translated, else `lang`). Pure. */
    fun langOf(url: String): String = (Regex("[?&]tlang=([^&]+)").find(url) ?: Regex("[?&]lang=([^&]+)").find(url))?.groupValues?.get(1).orEmpty()

    /**
     * JARVIS' own embed of the official YouTube player, in a WebView nobody sees, playing SILENTLY with subtitles on: the player requests
     * its subtitles (with its token) and that request's address is read — then the subtitle text is fetched once from it. Nothing else.
     */
    @SuppressLint("SetJavaScriptEnabled")
    private suspend fun viaPlayer(context: Context, server: String, video: String, langs: List<String>): JsonObject {
        if (server.isBlank()) throw PhoneOpException("alamat server belum diatur")
        val found = CompletableDeferred<String>()
        val web = withContext(Dispatchers.Main) {
            WebView(context.applicationContext).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.mediaPlaybackRequiresUserGesture = false
                webViewClient = object : WebViewClient() {
                    override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                        val u = request.url
                        if (u.host?.endsWith("youtube.com") == true && u.path?.contains("/api/timedtext") == true) found.complete(u.toString())
                        return null
                    }
                }
                measure(View.MeasureSpec.makeMeasureSpec(640, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(360, View.MeasureSpec.EXACTLY))
                layout(0, 0, 640, 360)
                loadUrl("${server.trimEnd('/')}/embed/youtube/$video?play=1&mute=1&cc=${langs.firstOrNull() ?: "id"}")
            }
        }
        try {
            val url = withTimeoutOrNull(30_000) { found.await() } ?: throw PhoneOpException("video ini tidak punya subtitle (pemutar YouTube tidak memuatnya)")
            val cookies = CookieManager.getInstance().getCookie("https://www.youtube.com").orEmpty()
            val json3 = withContext(Dispatchers.IO) {
                client.newCall(Request.Builder().url(asJson3(url)).header("User-Agent", web.settings.userAgentString)
                    .apply { if (cookies.isNotEmpty()) header("Cookie", cookies) }.build()).execute().use { r ->
                    if (!r.isSuccessful) throw PhoneOpException("YouTube menjawab HTTP ${r.code}")
                    r.body?.string().orEmpty()
                }
            }
            if (json3.isBlank()) throw PhoneOpException("subtitle kosong (YouTube menolak)")
            val meta = withContext(Dispatchers.IO) {
                runCatching { Json.parseToJsonElement(get("https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v=$video")).jsonObject }.getOrNull()
            }
            return buildJsonObject {
                put("json3", json3.take(MAX_CHARS))
                put("lang", langOf(url))
                put("title", meta?.get("title")?.jsonPrimitive?.contentOrNull.orEmpty())
                put("channel", meta?.get("author_name")?.jsonPrimitive?.contentOrNull.orEmpty())
            }
        } finally {
            withContext(Dispatchers.Main) { web.stopLoading(); web.destroy() }
        }
    }

    private fun fetchDirect(video: String, langs: List<String>): JsonObject {
        val page = get("https://www.youtube.com/watch?v=$video&hl=id")
        val t = pick(tracks(page), langs) ?: throw PhoneOpException("video ini tidak punya subtitle")
        val json3 = get(t.url + "&fmt=json3")
        if (json3.isBlank()) throw PhoneOpException("subtitle kosong (YouTube menolak)")
        return buildJsonObject {
            put("json3", json3.take(MAX_CHARS))
            put("lang", t.lang)
            put("title", field(page, "title"))
            put("channel", field(page, "author"))
            field(page, "lengthSeconds").toIntOrNull()?.let { put("duration", it) }
        }
    }
}
