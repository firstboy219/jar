package online.cosger.jarvis.notify

import android.app.Notification
import android.content.pm.PackageManager
import android.os.Build
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import online.cosger.jarvis.JarvisApp

/**
 * Lets JARVIS hear about new notifications without being asked (owner grants "Akses notifikasi" in
 * Android settings, and enables "Baca notifikasi" in the app). Forwards filtered notifications to
 * jarvis-core, which decides what is worth saying.
 */
class JarvisNotificationListener : NotificationListenerService() {
    private val deduper = NotificationFilter.Deduper()

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val engine = (application as JarvisApp).engine
        if (!engine.settings.value.readNotifications) return
        runCatching { Conversations.capture(sbn, appLabel(sbn.packageName)) }
        val n = sbn.notification
        val extras = n.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: extras.getCharSequence(Notification.EXTRA_TEXT))
            ?.toString().orEmpty()
        val candidate = NotificationFilter.Candidate(
            packageName = sbn.packageName, ownPackage = packageName,
            ongoing = (n.flags and Notification.FLAG_ONGOING_EVENT) != 0 || (n.flags and Notification.FLAG_FOREGROUND_SERVICE) != 0,
            groupSummary = (n.flags and Notification.FLAG_GROUP_SUMMARY) != 0,
            title = title, text = text,
        )
        if (!NotificationFilter.shouldForward(candidate)) return
        if (!deduper.firstTime(sbn.key, title, text, System.currentTimeMillis())) return
        val app = appLabel(sbn.packageName)
        engine.forwardNotification(app, sbn.packageName, title.take(300), NotificationFilter.safeText(title, text), sbn.postTime)
    }

    private fun appLabel(pkg: String): String = runCatching {
        val info = if (Build.VERSION.SDK_INT >= 33) {
            packageManager.getApplicationInfo(pkg, PackageManager.ApplicationInfoFlags.of(0))
        } else {
            @Suppress("DEPRECATION") packageManager.getApplicationInfo(pkg, 0)
        }
        packageManager.getApplicationLabel(info).toString()
    }.getOrDefault(pkg)
}
