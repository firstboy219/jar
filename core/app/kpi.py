"""Blueprint v2 §15: how well is JARVIS doing? Task success, verified results, recovery, skill reuse, cost, manual
interventions, latency — over the last N days, from what is already recorded (tasks, episodes, capabilities, llm_usage, audit)."""

from . import db


def pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


async def summary(days: int = 7) -> dict:
    days = max(1, min(int(days), 90))
    pool = db.pool()
    t = await pool.fetchrow(
        """SELECT count(*) FILTER (WHERE status = 'completed') AS done, count(*) FILTER (WHERE status = 'failed') AS failed,
                  count(*) FILTER (WHERE recovered > 0) AS recovered, count(*) FILTER (WHERE recovered > 0 AND status = 'completed') AS recovered_ok,
                  count(*) FILTER (WHERE status = 'completed' AND plan IS NOT NULL) AS planned,
                  count(*) FILTER (WHERE status = 'completed' AND artifacts @> '[{"type": "verification", "ok": true}]'::jsonb) AS verified,
                  coalesce(avg(cost_usd) FILTER (WHERE status = 'completed'), 0)::float AS avg_cost,
                  coalesce(sum(cost_usd), 0)::float AS total_cost,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM finished_at - started_at))
                      FILTER (WHERE status = 'completed' AND finished_at IS NOT NULL AND started_at IS NOT NULL) AS median_s
           FROM tasks WHERE kind = 'owner' AND created_at > now() - make_interval(days => $1)""", days)
    caps = await pool.fetchrow(
        """SELECT coalesce(sum(runs) FILTER (WHERE kind = 'skill'), 0) AS skill_runs,
                  count(*) FILTER (WHERE kind = 'skill' AND runs > 0) AS skills_used,
                  count(*) FILTER (WHERE kind = 'skill' AND tested AND own) AS tested_own,
                  coalesce(sum(success_n) FILTER (WHERE kind = 'skill'), 0) AS ok, coalesce(sum(fail_n) FILTER (WHERE kind = 'skill'), 0) AS bad
           FROM capabilities WHERE status <> 'deprecated'""")
    learned = await pool.fetchval(
        "SELECT count(*) FROM skill_drafts WHERE status = 'published' AND updated_at > now() - make_interval(days => $1)", days)
    manual = await pool.fetchval(
        """SELECT count(*) FROM audit_events WHERE at > now() - make_interval(days => $1)
             AND action IN ('task.retried', 'task.closed', 'task.stopped', 'task.cancelled')""", days)
    approvals_n = await pool.fetchval("SELECT count(*) FROM approvals WHERE created_at > now() - make_interval(days => $1)", days)
    chat = await pool.fetchval(
        """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) FROM llm_usage
           WHERE category = 'ngobrol' AND ok AND caller = 'chat' AND at > now() - make_interval(days => $1)""", days)
    fail = await pool.fetchrow(
        """SELECT count(*) FILTER (WHERE NOT ok AND coalesce(error, '') NOT LIKE '%402%') AS failed, count(*) AS total
           FROM llm_usage WHERE caller <> 'test' AND at > now() - make_interval(days => $1)""", days)
    finished = t["done"] + t["failed"]
    return {
        "days": days,
        "tugas": {"selesai": t["done"], "gagal": t["failed"], "tingkat_sukses_pct": pct(t["done"], finished),
                  "diperiksa_dengan_bukti_pct": pct(t["verified"], t["planned"]),
                  "gagal_lalu_pulih": t["recovered"], "pulih_pct": pct(t["recovered_ok"], t["recovered"]),
                  "biaya_rata_rata_usd": round(t["avg_cost"], 5), "biaya_total_usd": round(t["total_cost"], 4),
                  "median_durasi_dtk": int(t["median_s"]) if t["median_s"] is not None else None},
        "skill": {"dipakai_kali": int(caps["skill_runs"]), "skill_yang_dipakai": caps["skills_used"],
                  "teruji_buatan_sendiri": caps["tested_own"], "dipelajari_periode_ini": learned,
                  "tingkat_sukses_pct": pct(int(caps["ok"]), int(caps["ok"]) + int(caps["bad"]))},
        "intervensi_manual": {"tugas_diulang_ditutup_dihentikan": manual, "permintaan_persetujuan": approvals_n},
        "model": {"median_balasan_chat_ms": int(chat) if chat is not None else None,
                  "panggilan_gagal_pct": pct(fail["failed"], fail["total"])},
    }
