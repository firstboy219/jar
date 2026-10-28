"""Server operations for the owner: who is using the CPU and memory right now, and "Netralkan" (ADR-029).

Netralkan frees the server without losing anything important: every running or queued task is STOPPED
(not deleted) with what it had done so far, so the owner can retry it — it continues from there — or close
it. Background work (self-improvement, flow watcher, situations) then stays quiet for 15 minutes. On the
host, infra/scripts/ops.sh restarts Hermes (frees its browser/agent memory; its data stays on disk) and moves
swap back into RAM when there is room. Memories, chats, documents, passwords and settings are never touched.

Per-container usage comes from infra/scripts/usage-collector.sh (docker stats on the host, every 10 s),
because jarvis-core deliberately has no docker socket.

Background work (owner, 2026-10-21): JARVIS' own work — self-improvement, flow watcher, self-check,
situations, habits — starts only when none of the owner's work is running, one background task at a time
(workers.py). Everything done behind the scenes is listed for the owner (background()). There is no local
model any more (ADR-080): the CPU guard that held it back, and its orphan watchdog, are gone.
"""

import asyncio
import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from . import audit, gateway, reports, workers

ROOT = Path("/data/ops")
CALM_S = 15 * 60
_state = {"calm_until": 0.0, "cpu": 0.0}
_activity: deque = deque(maxlen=80)


def note(text: str) -> None:
    """One line in the owner-visible "Di balik layar" log."""
    _activity.appendleft({"at": datetime.now(timezone.utc).isoformat(), "text": text})

LABELS = {  # short: they share one line on the phone
    "jarvis-brain": "Hermes",
    "jarvis-ears": "Whisper (telinga)", "jarvis-core": "Inti JARVIS", "jarvis-tools": "Alat MCP", "jarvis-executor": "n8n",
    "jarvis-memory": "Qdrant", "jarvis-db": "Database", "jarvis-proxy": "Proxy", "jarvis-admin": "Web admin",
}


def calm() -> bool:
    """True for a while after Netralkan: background work waits (the owner's own requests still run)."""
    return time.time() < _state["calm_until"]


def parse_stats(raw: dict, cores: int) -> list[dict]:
    """docker stats rows → per-service share of the whole server, busiest first. Pure, unit-tested."""
    def num(v: str) -> float:
        try:
            return float(str(v).strip().rstrip("%"))
        except ValueError:
            return 0.0

    def gb(v: str) -> float:
        used = str(v).split("/")[0].strip()
        for unit, f in (("GiB", 1.0), ("MiB", 1 / 1024), ("KiB", 1 / 1024 ** 2), ("B", 1 / 1024 ** 3)):
            if used.endswith(unit):
                return round(num(used[: -len(unit)]) * f, 2)
        return 0.0
    rows = [{"name": c.get("Name", ""), "label": LABELS.get(c.get("Name", ""), c.get("Name", "")),
             "cpu_pct": round(num(c.get("CPUPerc", "0")) / max(cores, 1), 1), "mem_gb": gb(c.get("MemUsage", ""))}
            for c in raw.get("containers", [])]
    return sorted(rows, key=lambda r: (r["cpu_pct"], r["mem_gb"]), reverse=True)


def containers(cores: int) -> list[dict]:
    try:
        raw = json.loads((ROOT / "containers.json").read_text())
    except (OSError, ValueError):
        return []
    if time.time() - float(raw.get("at", 0)) > 90:
        return []  # the collector stopped: better nothing than stale numbers
    return parse_stats(raw, cores)


async def owner_busy() -> str:
    """Why the owner's work needs the CPU now ('' = it does not)."""
    from . import db
    n = await db.pool().fetchval(
        "SELECT count(*) FROM tasks WHERE kind IN ('owner', 'meeting') AND status IN ('queued', 'running')")
    if n:
        return f"{n} tugasmu berjalan"
    return ""


async def background_ok() -> tuple[bool, str]:
    """May JARVIS start its own (background) work now? (False, why) while not."""
    if calm():
        return False, "istirahat setelah Netralkan"
    if busy := await owner_busy():
        return False, f"mendahulukan pekerjaanmu ({busy})"
    return True, ""


async def tick() -> None:
    """Every ~20 s (main loop): the CPU reading the desk shows."""
    from . import hostinfo
    snap = await hostinfo.snapshot()
    _state["cpu"] = snap["cpu_pct"]


KIND_TEXT = {"owner": "tugasmu", "devteam": "tim dev", "meeting": "notulen rapat", "selfimprove": "perbaikan diri", "selfcheck": "cek diri harian",
             "routine": "belajar kebiasaanmu", "situation": "menyiapkan info situasi", "flowcheck": "pengawas alur", "watcher": "pantauan harga"}


async def background() -> dict:
    """Everything JARVIS does behind the scenes: now, scheduled, last 24 hours, and its log."""
    from . import db, hermes_studio
    now = time.time()
    ok, reason = await background_ok()
    tasks = await db.pool().fetch(
        """SELECT id, title, kind, status, extract(epoch FROM now() - coalesce(started_at, created_at))::int AS s
           FROM tasks WHERE status IN ('queued', 'running') ORDER BY id""")
    calls = [{"what": CALLERS.get(c["caller"], c["caller"]), "category": c.get("category"),
              "place": c.get("provider") or "-",
              "seconds": int(now - c["since"])} for c in gateway.inflight()]
    usage = await db.pool().fetch(
        """SELECT caller, count(*) AS n, round(sum(coalesce(latency_ms, 0)) / 60000.0, 1) AS minutes,
                  coalesce(sum(cost_usd), 0)::float AS cost
           FROM llm_usage WHERE at > now() - interval '24 hours' GROUP BY caller ORDER BY minutes DESC""")
    done = await db.pool().fetch(
        """SELECT kind, count(*) AS n, round(sum(extract(epoch FROM finished_at - started_at)) / 60.0, 1) AS minutes
           FROM tasks WHERE kind <> 'owner' AND finished_at > now() - interval '24 hours' GROUP BY kind""")
    try:
        cron = [{"what": f"jadwal Hermes: {j.get('name')}", "when": j.get("schedule")} for j in hermes_studio.cron_jobs()
                if j.get("enabled")]
    except Exception:
        cron = []
    return {
        "now": {"cpu_pct": _state["cpu"], "background_allowed": ok, "background_reason": reason,
                "ai_calls": calls,
                "tasks": [{"id": t["id"], "title": t["title"], "what": KIND_TEXT.get(t["kind"], t["kind"]),
                           "mine": t["kind"] in ("owner", "meeting"), "status": "menunggu giliran" if t["id"] in workers.waiting
                           or t["status"] == "queued" else "berjalan", "seconds": t["s"]} for t in tasks]},
        "schedule": [
            {"what": "pengawas alur — memeriksa obrolanmu", "when": "setelah obrolan jeda 2 menit, paling sering tiap 20 menit"},
            {"what": "cek diri harian", "when": "setiap hari 03.00 WIB"},
            {"what": "tinjauan efisiensi", "when": "Minggu 02.00 WIB"},
            {"what": "memahami situasimu", "when": "saat ada kejadian (pindah tempat, agenda, notifikasi penting)"},
            {"what": "perbaiki error berulang", "when": "bila error yang sama muncul ≥ 3× dalam 1 jam (maks 1×/hari)"},
            *cron],
        "rule": "Kerja latar hanya mulai saat tidak ada pekerjaanmu, dan satu per satu. Semua model AI jalan di cloud (OpenRouter), jadi tidak memakai CPU server.",
        "last24h": {"ai": [{"what": CALLERS.get(r["caller"], r["caller"]), "calls": r["n"], "minutes": float(r["minutes"] or 0),
                            "cost_usd": round(r["cost"], 4), "local": False} for r in usage],
                    "tasks": [{"what": KIND_TEXT.get(r["kind"], r["kind"]), "count": r["n"], "minutes": float(r["minutes"] or 0)}
                              for r in done]},
        "activity": list(_activity)[:40],
    }


CALLERS = {"chat": "ngobrol denganmu", "worker": "tugas", "hermes": "Hermes", "flowwatch": "pengawas alur",
           "awareness": "memahami situasimu", "meeting": "notulen rapat", "core": "menyusun laporan",
           "selfimprove": "perbaikan diri", "test": "uji model"}


def ai_calls(calls: list[dict]) -> list[str]:
    """In-flight AI calls → "pengawas alur", "ngobrol denganmu ×2" (who keeps the AI busy). Pure."""
    counts: dict[str, int] = {}
    for c in calls:
        label = CALLERS.get(c.get("caller", ""), c.get("caller") or "lainnya")
        counts[label] = counts.get(label, 0) + 1
    return [f"{k} ×{n}" if n > 1 else k for k, n in counts.items()]


async def who() -> dict:
    """What JARVIS is doing with the CPU: the owner's work, background work, and who waits for a turn."""
    tasks = await workers.active()
    return {"running": [{"id": t["id"], "title": t["title"], "kind": t["kind"], "category": t["category"]}
                        for t in tasks if t["status"] == "running" and t["id"] not in workers.waiting],
            "waiting": len([t for t in tasks if t["id"] in workers.waiting or t["status"] == "queued"]),
            "calm": calm(), "stopped": len(await workers.stopped()), "ai": ai_calls(gateway.inflight())}


async def relieve(actor: str) -> dict:
    from . import hostinfo
    before = await hostinfo.snapshot()
    stopped = await workers.stop_all(actor)
    _state["calm_until"] = time.time() + CALM_S
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "relieve.result").unlink(missing_ok=True)
    tmp = ROOT / ".relieve.tmp"
    tmp.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "actor": actor}))
    tmp.rename(ROOT / "relieve.request")  # infra/scripts/ops.sh (root) does the host part
    await audit.record(actor, "ops.relieve", None, stopped=[t["id"] for t in stopped])
    note(f"Netralkan oleh pemilik: {len(stopped)} tugas dihentikan & disimpan; kerja latar istirahat 15 menit.")
    asyncio.create_task(_report(before, stopped))
    return {"stopped": [{"id": t["id"], "title": t["title"]} for t in stopped], "calm_minutes": CALM_S // 60,
            "before": {"cpu_pct": before["cpu_pct"], "memory_gb": before["memory_gb"]}}


async def _report(before: dict, stopped: list[dict]) -> None:
    from . import hostinfo
    host = ""
    for _ in range(36):  # the host step takes up to ~2 minutes (Hermes restart)
        await asyncio.sleep(5)
        try:
            host = json.loads((ROOT / "relieve.result").read_text()).get("summary", "")
            break
        except (OSError, ValueError):
            continue
    await asyncio.sleep(10)
    after = await hostinfo.snapshot()
    owner = [t for t in stopped if t["kind"] == "owner"]
    text = (f"Server sudah dinetralkan. CPU {before['cpu_pct']:.0f}% → {after['cpu_pct']:.0f}%, RAM "
            f"{before['memory_gb']['used']:.1f} → {after['memory_gb']['used']:.1f} GB. "
            + (f"{len(stopped)} tugas kuhentikan dan kusimpan" + (f", termasuk {len(owner)} milikmu" if owner else "")
               + " — pilih Ulangi atau Tutup di daftar tugas. " if stopped else "Tidak ada tugas yang sedang berjalan. ")
            + "Pekerjaan latar belakangku istirahat 15 menit. " + (host or ""))
    await reports._create(None, "system", text.strip())
