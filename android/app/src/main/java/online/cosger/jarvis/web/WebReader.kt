package online.cosger.jarvis.web

import android.annotation.SuppressLint
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine

/**
 * ADR-087 (batch H): "visit the website directly" — some sites refuse the server (bot checks on a data-centre address), so the phone
 * opens the page itself, in a WebView nobody sees (the owner's screen is not touched), from its own connection, and sends back the
 * page's text and links. Only GET of https pages on the sites named for this visit; nothing is typed or submitted. Cookies are the
 * app's own (the owner may have signed in once in [WebLoginActivity]), so a dashboard he opened there can be read.
 */
object WebReader {
    private const val EXTRACT = """(function(){var a=[].slice.call(document.querySelectorAll('a[href]')).slice(0,400).map(function(x){return {t:(x.innerText||x.title||'').trim().slice(0,120),h:x.href}});
return JSON.stringify({title:document.title,url:location.href,text:(document.body?document.body.innerText:'').slice(0,60000),links:a});})()"""

    @SuppressLint("SetJavaScriptEnabled")
    suspend fun read(context: Context, url: String, domains: List<String>, waitMs: Long = 25_000): JsonObject {
        if (!WebRules.allowed(url, domains)) return buildJsonObject { put("error", "situs di luar izin kunjungan ini") }
        return withContext(Dispatchers.Main) {
            val web = WebView(context.applicationContext)
            try {
                CookieManager.getInstance().setAcceptCookie(true)
                CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
                web.settings.javaScriptEnabled = true
                web.settings.domStorageEnabled = true
                web.settings.loadsImagesAutomatically = false
                web.measure(View.MeasureSpec.makeMeasureSpec(1080, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(2340, View.MeasureSpec.EXACTLY))
                web.layout(0, 0, 1080, 2340)
                var loaded = false
                web.webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = !WebRules.allowed(request.url.toString(), domains)
                    override fun onPageFinished(view: WebView, u: String) { loaded = true }
                }
                web.loadUrl(url)
                val got = withTimeoutOrNull(waitMs) {
                    while (!loaded) delay(300)
                    var page = evaluate(web)
                    while (WebRules.challenged(page.s("title"), page.s("text"))) { delay(1_500); page = evaluate(web) }   // a bot check clears itself
                    delay(1_200)   // late content (schedules drawn by script)
                    evaluate(web)
                }
                got?.let { p -> buildJsonObject { p.forEach { (k, v) -> put(k, v) }; put("challenged", false) } }
                    ?: evaluate(web).let { p -> buildJsonObject { p.forEach { (k, v) -> put(k, v) }; put("challenged", WebRules.challenged(p.s("title"), p.s("text"))) } }
            } finally {
                CookieManager.getInstance().flush()
                Handler(Looper.getMainLooper()).post { web.stopLoading(); web.destroy() }
            }
        }
    }

    private fun JsonObject.s(k: String) = this[k]?.jsonPrimitive?.content.orEmpty()

    private suspend fun evaluate(web: WebView): JsonObject = suspendCoroutine { cont ->
        web.evaluateJavascript(EXTRACT) { raw ->
            val obj = runCatching { Json.parseToJsonElement(Json.parseToJsonElement(raw).jsonPrimitive.content).jsonObject }.getOrNull()
            cont.resume(obj ?: buildJsonObject { put("title", ""); put("text", ""); put("url", web.url ?: "") })
        }
    }
}
