package online.cosger.jarvis.update

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import online.cosger.jarvis.BuildConfig
import online.cosger.jarvis.data.SecureSettings
import online.cosger.jarvis.net.ConsoleApi
import online.cosger.jarvis.ui.stage.d
import online.cosger.jarvis.ui.stage.i
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.openFile
import online.cosger.jarvis.ui.stage.s
import java.io.File
import java.security.MessageDigest

/** A newer APK the owner may install now or postpone. */
data class UpdateOffer(val version: String, val code: Int, val file: String, val sizeMb: Double, val notes: String, val sha256: String)

/**
 * Checks the server for a newer JARVIS APK (on connect and every few hours) and offers it:
 * "Update sekarang" downloads it, verifies its SHA-256 and opens Android's installer; "Tunda" hides the
 * offer for that version for a day.
 */
class AppUpdater(private val context: Context, private val api: ConsoleApi, private val settings: SecureSettings) {
    private val _offer = MutableStateFlow<UpdateOffer?>(null)
    val offer: StateFlow<UpdateOffer?> = _offer.asStateFlow()
    private val _downloading = MutableStateFlow(false)
    val downloading: StateFlow<Boolean> = _downloading.asStateFlow()

    suspend fun check(installedCode: Int = BuildConfig.VERSION_CODE, now: Long = System.currentTimeMillis()) {
        val latest = runCatching { api.get("/api/v1/app/latest").obj()["latest"].obj() }.getOrNull() ?: return
        val code = latest.i("code") ?: return
        val s = settings.state.value
        val snoozed = s.updateSnoozeCode == code && now < s.updateSnoozeUntil
        _offer.value = if (shouldOffer(code, installedCode, snoozed)) UpdateOffer(latest.s("version"), code, latest.s("file"),
            (latest.d("size") ?: 0.0) / 1e6, latest.s("notes"), latest.s("sha256")) else null
    }

    fun postpone(hours: Int = 24) {
        val o = _offer.value ?: return
        settings.update { it.copy(updateSnoozeCode = o.code, updateSnoozeUntil = System.currentTimeMillis() + hours * 3_600_000L) }
        _offer.value = null
    }

    /** Download, check integrity, hand to the Android installer. Returns an error message or null. */
    suspend fun install(): String? {
        val o = _offer.value ?: return null
        if (!context.packageManager.canRequestPackageInstalls()) return "PERMISSION"
        _downloading.value = true
        try {
            val file = api.download("/api/v1/app/releases/${o.file}", File(context.cacheDir, "docs/${o.file}"))
            if (o.sha256.isNotBlank() && sha256(file) != o.sha256) {
                file.delete()
                return "File unduhan rusak (checksum tidak cocok) — coba lagi."
            }
            openFile(context, file, "view")
            _offer.value = null
            return null
        } catch (e: Exception) {
            return "Unduhan gagal: ${e.message}"
        } finally {
            _downloading.value = false
        }
    }

    companion object {
        fun shouldOffer(latestCode: Int, installedCode: Int, snoozed: Boolean): Boolean = latestCode > installedCode && !snoozed

        fun sha256(file: File): String = file.inputStream().use { input ->
            val md = MessageDigest.getInstance("SHA-256")
            val buf = ByteArray(64 * 1024)
            while (true) { val n = input.read(buf); if (n < 0) break; md.update(buf, 0, n) }
            md.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
