package online.cosger.jarvis

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

/**
 * ADR-086: "JARVIS siaga" — keeps the app's link to the server alive while it is in the background (Android otherwise freezes a
 * backgrounded app within minutes). Without it, reports wait, the admin-password approval and the project's pick never reach the phone,
 * and a Gojek run fails with "HP tidak tersambung". A quiet, low notification; its "Matikan" switches it off (and it stays off).
 */
class StandbyService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_OFF) {
            setEnabled(this, false)
            stopSelf()
            return START_NOT_STICKY
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "JARVIS siaga", NotificationManager.IMPORTANCE_MIN).apply {
            description = "Menjaga JARVIS tetap tersambung saat aplikasi di latar belakang"
            setShowBadge(false)
        })
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val off = PendingIntent.getService(this, 2, Intent(this, StandbyService::class.java).setAction(ACTION_OFF), PendingIntent.FLAG_IMMUTABLE)
        val n: Notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_jarvis)
            .setContentTitle("JARVIS siaga")
            .setContentText("Tersambung — laporan, persetujuan, dan operasi aplikasi bisa sampai kapan saja")
            .setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "Matikan", off).build())
            .setOngoing(true)
            .build()
        when {
            Build.VERSION.SDK_INT >= 34 -> startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q -> startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
            else -> startForeground(ID, n)
        }
        return START_STICKY
    }

    companion object {
        private const val CHANNEL = "standby"
        private const val ID = 9
        private const val ACTION_OFF = "online.cosger.jarvis.STANDBY_OFF"
        private const val PREFS = "jarvis_standby"

        fun enabled(context: Context): Boolean = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("on", true)

        fun setEnabled(context: Context, on: Boolean) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("on", on).apply()
        }

        /** From the foreground only (Android refuses a foreground service started from the background). */
        fun startIfWanted(context: Context) {
            if (enabled(context)) runCatching { context.startForegroundService(Intent(context, StandbyService::class.java)) }
        }
    }
}
