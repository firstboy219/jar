package online.cosger.jarvis.meeting

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
import online.cosger.jarvis.MainActivity
import online.cosger.jarvis.R

/** Keeps a meeting recording going with the screen off; Android requires the visible notification. */
class MeetingService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Rekaman rapat", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 2, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n: Notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_jarvis)
            .setContentTitle("JARVIS merekam rapat")
            .setContentText("Semua peserta sudah setuju direkam · ketuk untuk membuka")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        else startForeground(ID, n)
        return START_NOT_STICKY
    }

    companion object {
        private const val CHANNEL = "meeting"
        private const val ID = 9

        fun start(context: Context) = context.startForegroundService(Intent(context, MeetingService::class.java))
        fun stop(context: Context) = context.stopService(Intent(context, MeetingService::class.java))
    }
}
