package online.cosger.jarvis.media

import android.content.ComponentName
import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.annotation.OptIn
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.okhttp.OkHttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.OkHttpClient

/**
 * The phone's one music player (ADR-087 fix, owner 2026-10-30: "musik hanya bisa muncul suaranya saat di canvas"): it used to live inside
 * the talk sheet's music panel, so the sound stopped whenever another screen (the app v2) was in front. Now it belongs to the process and
 * a [MusicService] media session: it plays on every screen and with the screen off, with the lock-screen / notification controls, and
 * every panel (the talk sheet, the app's mini player) only steers it.
 */
@OptIn(UnstableApi::class)
object MusicPlayer {
    data class Track(val id: String, val url: String, val title: String, val artist: String, val cover: String = "",
                     val license: String = "", val sourceUrl: String = "")

    private val _track = MutableStateFlow<Track?>(null)
    val track: StateFlow<Track?> = _track.asStateFlow()
    private val _playing = MutableStateFlow(false)
    val playing: StateFlow<Boolean> = _playing.asStateFlow()

    /** JARVIS' own files (/api/v1/media/…) need the device token; anything else goes without it. */
    @Volatile private var origin = ""
    @Volatile private var auth: Map<String, String> = emptyMap()
    /** The track ended by itself (a playlist moves on: the server is told). */
    @Volatile var onEnded: ((String) -> Unit)? = null

    private var player: ExoPlayer? = null
    private var controller: MediaController? = null
    // the app page asks from the WebView's own thread, and ExoPlayer may only be touched on the main one: a snapshot kept fresh here
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var snapPos = 0L
    @Volatile private var snapDur = 0L
    private val ticker = object : Runnable {
        override fun run() {
            player?.let { snapPos = it.currentPosition; snapDur = it.duration.coerceAtLeast(0) }
            main.removeCallbacks(this)
            if (_playing.value) main.postDelayed(this, 500)
        }
    }

    fun player(context: Context): ExoPlayer = player ?: run {
        val http = OkHttpClient.Builder().addInterceptor { chain ->
            val req = chain.request()
            val own = origin.isNotEmpty() && req.url.toString().startsWith(origin)
            chain.proceed(if (own) req.newBuilder().apply { auth.forEach { (k, v) -> header(k, v) } }.build() else req)
        }.build()
        ExoPlayer.Builder(context.applicationContext)
            .setMediaSourceFactory(DefaultMediaSourceFactory(OkHttpDataSource.Factory(http)))
            .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(), true)
            .setHandleAudioBecomingNoisy(true)   // headphones out: pause, as every music app does
            .build().also { p ->
                p.addListener(object : Player.Listener {
                    override fun onIsPlayingChanged(isPlaying: Boolean) { _playing.value = isPlaying; ticker.run() }
                    override fun onPositionDiscontinuity(old: Player.PositionInfo, new: Player.PositionInfo, reason: Int) { ticker.run() }
                    override fun onPlaybackStateChanged(state: Int) {
                        if (state == Player.STATE_ENDED) _track.value?.let { t -> onEnded?.invoke(t.id) }
                    }
                })
                player = p
            }
    }

    /** Plays [t] (a JARVIS path or an https URL) through the media session; the same track again only resumes. */
    fun play(context: Context, t: Track, serverOrigin: String, headers: Map<String, String>, autoplay: Boolean = true) {
        origin = serverOrigin.trimEnd('/'); auth = headers
        val p = player(context)
        connect(context)
        if (_track.value?.id == t.id && _track.value?.url == t.url && p.mediaItemCount > 0) {
            if (autoplay) p.play()
            return
        }
        _track.value = t
        val url = if (t.url.startsWith("/")) origin + t.url else t.url
        val meta = MediaMetadata.Builder().setTitle(t.title.ifBlank { "JARVIS" }).setArtist(t.artist)
            .apply { if (t.cover.startsWith("https://")) setArtworkUri(android.net.Uri.parse(t.cover)) }.build()
        p.setMediaItem(MediaItem.Builder().setUri(url).setMediaId(t.id).setMediaMetadata(meta).build())
        p.prepare()
        p.playWhenReady = autoplay
    }

    /** The media session service is started (and kept while playing) by a controller bound to it. */
    private fun connect(context: Context) {
        if (controller != null) return
        val token = SessionToken(context.applicationContext, ComponentName(context.applicationContext, MusicService::class.java))
        val f = MediaController.Builder(context.applicationContext, token).buildAsync()
        f.addListener({ controller = runCatching { f.get() }.getOrNull() }, { it.run() })
    }

    fun toggle() { player?.let { if (it.isPlaying) it.pause() else it.play() } }
    fun pause() { player?.pause() }
    fun resume() { player?.play() }
    fun restart() { player?.let { it.seekTo(0); it.play() } }
    fun seekFraction(f: Float) { player?.let { if (it.duration > 0) it.seekTo((f.coerceIn(0f, 1f) * it.duration).toLong()) } }
    fun seekTo(ms: Long) { player?.seekTo(ms.coerceAtLeast(0)) }
    /** Quieter while the owner speaks, so JARVIS and he can hear each other. */
    fun duck(on: Boolean) { player?.volume = if (on) 0.2f else 1f }

    /** (position, duration) in ms; duration 0 while unknown. */
    fun position(): Pair<Long, Long> = player?.let { it.currentPosition to it.duration.coerceAtLeast(0) } ?: (0L to 0L)

    /** Stops and forgets the track (the panel closed, "Tutup" in the app). */
    fun stop(id: String? = null) {
        if (id != null && _track.value?.id != id) return
        player?.stop(); player?.clearMediaItems()
        _track.value = null; _playing.value = false; snapPos = 0; snapDur = 0
    }

    /** Called by the service when it goes away. */
    internal fun release() {
        controller?.release(); controller = null
        player?.release(); player = null
        _track.value = null; _playing.value = false
    }

    /** What the app's mini player shows (JSON for the WebView bridge). Pure-ish: reads state only. */
    fun stateJson(): String {
        val t = _track.value ?: return "{}"
        val pos = snapPos
        val dur = snapDur
        fun q(s: String) = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
        return "{\"id\":${q(t.id)},\"title\":${q(t.title)},\"artist\":${q(t.artist)},\"cover\":${q(t.cover)},\"playing\":${_playing.value},\"pos\":$pos,\"dur\":$dur}"
    }
}
