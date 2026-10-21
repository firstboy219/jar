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
    val diarize: Boolean = true,
    val endpointingMs: Int = 1000,
    val utteranceEndMs: Int = 1800,
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
        // End of speech after a pause (tuned on the server; 0.7 s cut sentences mid-thought), UtteranceEnd as backup.
        addQueryParameter("endpointing", endpointingMs.toString())
        addQueryParameter("utterance_end_ms", utteranceEndMs.toString())
        addQueryParameter("vad_events", "true")
        // How many different voices were heard — helps JARVIS ignore people who are not talking to it.
        if (diarize) addQueryParameter("diarize", "true")
        keywords.forEach {
            // nova-3 uses keyterm prompting; older models use keyword boosting.
            if (model.startsWith("nova-3")) addQueryParameter("keyterm", it)
            else addQueryParameter("keywords", "$it:2")
        }
    }.build()
}
