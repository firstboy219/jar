package online.cosger.jarvis.ui

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Test

class ServerUsageTest {
    @Test fun saysWhoUsesTheServerAndForWhat() {
        val u = ServerUsage.parse(Json.parseToJsonElement("""{"cpu_pct": 91.0, "cpu_cores": 4, "load": [6.7, 7.1, 6.6],
            "memory_gb": {"total": 15.4, "used": 7.5}, "swap_gb": {"used": 2.0}, "disk_gb": {"pct": 15, "used": 49, "total": 332},
            "tasks": {"owner": 1, "background": 1}, "ai": {"spent_usd": 0.42, "budget_usd": 20},
            "containers": [{"label": "AI kerja lokal", "cpu_pct": 88.4, "mem_gb": 2.7},
                           {"label": "Hermes", "cpu_pct": 3.1, "mem_gb": 0.3}, {"label": "Proxy web", "cpu_pct": 0.0, "mem_gb": 0.03}],
            "who": {"running": [{"id": 65, "title": "putarkan lagu idgitaf versi cover", "kind": "owner"},
                                {"id": 60, "title": "Pengawas alur", "kind": "selfimprove"}], "waiting": 2, "calm": false, "stopped": 1,
                    "ai": ["pengawas alur", "ngobrol denganmu"]}}""").jsonObject)
        assertEquals("AI kerja lokal 88% · Hermes 3%", u.busiest())
        assertEquals("tugasmu “putarkan lagu idgitaf versi cover” · 1 kerja latar JARVIS · 2 menunggu giliran · " +
            "AI: pengawas alur, ngobrol denganmu", u.purpose())
        assertEquals(1, u.stopped)
    }
}
