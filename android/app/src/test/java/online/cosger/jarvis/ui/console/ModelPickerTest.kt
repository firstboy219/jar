package online.cosger.jarvis.ui.console

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ModelPickerTest {
    private fun obj(s: String) = Json.parseToJsonElement(s).jsonObject

    @Test fun pricesAreShortAndReadable() {
        assertEquals("0.044", Models.usd(0.0444))
        assertEquals("0.89", Models.usd(0.886))
        assertEquals("15", Models.usd(15.0))
        assertEquals("0", Models.usd(0.0))
        assertEquals("gratis", Models.price(true, 0.0, 0.0))
        assertEquals("\$0.091 masuk / \$0.18 keluar per 1 juta token", Models.price(false, 0.091, 0.182))
    }

    @Test fun contextAndTags() {
        assertEquals("1M", Models.context(1_048_576))
        assertEquals("131K", Models.context(131_072))
        assertEquals(listOf("GRATIS", "GAMBAR"), Models.tags(obj("""{"free": true, "vision": true, "tools": false}""")))
    }

    @Test fun routesAreNamedForTheOwner() {
        assertEquals("DeepSeek: V4 Flash", Models.routeLabel(obj("""{"provider":"openrouter","model":"deepseek/x","name":"DeepSeek: V4 Flash"}""")))
        assertEquals("Model lokal (Qwen)", Models.routeLabel(obj("""{"provider":"lokal","model":"qwen-lokal"}""")))
        assertEquals("a/b", Models.routeLabel(obj("""{"provider":"openrouter","model":"a/b"}""")))
        assertEquals("di server, gratis", Models.routePrice(obj("""{"provider":"lokal-kerja","model":"qwen-lokal"}""")))
    }

    @Test fun categoriesNeedWhatTheServerNeeds() {
        assertTrue(Models.needsTools("ngobrol") && Models.needsTools("coding"))
        assertFalse(Models.needsTools("rapat") || Models.needsTools("balas-pesan"))
        assertTrue(Models.needsVision("penglihatan") && !Models.needsVision("ngobrol"))
    }

    @Test fun queryIsEncoded() {
        assertEquals("/api/v1/console/openrouter/models?q=deepseek+flash&free=false&tools=true&vision=false&sort=termurah&limit=60",
            Models.query(" deepseek flash ", false, true, false, "termurah"))
    }
}
