package online.cosger.jarvis.ui

import online.cosger.jarvis.net.ContextItem
import online.cosger.jarvis.net.ServerEvent

/** What JARVIS is doing right now — drives the orb animation and the thought stream. */
enum class Phase { Idle, Listening, Thinking, Acting, Answering, Done, Failed }

data class ToolActivity(val id: String, val title: String, val label: String, val emoji: String, val running: Boolean)

data class ContextCard(val query: String, val items: List<ContextItem>)

/** One user turn as seen live. Pure value type + reducer so it is unit-testable without Android. */
data class TurnState(
    val phase: Phase = Phase.Idle,
    val userText: String = "",
    val thoughts: String = "",
    val tools: List<ToolActivity> = emptyList(),
    val context: List<ContextCard> = emptyList(),
    val answer: String = "",
    val route: String? = null,
    val error: String? = null,
) {
    /** The last few lines of reasoning, for the scrolling "isi pikiran" view. */
    fun recentThoughts(maxChars: Int = 600): String =
        if (thoughts.length <= maxChars) thoughts else "…" + thoughts.takeLast(maxChars).substringAfter(' ')

    fun reduce(event: ServerEvent): TurnState = when (event) {
        is ServerEvent.Status -> when (event.state) {
            "thinking" -> copy(phase = Phase.Thinking)
            "executing" -> copy(phase = Phase.Acting)
            "failed" -> copy(phase = Phase.Failed)
            else -> this // "completed" is followed by the reply
        }
        is ServerEvent.Thought -> copy(
            phase = if (phase == Phase.Answering) phase else Phase.Thinking,
            thoughts = (thoughts + event.text).takeLast(MAX_THOUGHTS),
        )
        is ServerEvent.Tool -> {
            val existing = tools.indexOfFirst { it.id == event.id && event.id.isNotEmpty() }
            val updated = if (existing >= 0) {
                tools.toMutableList().also {
                    val old = it[existing]
                    it[existing] = old.copy(running = event.running, label = event.label.ifEmpty { old.label })
                }
            } else {
                tools + ToolActivity(event.id, event.title, event.label, event.emoji, event.running)
            }
            copy(phase = if (event.running) Phase.Acting else Phase.Thinking, tools = updated.takeLast(MAX_TOOLS))
        }
        is ServerEvent.Context -> copy(context = (context + ContextCard(event.query, event.items)).takeLast(MAX_CONTEXT))
        is ServerEvent.Delta -> copy(phase = Phase.Answering, answer = answer + event.text)
        is ServerEvent.Reply -> copy(phase = Phase.Done, answer = event.text, route = event.route)
        is ServerEvent.Error -> copy(phase = Phase.Failed, error = event.message)
        else -> this
    }

    companion object {
        const val MAX_THOUGHTS = 4000
        const val MAX_TOOLS = 8
        const val MAX_CONTEXT = 4
    }
}
