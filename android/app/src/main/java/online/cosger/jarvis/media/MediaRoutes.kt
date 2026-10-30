package online.cosger.jarvis.media

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings

/** ADR-087 phase J: where the sound and the picture go — the phone's own speaker picker, and the TV. */
object MediaRoutes {
    /** The system's output picker for this app (Bluetooth speakers, Cast speakers), Android 11+; else the Bluetooth settings. */
    fun pickSpeaker(context: Context): Boolean {
        if (Build.VERSION.SDK_INT >= 34 && runCatching { android.media.MediaRouter2.getInstance(context).showSystemOutputSwitcher() }.getOrDefault(false)) return true
        if (Build.VERSION.SDK_INT >= 30) {
            val out = Intent("com.android.systemui.action.LAUNCH_MEDIA_OUTPUT_DIALOG")
                .putExtra("com.android.systemui.extra.package_name", context.packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (runCatching { context.sendBroadcast(out.setPackage("com.android.systemui")); true }.getOrDefault(false)) return true
        }
        return runCatching { context.startActivity(Intent(Settings.ACTION_BLUETOOTH_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true }.getOrDefault(false)
    }

    /** To the TV: a YouTube video in the YouTube app (its Cast button keeps it official), anything else in the cast/mirroring settings. */
    fun castTv(context: Context, youtubeId: String, start: Int): Boolean {
        if (Regex("[A-Za-z0-9_-]{11}").matches(youtubeId)) {
            val app = Intent(Intent.ACTION_VIEW, Uri.parse("vnd.youtube:$youtubeId?t=$start")).setPackage("com.google.android.youtube").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (runCatching { context.startActivity(app); true }.getOrDefault(false)) return true
            return runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(webUrl(youtubeId, start))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true }.getOrDefault(false)
        }
        return runCatching { context.startActivity(Intent("android.settings.CAST_SETTINGS").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); true }.getOrDefault(false)
    }

    fun webUrl(id: String, start: Int) = "https://www.youtube.com/watch?v=$id&t=${start}s"
}
