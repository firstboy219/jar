package online.cosger.jarvis.phone

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import online.cosger.jarvis.MainActivity
import online.cosger.jarvis.net.ServerEvent

/** ADR-077: a JARVIS app run waits for approval — a notification that opens the app, where the admin password is asked. */
object ApprovalNotice {
    private const val CHANNEL = "jarvis_phone_approval"

    fun show(context: Context, a: ServerEvent.PhoneApproval) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Persetujuan operasi aplikasi", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, a.id.toInt(),
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setContentTitle("JARVIS minta izin membuka ${a.label}")
            .setContentText(a.goal)
            .setStyle(NotificationCompat.BigTextStyle().bigText("${a.goal}\n\nKetuk untuk memeriksa dan menyetujui dengan password admin."))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        runCatching { nm.notify(TAG, a.id.toInt(), n) }   // no notification permission: the dialog still shows when the app opens
    }

    fun cancel(context: Context, id: Long) {
        context.getSystemService(NotificationManager::class.java)?.cancel(TAG, id.toInt())
    }

    private const val TAG = "phone_approval"

    /** ADR-079: a plain notification (a project's pick is waiting, a run ended …). Ketuk opens the app, where the pick shows as a dialog. */
    fun notice(context: Context, id: Int, title: String, text: String, urgent: Boolean, route: String = "") {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        nm.createNotificationChannel(NotificationChannel(INFO_CHANNEL, "Proyek & pemberitahuan", NotificationManager.IMPORTANCE_DEFAULT))
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Persetujuan operasi aplikasi", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(context, id,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .apply { if (route.startsWith("#/")) putExtra(MainActivity.EXTRA_ROUTE, route) },   // ADR-087: the app opens that screen
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(context, if (urgent) CHANNEL else INFO_CHANNEL)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setPriority(if (urgent) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        runCatching { nm.notify(NOTICE_TAG, id, n) }
    }

    fun cancelNotice(context: Context, id: Int) {
        context.getSystemService(NotificationManager::class.java)?.cancel(NOTICE_TAG, id)
    }

    private const val INFO_CHANNEL = "jarvis_project_info"
    private const val NOTICE_TAG = "jarvis_notice"
}
