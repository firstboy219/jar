package online.cosger.jarvis.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import online.cosger.jarvis.BuildConfig
import java.util.UUID

data class AppSettings(
    val serverUrl: String = BuildConfig.DEFAULT_SERVER,
    val deviceToken: String = "",
    val speakReplies: Boolean = true,
    val shareLocation: Boolean = true,
    val readNotifications: Boolean = false,
    val useCalendar: Boolean = false,
    /** Listen for "Hey Jarvis" while muted (on the phone only). */
    val wakeWord: Boolean = false,
    /** Wake word sensitivity: 0.5 normal, 0.25 for Indonesian-accented pronunciation. */
    val wakeSensitive: Boolean = false,
    /** Talking over JARVIS stops it (best with a headset; phone speakers can echo). */
    val bargeIn: Boolean = false,
    /** "Tunda" on an app update: don't ask again for this version code until this time. */
    val updateSnoozeCode: Int = 0,
    val updateSnoozeUntil: Long = 0,
    val sessionId: String = UUID.randomUUID().toString(),
) {
    val isConfigured: Boolean get() = deviceToken.startsWith("jdv_")
}

/** Device token + preferences, encrypted at rest with an Android Keystore master key. */
class SecureSettings(context: Context) {
    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context,
        "jarvis_secure",
        MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build(),
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    private val _state = MutableStateFlow(load())
    val state: StateFlow<AppSettings> = _state

    private fun load(): AppSettings {
        val defaults = AppSettings()
        val session = prefs.getString("session_id", null) ?: defaults.sessionId.also {
            prefs.edit().putString("session_id", it).apply()
        }
        return AppSettings(
            serverUrl = prefs.getString("server_url", null) ?: defaults.serverUrl,
            deviceToken = prefs.getString("device_token", null) ?: "",
            speakReplies = prefs.getBoolean("speak_replies", true),
            shareLocation = prefs.getBoolean("share_location", true),
            readNotifications = prefs.getBoolean("read_notifications", false),
            useCalendar = prefs.getBoolean("use_calendar", false),
            wakeWord = prefs.getBoolean("wake_word", false),
            wakeSensitive = prefs.getBoolean("wake_sensitive", false),
            bargeIn = prefs.getBoolean("barge_in", false),
            updateSnoozeCode = prefs.getInt("update_snooze_code", 0),
            updateSnoozeUntil = prefs.getLong("update_snooze_until", 0),
            sessionId = session,
        )
    }

    fun update(transform: (AppSettings) -> AppSettings) {
        val next = transform(_state.value)
        prefs.edit()
            .putString("server_url", next.serverUrl.trim().trimEnd('/'))
            .putString("device_token", next.deviceToken.trim())
            .putBoolean("speak_replies", next.speakReplies)
            .putBoolean("share_location", next.shareLocation)
            .putBoolean("read_notifications", next.readNotifications)
            .putBoolean("use_calendar", next.useCalendar)
            .putBoolean("wake_word", next.wakeWord)
            .putBoolean("wake_sensitive", next.wakeSensitive)
            .putBoolean("barge_in", next.bargeIn)
            .putInt("update_snooze_code", next.updateSnoozeCode)
            .putLong("update_snooze_until", next.updateSnoozeUntil)
            .putString("session_id", next.sessionId)
            .apply()
        _state.value = next.copy(serverUrl = next.serverUrl.trim().trimEnd('/'), deviceToken = next.deviceToken.trim())
    }

    fun newConversation() = update { it.copy(sessionId = UUID.randomUUID().toString()) }
}
