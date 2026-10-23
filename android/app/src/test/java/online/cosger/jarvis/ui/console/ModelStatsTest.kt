package online.cosger.jarvis.ui.console

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ModelStatsTest {
    @Test fun timesAreReadable() {
        assertEquals("425 ms", ModelStats.ms(425))
        assertEquals("1,6 dtk", ModelStats.ms(1612))
        assertEquals("?", ModelStats.ms(null))
    }

    @Test fun reliabilityLevelsNeedEnoughCalls() {
        assertEquals(2, ModelStats.level(99.0, 40))
        assertEquals(1, ModelStats.level(90.0, 40))
        assertEquals(0, ModelStats.level(52.0, 40))
        assertEquals(-1, ModelStats.level(100.0, 3))   // three calls prove nothing
        assertEquals(-1, ModelStats.level(null, 50))
    }

    @Test fun costsAndErrors() {
        assertEquals("gratis", ModelStats.cost(0.0))
        assertEquals("<\$0.0001", ModelStats.cost(0.00001))
        assertEquals("\$0.0004", ModelStats.cost(0.0004))
        val errors = Json.parseToJsonElement("""{"ditolak OpenRouter (403)": 9, "timeout": 2, "dibatalkan": 5}""").jsonObject
        assertEquals("ditolak OpenRouter (403) ×9, dibatalkan ×5", ModelStats.errorsText(errors, 2))
    }

    @Test fun rowBadge() {
        assertNull(ModelStats.badge(0, null, null))
        assertEquals("dipakai 25× · 96% berhasil · median 1,3 dtk", ModelStats.badge(25, 96.0, 1323))
    }
}
