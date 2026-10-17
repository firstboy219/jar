package online.cosger.jarvis.notify

/**
 * Decides which phone notifications are forwarded to JARVIS, and strips one-time codes on the phone
 * itself (the server redacts again; codes never leave the phone in the first place).
 */
object NotificationFilter {
    /** System/noisy packages that never carry something worth saying. */
    private val IGNORED = setOf(
        "android", "com.android.systemui", "com.android.vending", "com.android.providers.downloads",
        "com.google.android.gms", "com.transsion.phonemaster", "com.android.settings",
    )
    private val OTP = Regex(
        "\\b(otp|kode (verifikasi|otp|keamanan|rahasia)|verification code|one[- ]time|pin)\\b|\\b\\d{4,8}\\b.*\\b(kode|code)\\b|\\b(kode|code)\\b.*\\b\\d{4,8}\\b",
        RegexOption.IGNORE_CASE,
    )

    data class Candidate(
        val packageName: String, val ownPackage: String, val ongoing: Boolean, val groupSummary: Boolean,
        val title: String, val text: String,
    )

    fun shouldForward(c: Candidate): Boolean =
        c.packageName != c.ownPackage && c.packageName !in IGNORED && !c.ongoing && !c.groupSummary &&
            (c.title.isNotBlank() || c.text.isNotBlank())

    /** Text safe to send: one-time codes are replaced by a note. */
    fun safeText(title: String, text: String): String =
        if (OTP.containsMatchIn("$title $text")) "(kode/OTP disembunyikan di HP)" else text.take(2000)

    /** Same notification re-posted (updates, re-alerts) within the window is sent once. */
    class Deduper(private val windowMs: Long = 10 * 60_000L) {
        private val seen = LinkedHashMap<Int, Long>()
        fun firstTime(key: String, title: String, text: String, nowMs: Long): Boolean {
            seen.entries.removeAll { nowMs - it.value > windowMs }
            val h = "$key|$title|$text".hashCode()
            if (seen.containsKey(h)) return false
            seen[h] = nowMs
            return true
        }
    }
}
