package online.cosger.jarvis.alarm

import android.app.KeyguardManager
import android.app.NotificationManager
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.speech.tts.TextToSpeech
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import online.cosger.jarvis.JarvisApp
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * ADR-087: the full-screen alarm (mockup "Bangun"). The ringtone starts soft and rises; the server's greeting (subuh, weather, the
 * first thing of the day) is read in the phone's own voice; no answer after a few minutes → full volume and vibration. "Tunda" rings
 * again after the snooze minutes; "Aku sudah bangun" stops it. Works offline — only the greeting needs the server.
 */
class AlarmActivity : ComponentActivity() {
    private var player: MediaPlayer? = null
    private var tts: TextToSpeech? = null
    private val vibrator by lazy { getSystemService(Vibrator::class.java) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 27) { setShowWhenLocked(true); setTurnScreenOn(true) }
        else @Suppress("DEPRECATION") window.addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        getSystemService(KeyguardManager::class.java)?.requestDismissKeyguard(this, null)
        val spec = AlarmScheduler.spec(this)
        startRinging()
        setContent {
            var greeting by remember { mutableStateOf("") }
            var prayer by remember { mutableStateOf("") }
            var loud by remember { mutableStateOf(false) }
            LaunchedEffect(Unit) {
                val w = fetchGreeting()
                greeting = w?.optString("text")?.ifBlank { null } ?: "Selamat pagi. Waktunya bangun."
                prayer = w?.let { prayerLine(it) }.orEmpty()
                if (spec?.greeting != false) speak(greeting)
            }
            LaunchedEffect(Unit) {
                delay((spec?.escalateMin ?: 5) * 60_000L)
                loud = true
                escalate()
            }
            AlarmFace(greeting, prayer, loud, spec?.snoozeMin ?: 5, onSnooze = { snooze(spec?.snoozeMin ?: 5) }, onAwake = { awake() })
        }
    }

    private fun startRinging() {
        val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM) ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
        player = runCatching {
            MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ALARM).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                setDataSource(this@AlarmActivity, uri)
                isLooping = true
                setVolume(0.15f, 0.15f)
                prepare()
                start()
            }
        }.getOrNull()
        Thread {   // soft → full over a minute
            var v = 0.15f
            while (v < 1f && player != null) {
                Thread.sleep(6_000)
                v = (v + 0.09f).coerceAtMost(1f)
                runCatching { player?.setVolume(v, v) }
            }
        }.start()
    }

    private fun escalate() {
        runCatching { player?.setVolume(1f, 1f) }
        runCatching { vibrator?.vibrate(VibrationEffect.createWaveform(longArrayOf(0, 800, 400), 0)) }
    }

    private suspend fun fetchGreeting(): JSONObject? = withContext(Dispatchers.IO) {
        val s = (application as JarvisApp).settings.state.value
        if (!s.isConfigured) return@withContext null
        runCatching {
            val client = OkHttpClient.Builder().callTimeout(8, TimeUnit.SECONDS).build()
            val req = Request.Builder().url(s.serverUrl.trimEnd('/') + "/api/v1/app/ibadah/wake").header("Authorization", "Bearer ${s.deviceToken}").build()
            client.newCall(req).execute().use { r -> if (r.isSuccessful) JSONObject(r.body?.string().orEmpty()) else null }
        }.getOrNull()
    }

    private fun speak(text: String) {
        runCatching { player?.setVolume(0.08f, 0.08f) }
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.forLanguageTag("id-ID")
                tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "wake")
            }
        }
    }

    private fun stopAll() {
        runCatching { player?.stop(); player?.release() }
        player = null
        runCatching { vibrator?.cancel() }
        runCatching { tts?.stop(); tts?.shutdown() }
        getSystemService(NotificationManager::class.java)?.cancel(AlarmReceiver.NOTIF_ID)
    }

    private fun snooze(min: Int) {
        stopAll()
        AlarmScheduler.snooze(this, min)
        finish()
    }

    private fun awake() {
        stopAll()
        val s = (application as JarvisApp).settings.state.value
        if (s.isConfigured) Thread {   // tell JARVIS when the owner got up: the habits learn his real waking time
            runCatching {
                val req = Request.Builder().url(s.serverUrl.trimEnd('/') + "/api/v1/app/opened").header("Authorization", "Bearer ${s.deviceToken}")
                    .post("""{"feature":"bangun"}""".toRequestBody("application/json".toMediaType())).build()
                OkHttpClient().newCall(req).execute().close()
            }
        }.start()
        finish()
    }

    override fun onDestroy() {
        stopAll()
        super.onDestroy()
    }
}

@androidx.compose.runtime.Composable
private fun AlarmFace(greeting: String, prayer: String, loud: Boolean, snoozeMin: Int, onSnooze: () -> Unit, onAwake: () -> Unit) {
    val now = remember { SimpleDateFormat("HH.mm", Locale.forLanguageTag("id-ID")).format(Date()) }
    val day = remember { SimpleDateFormat("EEEE, d MMMM", Locale.forLanguageTag("id-ID")).format(Date()) }
    val amber = Color(0xFFFFB547)
    Box(Modifier.fillMaxSize().background(Color(0xFF07060A)).padding(24.dp)) {
        Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(64.dp))
            Box(Modifier.size(150.dp).border(1.dp, Color(0xFF5A3E24), CircleShape), contentAlignment = Alignment.Center) {
                Box(Modifier.size(96.dp).background(Color(0xFF2A1C10), CircleShape).border(1.5.dp, amber, CircleShape))
            }
            Text(now, color = Color(0xFFF2EADF), fontSize = 84.sp, fontWeight = FontWeight.Light, modifier = Modifier.padding(top = 24.dp))
            Text(day, color = Color(0xFFD9CBB8), fontSize = 16.sp)
            if (prayer.isNotBlank()) Text(prayer, color = amber, fontSize = 15.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 10.dp))
            if (greeting.isNotBlank()) {
                Box(Modifier.padding(top = 28.dp).fillMaxWidth().background(Color(0xFF15110C), RoundedCornerShape(20.dp))
                    .border(1.dp, Color(0xFF3A2A1C), RoundedCornerShape(20.dp)).padding(16.dp)) {
                    Text("“$greeting”", color = Color(0xFFF2EADF), fontSize = 15.sp, lineHeight = 22.sp)
                }
            }
            Spacer(Modifier.weight(1f))
            Text(if (loud) "Belum ada respons — volume penuh & getar." else "Volume naik pelan-pelan.", color = Color(0xFFB8A891), fontSize = 12.sp,
                textAlign = TextAlign.Center, modifier = Modifier.padding(bottom = 14.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = onSnooze, modifier = Modifier.weight(1f).height(56.dp), shape = RoundedCornerShape(16.dp)) {
                    Text("Tunda $snoozeMin mnt", color = Color(0xFFF2EADF))
                }
                Button(onClick = onAwake, modifier = Modifier.weight(1.4f).height(56.dp), shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = amber, contentColor = Color(0xFF1A1204))) {
                    Text("Aku sudah bangun", fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}


/** "Subuh 04.13 · 13 menit lagi" from the wake answer ({next: {name, time, in_min}}), or "" when the next prayer is not subuh. */
internal fun prayerLine(w: JSONObject): String {
    val n = w.optJSONObject("next") ?: return ""
    if (n.optString("name") != "subuh") return ""
    val t = n.optString("time").replace(':', '.')
    val m = n.optInt("in_min", -1)
    return if (m >= 0) "Subuh $t · $m menit lagi" else "Subuh $t"
}
