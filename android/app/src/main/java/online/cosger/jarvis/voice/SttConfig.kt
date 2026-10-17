package online.cosger.jarvis.voice

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl

/** Speech-to-text settings + short-lived token, both handed out by jarvis-core. */
data class SttConfig(
    val token: String,
    val model: String = "nova-2",
    val language: String = "id",
    val keywords: List<String> = emptyList(),
    val expiresAtMs: Long = Long.MAX_VALUE,
) {
    fun isFresh(nowMs: Long = System.currentTimeMillis()) = nowMs < expiresAtMs - 15_000

    fun url(): HttpUrl = "https://api.deepgram.com/v1/listen".toHttpUrl().newBuilder().apply {
        addQueryParameter("model", model)
        addQueryParameter("language", language)
        addQueryParameter("encoding", "linear16")
        addQueryParameter("sample_rate", ContinuousListener.SAMPLE_RATE.toString())
        addQueryParameter("channels", "1")
        addQueryParameter("interim_results", "true")
        addQueryParameter("smart_format", "true")
        // Continuous listening: end of speech after ~0.7 s of silence, UtteranceEnd as a backup in noise.
        addQueryParameter("endpointing", "700")
        addQueryParameter("utterance_end_ms", "1500")
        addQueryParameter("vad_events", "true")
        keywords.forEach {
            // nova-3 uses keyterm prompting; older models use keyword boosting.
            if (model.startsWith("nova-3")) addQueryParameter("keyterm", it)
            else addQueryParameter("keywords", "$it:2")
        }
    }.build()
}
