package online.cosger.jarvis.web

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * ADR-087 (batch H): a site JARVIS reads from the web (a seller dashboard with no API, a cinema account) is signed into ONCE, here, by
 * the owner himself — JARVIS never types a password. The cookies stay in the app, so [WebReader] can read those pages later without
 * touching his screen. "Selesai" closes it.
 */
class WebLoginActivity : Activity() {
    private lateinit var web: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val url = intent.getStringExtra(EXTRA_URL).orEmpty()
        if (WebRules.host(url) == null) { finish(); return }
        val bar = LinearLayout(this).apply {
            setBackgroundColor(Color.parseColor("#0B0F14")); setPadding(24, 18, 24, 18)
            addView(TextView(context).apply {
                text = "Masuk sendiri — JARVIS tidak membaca kata sandimu"; setTextColor(Color.parseColor("#C8D1DC")); textSize = 13f
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            addView(Button(context).apply { text = "Selesai"; setOnClickListener { finish() } })
        }
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            webViewClient = WebViewClient()
            layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
        setContentView(LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; addView(bar); addView(web) })
        web.loadUrl(url)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() { if (web.canGoBack()) web.goBack() else super.onBackPressed() }

    override fun onPause() { super.onPause(); CookieManager.getInstance().flush() }

    override fun onDestroy() { if (::web.isInitialized) web.destroy(); super.onDestroy() }

    companion object {
        private const val EXTRA_URL = "url"
        fun open(context: Context, url: String) {
            if (WebRules.host(url) == null) return
            context.startActivity(Intent(context, WebLoginActivity::class.java).putExtra(EXTRA_URL, url).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
}
