package online.cosger.jarvis.alarm

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import online.cosger.jarvis.MainActivity
import org.json.JSONObject
import java.util.Calendar

/** The owner's alarm as the server keeps it (app settings 'alarm'): time "HH:MM", days 0=Mon…6=Sun. */
data class AlarmSpec(val enabled: Boolean, val hour: Int, val minute: Int, val days: Set<Int>, val snoozeMin: Int, val escalateMin: Int, val greeting: Boolean) {
    companion object {
        fun parse(json: String): AlarmSpec? = runCatching {
            val o = JSONObject(json)
            val (h, m) = o.optString("time", "04:00").split(":").map { it.trim().toInt() }
            val d = o.optJSONArray("days")
            val days = (0 until (d?.length() ?: 0)).map { d!!.getInt(it) }.filter { it in 0..6 }.toSet()
            AlarmSpec(o.optBoolean("enabled", true), h.coerceIn(0, 23), m.coerceIn(0, 59), days,
                o.optInt("snooze_min", 5).coerceIn(1, 30), o.optInt("escalate_after_min", 5).coerceIn(1, 30), o.optBoolean("voice_greeting", true))
        }.getOrNull()
    }
}

/**
 * ADR-087: the morning alarm rings from the phone's own clock (AlarmManager.setAlarmClock: exact, shown in the status bar, survives Doze),
 * so it works when the internet or the server is down. The spec is kept here so a reboot or a ring schedules the next one by itself.
 */
object AlarmScheduler {
    private const val PREFS = "jarvis_alarm"
    private const val REQ = 4004
    private const val SNOOZE_REQ = 4005

    /** Milliseconds of the next ring after [nowMs] (local time), or null when no day is picked. Pure. */
    fun nextAt(spec: AlarmSpec, nowMs: Long, cal: Calendar = Calendar.getInstance()): Long? {
        if (!spec.enabled || spec.days.isEmpty()) return null
        cal.timeInMillis = nowMs
        cal.set(Calendar.SECOND, 0); cal.set(Calendar.MILLISECOND, 0)
        cal.set(Calendar.HOUR_OF_DAY, spec.hour); cal.set(Calendar.MINUTE, spec.minute)
        repeat(8) {
            val dow = (cal.get(Calendar.DAY_OF_WEEK) + 5) % 7   // Calendar: Sun=1 … Sat=7 → Mon=0 … Sun=6
            if (cal.timeInMillis > nowMs && dow in spec.days) return cal.timeInMillis
            cal.add(Calendar.DAY_OF_MONTH, 1)
        }
        return null
    }

    fun save(context: Context, json: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("spec", json).apply()
        schedule(context)
    }

    fun spec(context: Context): AlarmSpec? = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("spec", null)?.let { AlarmSpec.parse(it) }

    fun schedule(context: Context) {
        val am = context.getSystemService(AlarmManager::class.java) ?: return
        val pi = ring(context, REQ)
        am.cancel(pi)
        val at = spec(context)?.let { nextAt(it, System.currentTimeMillis()) } ?: return
        val show = PendingIntent.getActivity(context, REQ, Intent(context, MainActivity::class.java).putExtra(MainActivity.EXTRA_ROUTE, "#/bangun"),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        runCatching { am.setAlarmClock(AlarmManager.AlarmClockInfo(at, show), pi) }
    }

    fun snooze(context: Context, minutes: Int) {
        val am = context.getSystemService(AlarmManager::class.java) ?: return
        val at = System.currentTimeMillis() + minutes * 60_000L
        runCatching { am.setAlarmClock(AlarmManager.AlarmClockInfo(at, null), ring(context, SNOOZE_REQ)) }
    }

    private fun ring(context: Context, req: Int): PendingIntent =
        PendingIntent.getBroadcast(context, req, Intent(context, AlarmReceiver::class.java).setAction(AlarmReceiver.ACTION_RING),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
}
