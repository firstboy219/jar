package online.cosger.jarvis.ui

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import online.cosger.jarvis.ui.stage.arr
import online.cosger.jarvis.ui.stage.b
import online.cosger.jarvis.ui.stage.d
import online.cosger.jarvis.ui.stage.i
import online.cosger.jarvis.ui.stage.obj
import online.cosger.jarvis.ui.stage.s

/** The server at a glance (GET /api/v1/console/server-usage), for the strip on the home screen. */
data class ServerUsage(
    val cpuPct: Double,
    val load1: Double,
    val cores: Int,
    val ramUsedGb: Double,
    val ramTotalGb: Double,
    val swapUsedGb: Double,
    val diskPct: Double,
    val diskUsedGb: Double,
    val diskTotalGb: Double,
    val ownerTasks: Int,
    val backgroundTasks: Int,
    val aiSpentUsd: Double,
    val aiBudgetUsd: Double,
    val top: List<Consumer> = emptyList(),
    val doing: List<Job> = emptyList(),
    val waiting: Int = 0,
    val calm: Boolean = false,
    val stopped: Int = 0,
    val aiCalls: List<String> = emptyList(),
) {
    /** One service and its share of the whole server (CPU % of all cores, memory in GB). */
    data class Consumer(val label: String, val cpuPct: Double, val memGb: Double)

    /** Work JARVIS is running right now — whose it is decides who gets the CPU first. */
    data class Job(val id: Long, val title: String, val owner: Boolean)

    val ramPct: Double get() = if (ramTotalGb > 0) 100 * ramUsedGb / ramTotalGb else 0.0

    /** "AI kerja lokal (Qwen 4B) 91% · Hermes (otak kerja) 3%" — the services that matter now. Pure. */
    fun busiest(n: Int = 2): String = top.filter { it.cpuPct >= 1 || it.memGb >= 1 }.take(n)
        .joinToString(" · ") { "${it.label} ${it.cpuPct.toInt()}%" }

    /** What that CPU is spent on: the owner's work first, then JARVIS' own, then who waits for a turn. Pure. */
    fun purpose(): String {
        val mine = doing.filter { it.owner }
        val own = doing.filterNot { it.owner }
        return buildList {
            mine.firstOrNull()?.let { add("tugasmu “${it.title.take(40)}”" + if (mine.size > 1) " +${mine.size - 1}" else "") }
            if (own.isNotEmpty()) add("${own.size} kerja latar JARVIS")
            if (waiting > 0) add("$waiting menunggu giliran")
            if (aiCalls.isNotEmpty()) add("AI: " + aiCalls.take(3).joinToString(", "))
            if (calm) add("latar istirahat")
        }.joinToString(" · ").ifEmpty { "tidak ada tugas berjalan" }
    }

    companion object {
        fun parse(o: JsonObject): ServerUsage {
            val mem = o["memory_gb"].obj()
            val disk = o["disk_gb"].obj()
            val tasks = o["tasks"].obj()
            val ai = o["ai"].obj()
            val who = o["who"].obj()
            val load = (o["load"] as? JsonArray)?.firstOrNull()
            return ServerUsage(
                cpuPct = o.d("cpu_pct") ?: 0.0,
                load1 = (load as? JsonPrimitive)?.content?.toDoubleOrNull() ?: 0.0,
                cores = o.i("cpu_cores") ?: 0,
                ramUsedGb = mem.d("used") ?: 0.0, ramTotalGb = mem.d("total") ?: 0.0,
                swapUsedGb = o["swap_gb"].obj().d("used") ?: 0.0,
                diskPct = disk.d("pct") ?: 0.0, diskUsedGb = disk.d("used") ?: 0.0, diskTotalGb = disk.d("total") ?: 0.0,
                ownerTasks = tasks.i("owner") ?: 0, backgroundTasks = tasks.i("background") ?: 0,
                aiSpentUsd = ai.d("spent_usd") ?: 0.0, aiBudgetUsd = ai.d("budget_usd") ?: 0.0,
                top = o["containers"].arr().map { it.obj() }.map { Consumer(it.s("label"), it.d("cpu_pct") ?: 0.0, it.d("mem_gb") ?: 0.0) },
                doing = who["running"].arr().map { it.obj() }.map { Job((it.i("id") ?: 0).toLong(), it.s("title"), it.s("kind") == "owner") },
                waiting = who.i("waiting") ?: 0,
                calm = who.b("calm"),
                stopped = who.i("stopped") ?: 0,
                aiCalls = who["ai"].arr().mapNotNull { (it as? JsonPrimitive)?.content },
            )
        }
    }
}
