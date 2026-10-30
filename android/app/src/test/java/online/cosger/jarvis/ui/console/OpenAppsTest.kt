package online.cosger.jarvis.ui.console

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class OpenAppsTest {
    @Test fun onlyTheApprovedAppsCanBeOpenedFromThePage() {
        assertEquals(setOf("gojek", "gopay", "pluang", "kopikenangan", "qpon", "jobstreet"), OPENABLE_APPS.keys)
        assertEquals("com.EmasDigi", OPENABLE_APPS["pluang"])
        assertNull(OPENABLE_APPS["com.bca"])   // a bank app is never launched from the page
    }
}
