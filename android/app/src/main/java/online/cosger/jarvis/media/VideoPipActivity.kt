package online.cosger.jarvis.media

import android.annotation.SuppressLint
import android.app.Activity
import android.app.PictureInPictureParams
import android.content.Context
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Color
import android.os.Bundle
import android.util.Rational
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import online.cosger.jarvis.JarvisApp

/**
 * ADR-087 phase J: a YouTube video in a small window that floats over other apps (picture-in-picture). The official embedded player stays
 * visible the whole time (YouTube's terms forbid background playback); closing the small window ends it. Its own task, so the rest of
 * JARVIS is not shrunk with it.
 */
class VideoPipActivity : Activity() {
    private var web: WebView? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val id = intent.getStringExtra(EXTRA_ID).orEmpty()
        val server = (application as JarvisApp).settings.state.value.serverUrl.trimEnd('/')
        if (!Regex("[A-Za-z0-9_-]{11}").matches(id) || server.isBlank()) { finish(); return }
        val start = intent.getIntExtra(EXTRA_START, 0).coerceIn(0, 86_400)
        web = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null)
            setBackgroundColor(Color.BLACK)
            webChromeClient = object : WebChromeClient() {
                override fun onReceivedTitle(view: WebView, title: String?) { if (title == "ended") finish() }
            }
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = request.isForMainFrame   // stay on the player
            }
            loadUrl("$server/embed/youtube/$id?play=1&start=$start")
        }
        setContentView(web)
        enterPip()
    }

    private fun enterPip() {
        runCatching { enterPictureInPictureMode(PictureInPictureParams.Builder().setAspectRatio(Rational(16, 9)).build()) }
    }

    override fun onUserLeaveHint() { super.onUserLeaveHint(); enterPip() }

    override fun onPictureInPictureModeChanged(isInPictureInPictureMode: Boolean, newConfig: Configuration) {
        super.onPictureInPictureModeChanged(isInPictureInPictureMode, newConfig)
    }

    override fun onStop() {
        super.onStop()
        if (!isInPictureInPictureMode) finish()   // the small window was closed: the video ends with it
    }

    override fun onDestroy() { web?.destroy(); web = null; super.onDestroy() }

    companion object {
        private const val EXTRA_ID = "id"
        private const val EXTRA_START = "start"
        fun open(context: Context, id: String, start: Int) {
            context.startActivity(Intent(context, VideoPipActivity::class.java).putExtra(EXTRA_ID, id).putExtra(EXTRA_START, start)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
        }
    }
}
