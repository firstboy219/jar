package online.cosger.jarvis.voice

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import kotlin.coroutines.resume

/** A voice on the server (OpenRouter: ElevenLabs, Gemini, …): MP3 of one sentence, or null = say it with the phone's own voice. */
fun interface CloudVoice {
    suspend fun speak(text: String): ByteArray?
}

/**
 * TTS with a queue. [speaking] lets the listener pause the mic so JARVIS does not hear itself; [onDone] callbacks tell
 * the server a report was actually said out loud.
 *
 * Two voices (Blueprint v4 Fase 3): the phone's own engine (Indonesian), or — when the owner picked one — a [cloud] voice.
 * With a cloud voice every sentence is fetched as soon as it is queued (so the next one downloads while this one plays)
 * and played strictly in order; whatever the server refuses (private/sensitive text, budget, no network) is spoken by the
 * phone's engine in its place, so nothing is ever skipped.
 */
class Speaker(context: Context) {
    private val app = context.applicationContext
    private var ready = false
    private val _speaking = MutableStateFlow(false)
    val speaking: StateFlow<Boolean> = _speaking
    private val done = ConcurrentHashMap<String, () -> Unit>()
    private val finishedSignal = ConcurrentHashMap<String, CompletableDeferred<Unit>>()
    private val queued = ConcurrentHashMap.newKeySet<String>()
    private var seq = 0
    @Volatile private var generation = 0
    @Volatile var cloud: CloudVoice? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val items = Channel<Item>(Channel.UNLIMITED)
    private var player: MediaPlayer? = null

    private class Item(val id: String, val text: String, val audio: Deferred<ByteArray?>?, val generation: Int)

    private val tts = TextToSpeech(app) { status ->
        ready = status == TextToSpeech.SUCCESS
        if (ready) setLanguage()
    }.apply {
        setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String) { _speaking.value = true }
            override fun onDone(utteranceId: String) = finished(utteranceId)
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String) = finished(utteranceId)
            override fun onStop(utteranceId: String, interrupted: Boolean) = finished(utteranceId)
        })
    }

    init {
        scope.launch { for (item in items) play(item) }
    }

    private fun finished(id: String) {
        queued.remove(id)
        done.remove(id)?.invoke()
        finishedSignal.remove(id)?.complete(Unit)
        if (queued.isEmpty()) _speaking.value = false
    }

    private fun setLanguage() {
        val id = Locale.forLanguageTag("id-ID")
        if (tts.isLanguageAvailable(id) >= TextToSpeech.LANG_AVAILABLE) tts.language = id
    }

    /**
     * Say [text] after whatever is already queued; [onDone] runs once it has been spoken (or skipped).
     * [local]: the server marked it private/sensitive — never the cloud voice.
     */
    fun say(text: String, onDone: (() -> Unit)? = null, local: Boolean = false) {
        val clean = stripMarkdown(text)
        val voice = cloud
        if (clean.isBlank() || (voice == null && !ready)) {
            onDone?.invoke()
            return
        }
        val id = "j${seq++}"
        onDone?.let { done[id] = it }
        queued += id
        _speaking.value = true
        if (voice == null) {
            tts.speak(clean, TextToSpeech.QUEUE_ADD, null, id)
            return
        }
        val audio = if (local) null else scope.async(Dispatchers.IO) { runCatching { voice.speak(clean) }.getOrNull() }
        items.trySend(Item(id, clean, audio, generation))
    }

    private suspend fun play(item: Item) {
        if (item.generation != generation) return finished(item.id)
        val mp3 = withTimeoutOrNull(20_000) { item.audio?.await() }
        if (item.generation != generation) return finished(item.id)
        if (mp3 != null && mp3.isNotEmpty() && playMp3(mp3)) return finished(item.id)
        if (item.generation != generation || !ready) return finished(item.id)
        val signal = CompletableDeferred<Unit>().also { finishedSignal[item.id] = it }
        tts.speak(item.text, TextToSpeech.QUEUE_ADD, null, item.id)   // the phone's own voice stands in
        withTimeoutOrNull(60_000) { signal.await() } ?: finished(item.id)
    }

    /** Plays one MP3 to the end; false when it could not be played (then the phone's voice says it). */
    private suspend fun playMp3(bytes: ByteArray): Boolean {
        val file = File(app.cacheDir, "jarvis-say-${System.nanoTime()}.mp3")
        return try {
            file.writeBytes(bytes)
            suspendCancellableCoroutine { cont ->
                val mp = MediaPlayer()
                player = mp
                fun end(ok: Boolean) {
                    if (player === mp) player = null
                    runCatching { mp.release() }
                    if (cont.isActive) cont.resume(ok)
                }
                runCatching {
                    mp.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    mp.setDataSource(file.path)
                    mp.setOnCompletionListener { end(true) }
                    mp.setOnErrorListener { _, _, _ -> end(false); true }
                    mp.prepare()
                    mp.start()
                }.onFailure { end(false) }
                cont.invokeOnCancellation { end(false) }
            }
        } catch (e: Exception) {
            false
        } finally {
            file.delete()
        }
    }

    /** 'Coba' on the voice screen: play a sample right away (not queued). */
    fun preview(bytes: ByteArray) {
        stop()
        val id = "p${seq++}"
        queued += id
        _speaking.value = true
        scope.launch { playMp3(bytes); finished(id) }
    }

    fun stop() {
        generation++
        player?.let { p -> runCatching { p.stop() } }
        if (ready) tts.stop()
        queued.toList().forEach(::finished)
    }

    fun shutdown() {
        stop()
        tts.shutdown()
    }

    companion object {
        /** Spoken text should not read out markdown symbols or code. */
        fun stripMarkdown(text: String): String = text
            .replace(Regex("```.*?```", RegexOption.DOT_MATCHES_ALL), " (kode) ")
            .replace(Regex("`([^`]*)`"), "$1")
            .replace(Regex("\\*\\*|__|[*_#>]"), "")
            .replace(Regex("^\\s*[-•]\\s+", RegexOption.MULTILINE), "")
            .replace(Regex("\\[([^]]+)]\\([^)]+\\)"), "$1")
            .replace(Regex("\\s+"), " ")
            .trim()
    }
}
