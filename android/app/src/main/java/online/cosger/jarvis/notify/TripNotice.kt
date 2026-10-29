package online.cosger.jarvis.notify

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import online.cosger.jarvis.MainActivity

/**
 * ADR-087 (mockup "Di jalan"): the trip to work or home as one quiet, ongoing notification — on the lock screen too — with the next leg
 * and the arrival time; it updates as JARVIS reminds, orders the ride or replans, and goes away when the owner arrives.
 */
object TripNotice {
    private const val CHANNEL = "jarvis_trip"
    private const val ID = 4020

    fun show(context: Context, title: String, text: String, route: String) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Perjalanan", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Langkah berikutnya perjalanan ke kantor/rumah"
            lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
        })
        val open = PendingIntent.getActivity(context, ID, Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_ROUTE, route.ifBlank { "#/perjalanan" }),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_directions)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setCategory(NotificationCompat.CATEGORY_NAVIGATION)
            .setContentIntent(open)
            .build()
        runCatching { nm.notify(ID, n) }
    }

    fun clear(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ID)
    }
}
