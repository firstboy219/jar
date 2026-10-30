package online.cosger.jarvis.guide

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import online.cosger.jarvis.MainActivity

/**
 * ADR-087 (Bimbing layar): the next step JARVIS says while the owner shares his screen — a heads-up notification over whatever app he is
 * in (no extra permission), updated with each step and spoken too; tapping it opens the guidance screen.
 */
object GuideNotice {
    private const val CHANNEL = "jarvis_guide"
    private const val ID = 4030

    fun show(context: Context, step: Int, text: String, target: String, done: Boolean, where: String = "", total: Int = 0) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Bimbingan layar", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Langkah berikutnya saat JARVIS membimbing"
            setSound(null, null)
        })
        val open = PendingIntent.getActivity(context, ID, Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra(MainActivity.EXTRA_ROUTE, "#/bimbing"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val title = if (done) "Selesai ✓" else if (step > 0) ("Langkah $step" + if (total > step) " dari ±$total" else "") else "JARVIS membimbing"
        val n = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_help)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(if (target.isNotBlank()) "$text\n→ \"$target\"" + (if (where.isNotBlank()) " ($where)" else "") else text))
            .setOngoing(!done)
            .setAutoCancel(done)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_NAVIGATION)
            .setContentIntent(open)
            .build()
        runCatching { nm.notify(ID, n) }
    }

    fun clear(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ID)
    }

    /** The screen's text as compared between two looks (spacing and case do not count). Pure; unit-tested. */
    fun key(text: String): String = text.lowercase().split(Regex("\\s+")).filter { it.isNotBlank() }.joinToString(" ")
}
