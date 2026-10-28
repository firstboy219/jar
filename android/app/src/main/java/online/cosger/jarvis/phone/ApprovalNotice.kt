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
}
