package online.cosger.jarvis.data

import online.cosger.jarvis.net.DeviceLocation
import online.cosger.jarvis.net.Protocol
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocationFormatTest {
    @Test fun addressPartsAreDedupedAndBlanksDropped() {
        assertEquals(
            "Jl. Boulevard Raya, Kelapa Gading, Jakarta Utara, Daerah Khusus Ibukota Jakarta",
            LocationProvider.formatParts("Jl. Boulevard Raya", "Kelapa Gading", "Jakarta Utara", "Jakarta Utara", "Daerah Khusus Ibukota Jakarta"),
        )
        assertNull(LocationProvider.formatParts(null, " ", null, "", null))
    }

    @Test fun commandCarriesLocationOnlyWhenGiven() {
        val loc = DeviceLocation(-6.158, 106.905, 18.5, 4, "Kelapa Gading, Jakarta Utara")
        val withLoc = Protocol.command("cuaca di sini?", "s", loc)
        assertTrue(withLoc.contains("\"location\":{\"lat\":-6.158,\"lon\":106.905,\"accuracy_m\":18.5,\"age_s\":4,\"address\":\"Kelapa Gading, Jakarta Utara\"}"))
        assertFalse(Protocol.command("halo", "s").contains("location"))
    }
}
