package online.cosger.jarvis.ui

import online.cosger.jarvis.net.MediaItem
import online.cosger.jarvis.net.ServerEvent

/** One background worker as shown in the app: its status plus its own live "thought stream". */
data class Worker(
    val id: Long,
    val title: String,
    val status: String,
    val live: TurnState = TurnState(phase = Phase.Thinking),
) {
    val active: Boolean get() = status == "queued" || status == "running"
}

data class SpokenReport(
    val id: Long,
    val taskId: Long?,
    val text: String,
    val attempt: Int,
    val repeat: Boolean,
    val state: State = State.Waiting,
) {
    enum class State { Waiting, Spoken, Acknowledged, Unheard }
}

data class MediaShow(val seq: Long, val caption: String, val items: List<MediaItem>)

/** Workers, reports and shown media — what the main agent has delegated and what still needs attention. Pure reducer. */
data class Board(
    val workers: List<Worker> = emptyList(),
    val reports: List<SpokenReport> = emptyList(),
    val media: List<MediaShow> = emptyList(),
) {
    val activeWorkers: List<Worker> get() = workers.filter { it.active }
    /** Stopped by "Netralkan": kept, waiting for the owner to retry or close them. */
    val stoppedWorkers: List<Worker> get() = workers.filter { it.status == "stopped" }
    val openReports: List<SpokenReport> get() = reports.filter { it.state == SpokenReport.State.Waiting || it.state == SpokenReport.State.Spoken || it.state == SpokenReport.State.Unheard }

    fun reduce(e: ServerEvent): Board = when (e) {
        is ServerEvent.Tasks -> copy(workers = e.items.map { Worker(it.id, it.title, it.status) } +
            workers.filter { w -> !w.active && e.items.none { it.id == w.id } })
        is ServerEvent.Task -> {
            val existing = workers.find { it.id == e.id }
            val updated = existing?.copy(status = e.status, title = e.title.ifEmpty { existing.title })
                ?: Worker(e.id, e.title, e.status)
            copy(workers = (workers.filter { it.id != e.id } + updated).sortedBy { it.id }.takeLast(MAX_WORKERS))
        }
        is ServerEvent.TaskEvent -> copy(workers = workers.map {
            if (it.id == e.taskId) it.copy(live = it.live.reduce(e.event)) else it
        })
        is ServerEvent.Report -> {
            val r = SpokenReport(e.id, e.taskId, e.text, e.attempt, e.repeat)
            copy(reports = (reports.filter { it.id != e.id } + r).takeLast(MAX_REPORTS))
        }
        is ServerEvent.ReportAck -> withReport(e.id) { it.copy(state = SpokenReport.State.Acknowledged) }
        is ServerEvent.ReportUnheard -> withReport(e.id) { it.copy(state = SpokenReport.State.Unheard) }
        is ServerEvent.Media -> if (e.items.isEmpty()) this else copy(
            media = (listOf(MediaShow((media.firstOrNull()?.seq ?: 0) + 1, e.caption, e.items)) + media).take(MAX_MEDIA),
        )
        else -> this
    }

    fun dismissMedia(seq: Long): Board = copy(media = media.filter { it.seq != seq })

    fun markSpoken(id: Long): Board = withReport(id) {
        if (it.state == SpokenReport.State.Waiting) it.copy(state = SpokenReport.State.Spoken) else it
    }

    private fun withReport(id: Long, f: (SpokenReport) -> SpokenReport) =
        copy(reports = reports.map { if (it.id == id) f(it) else it })

    companion object {
        const val MAX_WORKERS = 20
        const val MAX_REPORTS = 20
        const val MAX_MEDIA = 10
    }
}
