package online.cosger.jarvis.ui

import kotlinx.serialization.json.JsonObject
import online.cosger.jarvis.ui.stage.d
import online.cosger.jarvis.ui.stage.i
import online.cosger.jarvis.ui.stage.obj

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
) {
    val ramPct: Double get() = if (ramTotalGb > 0) 100 * ramUsedGb / ramTotalGb else 0.0

    companion object {
        fun parse(o: JsonObject): ServerUsage {
            val mem = o["memory_gb"].obj()
            val disk = o["disk_gb"].obj()
            val tasks = o["tasks"].obj()
            val ai = o["ai"].obj()
            val load = (o["load"] as? kotlinx.serialization.json.JsonArray)?.firstOrNull()
            return ServerUsage(
                cpuPct = o.d("cpu_pct") ?: 0.0,
                load1 = (load as? kotlinx.serialization.json.JsonPrimitive)?.content?.toDoubleOrNull() ?: 0.0,
                cores = o.i("cpu_cores") ?: 0,
                ramUsedGb = mem.d("used") ?: 0.0, ramTotalGb = mem.d("total") ?: 0.0,
                swapUsedGb = o["swap_gb"].obj().d("used") ?: 0.0,
                diskPct = disk.d("pct") ?: 0.0, diskUsedGb = disk.d("used") ?: 0.0, diskTotalGb = disk.d("total") ?: 0.0,
                ownerTasks = tasks.i("owner") ?: 0, backgroundTasks = tasks.i("background") ?: 0,
                aiSpentUsd = ai.d("spent_usd") ?: 0.0, aiBudgetUsd = ai.d("budget_usd") ?: 0.0,
            )
        }
    }
}
