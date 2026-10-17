package online.cosger.jarvis.ui

import online.cosger.jarvis.net.ContextItem
import online.cosger.jarvis.net.ServerEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TurnStateTest {
    private fun tool(id: String, running: Boolean, label: String = "q") =
        ServerEvent.Tool(id, "memory_search", "Mencari di memori", label, "", running, "s")

    @Test fun fullHermesTurnDrivesPhases() {
        var s = TurnState(phase = Phase.Thinking, userText = "halo")
        s = s.reduce(ServerEvent.Status("thinking", "s"))
        assertEquals(Phase.Thinking, s.phase)
        s = s.reduce(ServerEvent.Thought("The user ", "s")).reduce(ServerEvent.Thought("greets.", "s"))
        assertEquals("The user greets.", s.thoughts)
        s = s.reduce(tool("c1", running = true))
        assertEquals(Phase.Acting, s.phase)
        s = s.reduce(ServerEvent.Context("q", listOf(ContextItem("fakta", "personal", 0.7)), "s"))
        assertEquals(1, s.context.size)
        s = s.reduce(tool("c1", running = false, label = ""))
        assertEquals(1, s.tools.size)
        assertFalse(s.tools[0].running)
        assertEquals("q", s.tools[0].label) // completion events carry no label; keep the original
        assertEquals(Phase.Thinking, s.phase)
        s = s.reduce(ServerEvent.Delta("Ha", "s")).reduce(ServerEvent.Delta("lo", "s"))
        assertEquals(Phase.Answering, s.phase)
        assertEquals("Halo", s.answer)
        s = s.reduce(ServerEvent.Reply("Halo!", "hermes", "s"))
        assertEquals(Phase.Done, s.phase)
        assertEquals("Halo!", s.answer)
    }

    @Test fun thoughtsAfterAnswerStartDoNotFlipPhaseBack() {
        val s = TurnState(phase = Phase.Answering).reduce(ServerEvent.Thought("x", "s"))
        assertEquals(Phase.Answering, s.phase)
    }

    @Test fun errorsFailTheTurn() {
        val s = TurnState(phase = Phase.Thinking).reduce(ServerEvent.Error("internal error", "s"))
        assertEquals(Phase.Failed, s.phase)
        assertEquals("internal error", s.error)
    }

    @Test fun buffersAreBounded() {
        var s = TurnState()
        repeat(20) { s = s.reduce(tool("t$it", running = true)) }
        assertEquals(TurnState.MAX_TOOLS, s.tools.size)
        s = s.reduce(ServerEvent.Thought("x".repeat(10_000), "s"))
        assertEquals(TurnState.MAX_THOUGHTS, s.thoughts.length)
        assertTrue(s.recentThoughts(600).length <= 601)
    }
}
