package online.cosger.jarvis.ui.console

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import online.cosger.jarvis.ui.JarvisViewModel
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s
import online.cosger.jarvis.ui.theme.JarvisColors

/** Pure helpers of the voice picker (unit-tested). The models and their characters come live from OpenRouter. */
object VoiceChoices {
    /** Models whose id, name, provider or one of their characters contains [query]; the server already orders them
     *  (ElevenLabs first, then free, then cheapest). */
    fun filter(models: List<JsonObject>, query: String): List<JsonObject> {
        val q = query.trim().lowercase()
        if (q.isEmpty()) return models
        return models.filter { m ->
            listOf(m.s("id"), m.s("name"), m.s("provider")).any { q in it.lowercase() } ||
                m["voices"].arr().any { q in (it as? JsonPrimitive)?.content.orEmpty().lowercase() }
        }
    }

    fun voices(m: JsonObject): List<String> = m["voices"].arr().mapNotNull { (it as? JsonPrimitive)?.content }

    /** "elevenlabs" → "ElevenLabs", "fish-audio" → "Fish Audio". */
    fun provider(id: String): String = when (id) {
        "elevenlabs" -> "ElevenLabs"
        "openai" -> "OpenAI"
        else -> id.split('-').joinToString(" ") { it.replaceFirstChar(Char::uppercase) }
    }
}

/**
 * Suara JARVIS (Blueprint v4 Fase 3): how JARVIS speaks — the phone's own voice or a model from OpenRouter (ElevenLabs,
 * Gemini, Fish, …) with its character — and which OpenRouter model listens when the speech engine is "openrouter".
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun JarvisVoiceScreen(vm: JarvisViewModel, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val gate = rememberOwnerGate()
    val load = rememberLoad { vm.console.get("/api/v1/voice").obj() }
    var query by remember { mutableStateOf("eleven") }
    var sttQuery by remember { mutableStateOf("") }
    var showAllStt by remember { mutableStateOf(false) }
    val picked = remember { mutableStateMapOf<String, String>() }   // model id → character chosen on its card
    var busy by remember { mutableStateOf<String?>(null) }

    fun save(body: JsonObject, reason: String, done: String) = gate(reason) {
        scope.launch {
            runCatching { vm.console.put("/api/v1/voice", body) }
                .onSuccess { vm.notify(done); load.reload(); vm.refreshVoice() }
                .onFailure { vm.notify(it.message ?: "Gagal") }
        }
    }

    ConsolePage("Suara JARVIS", onBack, load.reload) {
        LoadState(load) { v ->
            val tts = v["tts"].obj()
            val cloud = tts.s("engine") == "openrouter"
            Card(border = JarvisColors.Cyan) {
                Label("Suara sekarang")
                Body(if (cloud) "${tts.s("model")} · karakter ${tts.s("voice")}" else "Suara bawaan HP (gratis, offline)")
                Small(v.s("note"))
                if (cloud) Action("Kembali ke suara HP") {
                    save(buildJsonObject { put("tts", buildJsonObject { put("engine", "android") }) }, "Ganti suara JARVIS", "Suara HP dipakai lagi.")
                }
                if (!tts.b("has_key")) Small("Belum ada API key OpenRouter — isi di Lainnya → Pengaturan server.", JarvisColors.Red)
            }
            Card {
                Label("Pilih suara dari OpenRouter")
                OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), singleLine = true,
                    label = { Text("Cari model atau karakter (mis. eleven, gemini, sarah)") })
                Small("ElevenLabs: Multilingual v2 / v3 paling fasih berbahasa Indonesia; Flash/Turbo paling cepat. Tekan \"Coba\" untuk mendengar.")
            }
            val models = VoiceChoices.filter(tts["models"].arr().map { it.obj() }, query)
            if (models.isEmpty()) Small("Tidak ada model yang cocok.")
            models.take(25).forEach { m ->
                val id = m.s("id")
                val voices = VoiceChoices.voices(m)
                val current = cloud && tts.s("model") == id
                val voice = picked[id] ?: (if (current) tts.s("voice") else voices.firstOrNull().orEmpty())
                Card(border = if (current) JarvisColors.Green else JarvisColors.Border) {
                    Body("${VoiceChoices.provider(m.s("provider"))} · ${m.s("name")}", size = 15)
                    Small(m.s("price_text") + (if (m.b("multilingual")) " · multibahasa" else "") +
                        (m.s("expires").takeIf { it.isNotBlank() }?.let { " · berakhir $it" } ?: ""))
                    if (m.s("description").isNotBlank()) Small(m.s("description"))
                    if (voices.isNotEmpty()) FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        voices.forEach { name ->
                            Action(if (name == voice) "● $name" else name, if (name == voice) JarvisColors.Green else JarvisColors.Muted) {
                                picked[id] = name
                            }
                        }
                    }
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Action(if (busy == id) "Memutar…" else "Coba", enabled = busy == null) {
                            busy = id
                            scope.launch {
                                vm.previewVoice(id, voice)?.let { vm.notify(it) }
                                busy = null
                            }
                        }
                        Action(if (current && voice == tts.s("voice")) "Dipakai" else "Pakai suara ini",
                            JarvisColors.Green, enabled = !(current && voice == tts.s("voice"))) {
                            save(buildJsonObject {
                                put("tts", buildJsonObject { put("engine", "openrouter"); put("model", id); if (voice.isNotBlank()) put("voice", voice) })
                            }, "Ganti suara JARVIS", "JARVIS sekarang bicara dengan ${m.s("name")}" + (if (voice.isNotBlank()) " ($voice)" else "") + ".")
                        }
                    }
                }
            }
            if (models.size > 25) Small("${models.size - 25} model lagi — persempit pencarian.")

            val stt = v["stt"].obj()
            Card {
                Label("Pendengaran (STT)")
                val engines = stt["options"].obj()
                Body("Mesin sekarang: " + ((engines[stt.s("engine")] as? JsonPrimitive)?.content ?: stt.s("engine")))
                if (stt.s("engine") == "openrouter") Small("Model: ${stt.s("model")}")
                Small("Mesin dasar dipilih di Komposisi AI → Mesin suara. Model di bawah dipakai bila mesinnya \"OpenRouter\". " +
                    "Bisukan mikrofon dulu agar pergantian berlaku.")
                OutlinedTextField(sttQuery, { sttQuery = it }, Modifier.fillMaxWidth(), singleLine = true, label = { Text("Cari model dengar") })
            }
            val sttModels = VoiceChoices.filter(stt["models"].arr().map { it.obj() }, sttQuery)
            (if (showAllStt || sttQuery.isNotBlank()) sttModels else sttModels.take(6)).forEach { m ->
                val id = m.s("id")
                val current = stt.s("engine") == "openrouter" && stt.s("model") == id
                Card(border = if (current) JarvisColors.Green else JarvisColors.Border) {
                    Body("${VoiceChoices.provider(m.s("provider"))} · ${m.s("name")}", size = 14)
                    Small(m.s("price_text"))
                    Action(if (current) "Dipakai" else "Pakai untuk mendengar", JarvisColors.Green, enabled = !current) {
                        gate("Ganti model dengar") {
                            scope.launch {
                                runCatching {
                                    vm.console.put("/api/v1/voice", buildJsonObject { put("stt_model", id) })
                                    vm.console.put("/api/v1/composition", buildJsonObject {
                                        put("changes", buildJsonObject { put("stt", "openrouter") })
                                    })
                                }.onSuccess {
                                    vm.notify("JARVIS mendengar dengan ${m.s("name")}. Bisukan lalu nyalakan mikrofon agar berlaku.")
                                    load.reload(); vm.refreshComposition()
                                }.onFailure { vm.notify(it.message ?: "Gagal") }
                            }
                        }
                    }
                }
            }
            if (!showAllStt && sttQuery.isBlank() && sttModels.size > 6) Action("Tampilkan ${sttModels.size - 6} model lagi") { showAllStt = true }
            Small("Harga dari katalog OpenRouter (perkiraan). Biaya suara masuk anggaran bulanan kategori \"suara\".")
        }
    }
}
