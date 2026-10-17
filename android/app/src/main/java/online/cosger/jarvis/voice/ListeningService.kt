package online.cosger.jarvis.voice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import online.cosger.jarvis.JarvisApp
import online.cosger.jarvis.MainActivity
import online.cosger.jarvis.R

/**
 * Keeps the app (and the open mic) alive while JARVIS is unmuted, including with the screen off.
 * Android requires a visible notification for this; it carries a "Matikan mic" action.
 */
class ListeningService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_MUTE) {
            (application as JarvisApp).engine.mute()
            stopSelf()
            return START_NOT_STICKY
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "JARVIS mendengarkan", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Tampil selama mikrofon JARVIS aktif"
                setShowBadge(false)
            },
        )
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val mute = PendingIntent.getService(
            this, 1, Intent(this, ListeningService::class.java).setAction(ACTION_MUTE), PendingIntent.FLAG_IMMUTABLE,
        )
        val n: Notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_jarvis)
            .setContentTitle("JARVIS mendengarkan")
            .setContentText("Mic aktif — ketuk untuk membuka")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Matikan mic", mute).build())
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(ID, n)
        }
        return START_NOT_STICKY
    }

    companion object {
        private const val CHANNEL = "listening"
        private const val ID = 7
        private const val ACTION_MUTE = "online.cosger.jarvis.MUTE"

        fun start(context: Context) {
            context.startForegroundService(Intent(context, ListeningService::class.java))
        }
    }
}
