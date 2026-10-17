package online.cosger.jarvis.ui

import online.cosger.jarvis.net.Protocol
import online.cosger.jarvis.net.ServerEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BoardTest {
    @Test fun parsesWorkerAndReportEvents() {
        assertEquals(ServerEvent.Task(3, "Cek emas", "running"), Protocol.parse("""{"type":"task","id":3,"title":"Cek emas","status":"running"}"""))
        assertEquals(
            ServerEvent.Tasks(listOf(ServerEvent.Task(1, "A", "queued"))),
            Protocol.parse("""{"type":"tasks","items":[{"id":1,"title":"A","status":"queued","created_at":"x"}]}"""),
        )
        assertEquals(
            ServerEvent.TaskEvent(3, ServerEvent.Thought("Cari harga", null)),
            Protocol.parse("""{"type":"task_event","task_id":3,"event":{"type":"thought","text":"Cari harga"}}"""),
        )
        assertEquals(
            ServerEvent.Report(7, 3, "Emas Rp2,5 juta.", 2, true),
            Protocol.parse("""{"type":"report","id":7,"task_id":3,"text":"Emas Rp2,5 juta.","attempt":2,"repeat":true}"""),
        )
        assertEquals("""{"type":"ack","report_id":7}""", Protocol.control("ack", "report_id", 7))
    }

    @Test fun workerLifecycleAndLiveThoughts() {
        var b = Board()
        b = b.reduce(ServerEvent.Task(1, "Cek emas", "queued"))
        b = b.reduce(ServerEvent.Task(1, "Cek emas", "running"))
        b = b.reduce(ServerEvent.TaskEvent(1, ServerEvent.Thought("Mencari harga Antam.", null)))
        b = b.reduce(ServerEvent.TaskEvent(1, ServerEvent.Tool("c1", "web_search", "Mencari di web", "emas antam", "", true, null)))
        assertEquals(1, b.activeWorkers.size)
        assertEquals("Mencari harga Antam.", b.workers[0].live.thoughts)
        assertEquals("Mencari di web", b.workers[0].live.tools[0].title)
        b = b.reduce(ServerEvent.Task(1, "Cek emas", "completed"))
        assertTrue(b.activeWorkers.isEmpty())
    }

    @Test fun reportStatesSpokenAckAndUnheard() {
        var b = Board().reduce(ServerEvent.Report(7, 1, "Hasil.", 1, false))
        assertEquals(SpokenReport.State.Waiting, b.reports[0].state)
        b = b.markSpoken(7)
        assertEquals(SpokenReport.State.Spoken, b.reports[0].state)
        b = b.reduce(ServerEvent.Report(7, 1, "Hasil.", 2, true)) // repeated by the server
        assertEquals(2, b.reports.single().attempt)
        b = b.reduce(ServerEvent.ReportAck(7))
        assertTrue(b.openReports.isEmpty())
        b = Board().reduce(ServerEvent.Report(8, null, "x", 3, true)).reduce(ServerEvent.ReportUnheard(8))
        assertEquals(SpokenReport.State.Unheard, b.openReports.single().state)
    }

    @Test fun mediaEventsAreParsedFilteredAndKept() {
        val e = Protocol.parse("""{"type":"media","caption":"Contoh kampas rem","items":[
            {"kind":"video","url":"https://www.youtube.com/watch?v=XkQzAS-9G3E","title":"Ganti kampas","thumbnail":"https://i.ytimg.com/vi/XkQzAS-9G3E/hqdefault.jpg","source":""},
            {"kind":"image","url":"http://insecure/x.jpg","title":"x","thumbnail":null,"source":""}]}""") as ServerEvent.Media
        assertEquals(1, e.items.size) // non-https dropped
        assertEquals("https://i.ytimg.com/vi/XkQzAS-9G3E/hqdefault.jpg", e.items[0].preview)
        var b = Board().reduce(e).reduce(e)
        assertEquals(listOf(2L, 1L), b.media.map { it.seq }) // newest first
        b = b.dismissMedia(2)
        assertEquals(listOf(1L), b.media.map { it.seq })
    }

    @Test fun commandCarriesScreenFrameOnlyWhenSharing() {
        assertTrue(Protocol.command("ini kenapa?", "s", null, "QUJD").contains("\"screen\":\"QUJD\""))
        assertTrue(!Protocol.command("halo", "s").contains("screen"))
    }
}
