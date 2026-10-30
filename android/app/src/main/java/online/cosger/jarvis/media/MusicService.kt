package online.cosger.jarvis.media

import android.app.PendingIntent
import android.content.Intent
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService
import online.cosger.jarvis.MainActivity

/** The media session around [MusicPlayer]: the system's media notification and lock-screen controls, and playback kept alive off screen. */
class MusicService : MediaSessionService() {
    private var session: MediaSession? = null

    override fun onCreate() {
        super.onCreate()
        val open = PendingIntent.getActivity(this, 7, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        session = MediaSession.Builder(this, MusicPlayer.player(this)).setSessionActivity(open).build().also { addSession(it) }
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = session

    override fun onTaskRemoved(rootIntent: Intent?) {
        if (session?.player?.isPlaying != true) stopSelf()   // swiped away while silent: nothing to keep
    }

    override fun onDestroy() {
        session?.release(); session = null
        MusicPlayer.release()
        super.onDestroy()
    }
}
