package online.cosger.jarvis.ui.console

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

class VoiceChoicesTest {
    private val models = Json.parseToJsonElement("""[
        {"id":"elevenlabs/eleven-multilingual-v2","name":"ElevenLabs Multilingual v2","provider":"elevenlabs","voices":["george","sarah"]},
        {"id":"google/gemini-3.8-flash-tts","name":"Gemini TTS","provider":"google","voices":["Kore","Puck"]},
        {"id":"fish-audio/s2.1-pro-free:free","name":"Fish S2.1 Free","provider":"fish-audio","voices":[]}
    ]""").jsonArray.map { it.jsonObject }

    @Test fun filtersByModelProviderOrCharacter() {
        assertEquals(3, VoiceChoices.filter(models, " ").size)
        assertEquals(listOf("elevenlabs/eleven-multilingual-v2"), VoiceChoices.filter(models, "Eleven").map { it["id"].toString().trim('"') })
        assertEquals(listOf("google/gemini-3.8-flash-tts"), VoiceChoices.filter(models, "kore").map { it["id"].toString().trim('"') })
        assertEquals(listOf("george", "sarah"), VoiceChoices.voices(models[0]))
        assertEquals("ElevenLabs", VoiceChoices.provider("elevenlabs"))
        assertEquals("Fish Audio", VoiceChoices.provider("fish-audio"))
    }
}
