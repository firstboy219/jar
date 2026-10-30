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
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView

/**
 * ADR-087 batch H/I: the owner's own hands on a website. Two uses:
 *  - sign in ONCE to a site JARVIS reads (a seller dashboard) — its cookies stay in the app;
 *  - a JARVIS web session that needs him (sign in, "not a robot", a code, the payment): the session's very page, with what JARVIS
 *    already filled in, is shown here; "Selesai" gives it back and JARVIS carries on, "Batal" stops that step.
 * JARVIS never types a password; here only he types.
 */
class WebLoginActivity : Activity() {
    private var web: WebView? = null
    private var session: String? = null
    private var handed = false

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = intent.getStringExtra(EXTRA_SESSION)
        val s = session?.let { WebSessions.get(it) }
        val url = intent.getStringExtra(EXTRA_URL).orEmpty()
        if (s == null && WebRules.host(url) == null) { finish(); return }
        val box = FrameLayout(this).apply { layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f) }
        val bar = LinearLayout(this).apply {
            setBackgroundColor(Color.parseColor("#0B0F14")); setPadding(24, 18, 24, 18)
            addView(TextView(context).apply {
                text = s?.reason?.ifBlank { null } ?: "Masuk sendiri — JARVIS tidak membaca kata sandimu"
                setTextColor(Color.parseColor("#C8D1DC")); textSize = 13f
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            if (s != null) addView(Button(context).apply { text = "Batal"; setOnClickListener { hand(false) } })
            addView(Button(context).apply { text = "Selesai"; setOnClickListener { hand(true) } })
        }
        setContentView(LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; addView(bar); addView(box) })
        if (s != null) {
            web = WebSessions.attach(s.id, this, box)?.web
        } else {
            web = WebView(this).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                webViewClient = WebViewClient()
            }.also { box.addView(it, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)) }
            CookieManager.getInstance().setAcceptCookie(true)
            CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)
            web?.loadUrl(url)
        }
    }

    private fun hand(done: Boolean) {
        session?.let { if (!handed) WebSessions.detach(it, done) }
        handed = true
        finish()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() { if (web?.canGoBack() == true) web?.goBack() else hand(false) }

    override fun onPause() { super.onPause(); CookieManager.getInstance().flush() }

    override fun onDestroy() {
        if (session != null) { if (!handed) WebSessions.detach(session!!, false) }   // the session's page lives on for JARVIS
        else web?.destroy()
        super.onDestroy()
    }

    companion object {
        private const val EXTRA_URL = "url"
        private const val EXTRA_SESSION = "session"
        fun open(context: Context, url: String) {
            if (WebRules.host(url) == null) return
            context.startActivity(Intent(context, WebLoginActivity::class.java).putExtra(EXTRA_URL, url).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
        fun openSession(context: Context, id: String) {
            context.startActivity(Intent(context, WebLoginActivity::class.java).putExtra(EXTRA_SESSION, id).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }
}
