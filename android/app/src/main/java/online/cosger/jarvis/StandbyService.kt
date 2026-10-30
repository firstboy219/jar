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
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * ADR-086: "JARVIS siaga" — keeps the app's link to the server alive while it is in the background (Android otherwise freezes a
 * backgrounded app within minutes). Without it, reports wait, the admin-password approval and the project's pick never reach the phone,
 * and a Gojek run fails with "HP tidak tersambung". A quiet, low notification; its "Matikan" switches it off (and it stays off).
 */
class StandbyService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var reporter: Job? = null
    private val http by lazy { OkHttpClient() }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    /**
     * ADR-087: while the owner shares his location (the app's setting, opt-in), tell the server where the phone is every few minutes, so
     * JARVIS learns rumah/kantor and knows when he arrives or leaves (the "sampai kantor" / "sampai rumah" habits). Nothing is sent otherwise.
     */
    private fun startReporting() {
        if (reporter?.isActive == true) return
        reporter = scope.launch {
            val app = application as JarvisApp
            while (isActive) {
                val s = app.settings.state.value
                if (s.isConfigured && s.shareLocation) {
                    val loc = runCatching { app.location.current(timeoutMs = 15_000) }.getOrNull()
                    if (loc != null) runCatching {
                        val body = org.json.JSONObject().put("lat", loc.lat).put("lon", loc.lon).put("age_s", loc.ageSeconds.coerceIn(0, 86_400))
                        loc.accuracyM?.let { body.put("accuracy_m", it.coerceIn(0.0, 100_000.0)) }
                        val req = Request.Builder().url(s.serverUrl.trimEnd('/') + "/api/v1/app/location")
                            .header("Authorization", "Bearer ${s.deviceToken}")
                            .post(body.toString().toRequestBody("application/json".toMediaType())).build()
                        http.newCall(req).execute().close()
                    }
                }
                delay(REPORT_EVERY_MS)
            }
        }
    }

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
        // the location type only when the owner allowed location (Android refuses the type otherwise): the trail of places (ADR-087)
        val where = if ((application as JarvisApp).location.hasPermission() && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0
        when {
            Build.VERSION.SDK_INT >= 34 -> startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE or where)
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q -> startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or where)
            else -> startForeground(ID, n)
        }
        startReporting()
        return START_STICKY
    }

    companion object {
        private const val CHANNEL = "standby"
        private const val ID = 9
        private const val ACTION_OFF = "online.cosger.jarvis.STANDBY_OFF"
        private const val PREFS = "jarvis_standby"
        private const val REPORT_EVERY_MS = 5 * 60 * 1000L

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
