package online.cosger.jarvis.notify

import android.app.Notification
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.service.notification.StatusBarNotification

/**
 * Recent chat threads seen in messaging notifications (WhatsApp & co., MessagingStyle keeps ≤ 25
 * messages), with their "Reply" action. Two uses:
 *  - the thread text helps JARVIS draft a reply to what the owner is showing on screen;
 *  - "Kirim lewat Balas notifikasi": the OWNER taps send, and the text goes through the app's own
 *    reply action — JARVIS itself never sends anything.
 * Kept in memory only, never stored or uploaded except as context when the owner asks for a draft.
 */
object Conversations {
    data class Thread(val app: String, val pkg: String, val title: String, val messages: List<String>,
                      val reply: Notification.Action?, val at: Long)

    private val threads = LinkedHashMap<String, Thread>()
    private const val MAX = 20
    val MESSAGING = setOf("com.whatsapp", "com.whatsapp.w4b", "org.telegram.messenger", "com.google.android.gm",
                          "com.google.android.apps.messaging", "jp.naver.line.android")

    @Synchronized
    fun capture(sbn: StatusBarNotification, appLabel: String) {
        if (sbn.packageName !in MESSAGING) return
        val n = sbn.notification
        val extras = n.extras
        val title = (extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)
            ?: extras.getCharSequence(Notification.EXTRA_TITLE))?.toString()?.trim().orEmpty()
        if (title.isEmpty()) return
        val messages = Notification.MessagingStyle.Message.getMessagesFromBundleArray(
            extras.getParcelableArray(Notification.EXTRA_MESSAGES) as Array<android.os.Parcelable>?
        ).map { "${it.senderPerson?.name ?: it.sender ?: title}: ${it.text}" }
            .ifEmpty { listOfNotNull(extras.getCharSequence(Notification.EXTRA_TEXT)?.let { "$title: $it" }) }
        val reply = n.actions?.firstOrNull { a -> a.remoteInputs?.any { it.allowFreeFormInput } == true }
        val key = "${sbn.packageName}|$title"
        val previous = threads.remove(key)
        threads[key] = Thread(appLabel, sbn.packageName, title,
            (previous?.messages.orEmpty() + messages).distinct().takeLast(25), reply ?: previous?.reply, sbn.postTime)
        while (threads.size > MAX) threads.remove(threads.keys.first())
    }

    @Synchronized
    fun latest(): Thread? = threads.values.maxByOrNull { it.at }

    /** The thread whose title best matches [name] (from the draft), else the most recent one. */
    @Synchronized
    fun find(name: String): Thread? {
        val n = name.trim().lowercase()
        return threads.values.filter { n.isNotEmpty() && (it.title.lowercase().contains(n) || n.contains(it.title.lowercase())) }
            .maxByOrNull { it.at } ?: latest()
    }

    fun text(t: Thread): String = "Percakapan ${t.app} dengan ${t.title}:\n" + t.messages.joinToString("\n")

    /** The owner tapped "Kirim": deliver [message] through the app's own notification reply action. */
    fun reply(context: Context, thread: Thread, message: String): Boolean {
        val action = thread.reply ?: return false
        val inputs = action.remoteInputs ?: return false
        val intent = Intent()
        val results = Bundle().apply { inputs.forEach { putCharSequence(it.resultKey, message) } }
        RemoteInput.addResultsToIntent(inputs, intent, results)
        return runCatching { action.actionIntent.send(context, 0, intent); true }
            .recover { e -> if (e is PendingIntent.CanceledException) false else throw e }.getOrDefault(false)
    }
}
