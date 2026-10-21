package online.cosger.jarvis.voice

import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * The microphone side of JARVIS, whichever speech engine the owner chose (Komposisi AI):
 *  - [ContinuousListener]: streams to Deepgram, emits finished text ([texts]);
 *  - [VadListener]: Silero VAD on the phone cuts each utterance and emits its audio ([audio]) for the
 *    server to transcribe (local Whisper or Groq). Silence never leaves the phone.
 */
interface VoiceInput {
    val state: StateFlow<MicState>
    val level: StateFlow<Float>
    val interim: StateFlow<String>
    val texts: SharedFlow<UtteranceSegmenter.Output.Utterance>
    val audio: SharedFlow<ByteArray>
    val errors: SharedFlow<String>
    val unmuted: Boolean
    val lastSpeechAtMs: Long

    fun unmute(config: suspend () -> SttConfig)
    fun mute()
    /** While JARVIS speaks: drop mic audio so it does not hear itself. */
    fun pause()
    fun resume()
    /** The server got the utterance and is transcribing it ("Hearing" → "Ready"). */
    fun setInterim(text: String) {}
}
