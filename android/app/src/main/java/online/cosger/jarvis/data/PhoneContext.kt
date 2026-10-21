package online.cosger.jarvis.data

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.PowerManager
import android.provider.CalendarContract
import online.cosger.jarvis.BuildConfig
import online.cosger.jarvis.net.DeviceLocation

data class CalendarItem(val title: String, val startMs: Long, val endMs: Long?, val location: String?)

/** What the phone can tell JARVIS about the owner's situation right now. */
data class PhoneContext(
    val location: DeviceLocation?,
    val activity: String,          // still | walking | driving | unknown
    val speedKmh: Double?,
    val battery: Int?,
    val charging: Boolean?,
    val headset: Boolean?,
    val screenOn: Boolean?,
    val network: String?,
    val unmuted: Boolean,
    val calendar: List<CalendarItem>,
    val appVersion: String = BuildConfig.VERSION_NAME,
) {
    companion object {
        /** Movement from GPS speed (no Play services needed). */
        fun activityFromSpeed(kmh: Double?): String = when {
            kmh == null -> "unknown"
            kmh < 1.5 -> "still"
            kmh < 8 -> "walking"
            else -> "driving"
        }
    }
}

/** Gathers [PhoneContext]. Each source is optional and fails soft (permission missing → null). */
class PhoneSensors(context: Context) {
    private val app = context.applicationContext

    fun collect(location: DeviceLocation?, unmuted: Boolean, includeCalendar: Boolean): PhoneContext {
        val kmh = location?.speedMps?.let { it * 3.6 }
        val battery = app.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val plugged = battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
        return PhoneContext(
            location = location,
            activity = PhoneContext.activityFromSpeed(kmh),
            speedKmh = kmh,
            battery = if (level >= 0 && scale > 0) level * 100 / scale else null,
            charging = battery?.let { plugged != 0 },
            headset = headset(),
            screenOn = runCatching { app.getSystemService(PowerManager::class.java).isInteractive }.getOrNull(),
            network = network(),
            unmuted = unmuted,
            calendar = if (includeCalendar) calendar() else emptyList(),
        )
    }

    fun headset(): Boolean? = runCatching {
        val am = app.getSystemService(AudioManager::class.java)
        am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any {
            it.type in setOf(AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
                AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLUETOOTH_SCO, AudioDeviceInfo.TYPE_USB_HEADSET)
        }
    }.getOrNull()

    private fun network(): String? = runCatching {
        val cm = app.getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return "none"
        when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            else -> "other"
        }
    }.getOrNull()

    /** Next 24 h of agenda (titles, times, places only). Needs READ_CALENDAR, opt-in in Pengaturan. */
    fun calendar(nowMs: Long = System.currentTimeMillis()): List<CalendarItem> {
        if (app.checkSelfPermission(Manifest.permission.READ_CALENDAR) != PackageManager.PERMISSION_GRANTED) return emptyList()
        val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().also {
            android.content.ContentUris.appendId(it, nowMs)
            android.content.ContentUris.appendId(it, nowMs + 24 * 3600_000L)
        }.build()
        val cols = arrayOf(CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.END, CalendarContract.Instances.EVENT_LOCATION, CalendarContract.Instances.ALL_DAY)
        return runCatching {
            app.contentResolver.query(uri, cols, null, null, "${CalendarContract.Instances.BEGIN} ASC")?.use { c ->
                buildList {
                    while (c.moveToNext() && size < 8) {
                        if (c.getInt(4) == 1) continue // all-day events are not "soon"
                        add(CalendarItem(c.getString(0) ?: "(tanpa judul)", c.getLong(1), c.getLong(2), c.getString(3)?.takeIf { it.isNotBlank() }))
                    }
                }
            } ?: emptyList()
        }.getOrDefault(emptyList())
    }
}
