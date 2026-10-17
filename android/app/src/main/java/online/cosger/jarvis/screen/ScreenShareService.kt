package online.cosger.jarvis.screen

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import online.cosger.jarvis.JarvisApp
import online.cosger.jarvis.MainActivity
import online.cosger.jarvis.R

/** Foreground service Android requires while the screen is being captured; shows a "Berhenti" action. */
class ScreenShareService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val capture = (application as JarvisApp).engine.screen
        if (intent?.action == ACTION_STOP) {
            capture.detach()
            stopSelf()
            return START_NOT_STICKY
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Berbagi layar", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getService(this, 2, Intent(this, ScreenShareService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE)
        val open = PendingIntent.getActivity(this, 3, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n: Notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_jarvis)
            .setContentTitle("JARVIS bisa melihat layarmu")
            .setContentText("Layar dikirim hanya saat kamu bicara")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Berhenti berbagi", stop).build())
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(ID, n)
        }
        // The projection may only be created after the foreground service is running.
        val code = intent?.getIntExtra(EXTRA_CODE, Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data: Intent? = if (Build.VERSION.SDK_INT >= 33) intent?.getParcelableExtra(EXTRA_DATA, Intent::class.java)
            else @Suppress("DEPRECATION") intent?.getParcelableExtra(EXTRA_DATA)
        val mpm = getSystemService(MediaProjectionManager::class.java)
        val projection = if (code == Activity.RESULT_OK && data != null) mpm.getMediaProjection(code, data) else null
        if (projection == null) {
            stopSelf()
            return START_NOT_STICKY
        }
        capture.attach(projection)
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        (application as JarvisApp).engine.screen.detach()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "screen_share"
        private const val ID = 8
        private const val ACTION_STOP = "online.cosger.jarvis.STOP_SHARE"
        private const val EXTRA_CODE = "code"
        private const val EXTRA_DATA = "data"

        fun start(context: Context, resultCode: Int, data: Intent) {
            context.startForegroundService(
                Intent(context, ScreenShareService::class.java).putExtra(EXTRA_CODE, resultCode).putExtra(EXTRA_DATA, data),
            )
        }

        fun stop(context: Context) = context.stopService(Intent(context, ScreenShareService::class.java))
    }
}
