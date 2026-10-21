"""Server operations for the owner: who is using the CPU and memory right now, and "Netralkan" (ADR-029).

Netralkan frees the server without losing anything important: every running or queued task is STOPPED
(not deleted) with what it had done so far, so the owner can retry it — it continues from there — or close
it. Background work (self-improvement, flow watcher, situations) then stays quiet for 15 minutes. On the
host, infra/scripts/ops.sh restarts Hermes (frees its browser/agent memory; its data stays on disk),
restarts the local worker model only if it is still busy, and moves swap back into RAM when there is room.
Memories, chats, documents, passwords and settings are never touched.

Per-container usage comes from infra/scripts/usage-collector.sh (docker stats on the host, every 10 s),
because jarvis-core deliberately has no docker socket.

Background work (owner, 2026-10-21): JARVIS' own work — self-improvement, flow watcher, self-check,
situations, habits — starts only when none of the owner's work is running, one background task at a time
(workers.py). The first version also required CPU < 50% and held the worker model to 2 of 4 threads; the owner
removed that limit the same day (it made background work slower without freeing anything the owner needs: the
worker model already runs at idle priority). A watchdog stops the worker model when it keeps computing an
answer nobody waits for any more (seen: 286% CPU with no task). Everything done behind the scenes is listed
for the owner (background()).
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
WORKER_CPUS = 4.0  # the worker model may use every thread (it runs at idle priority; docker --cpus applied by usage-collector.sh)
ORPHAN_CPU, ORPHAN_TICKS = 25.0, 3  # worker model busy with nobody waiting for 3 checks (~60 s) = orphan
OWNER_CALLERS = ("chat", "meeting")
_state = {"calm_until": 0.0, "cpu": 0.0, "worker_cpus": None, "orphan_ticks": 0, "reset_at": 0.0}
_activity: deque = deque(maxlen=80)


def note(text: str) -> None:
    """One line in the owner-visible "Di balik layar" log."""
    _activity.appendleft({"at": datetime.now(timezone.utc).isoformat(), "text": text})

LABELS = {  # short: they share one line on the phone
    "jarvis-llm-worker": "AI kerja lokal", "jarvis-llm-chat": "AI ngobrol lokal", "jarvis-brain": "Hermes",
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
    if any(c.get("caller") in OWNER_CALLERS and c.get("provider") == gateway.LOCAL_WORKER for c in gateway.inflight()):
        return "kamu sedang dilayani"
    return ""


async def background_ok() -> tuple[bool, str]:
    """May JARVIS start its own (background) work now? (False, why) while not."""
    if calm():
        return False, "istirahat setelah Netralkan"
    if busy := await owner_busy():
        return False, f"mendahulukan pekerjaanmu ({busy})"
    return True, ""


def worker_policy(owner: str) -> tuple[float, str]:
    """How many CPU threads the local worker model may use: all of them. Pure."""
    return WORKER_CPUS, f"semua inti, prioritas paling rendah ({owner})" if owner else "semua inti, prioritas paling rendah"


def orphaned(worker_cpu: float, inflight: list[dict]) -> bool:
    """The worker model computes while no call is waiting for it. Pure."""
    return worker_cpu >= ORPHAN_CPU and not any(c.get("provider") == gateway.LOCAL_WORKER for c in inflight)


async def tick() -> None:
    """Every ~20 s (main loop): CPU reading, the worker model's CPU limit, the orphan watchdog."""
    from . import hostinfo
    snap = await hostinfo.snapshot()
    _state["cpu"] = snap["cpu_pct"]
    cpus, why = worker_policy(await owner_busy())
    if cpus != _state["worker_cpus"]:
        _state["worker_cpus"] = cpus
        ROOT.mkdir(parents=True, exist_ok=True)
        tmp = ROOT / ".policy.tmp"
        tmp.write_text(json.dumps({"worker_cpus": cpus, "why": why}))
        tmp.rename(ROOT / "policy.json")  # usage-collector.sh applies it (docker update --cpus)
        note(f"Model AI kerja lokal: {why}.")
    worker = next((c for c in containers(snap["cpu_cores"] or 1) if c["name"] == "jarvis-llm-worker"), None)
    if worker and orphaned(worker["cpu_pct"], gateway.inflight()):
        _state["orphan_ticks"] += 1
    else:
        _state["orphan_ticks"] = 0
    if _state["orphan_ticks"] >= ORPHAN_TICKS and time.time() - _state["reset_at"] > 600:
        _state.update(orphan_ticks=0, reset_at=time.time())
        (ROOT / ".reset.tmp").write_text(json.dumps({"at": time.time()}))
        (ROOT / ".reset.tmp").rename(ROOT / "worker-reset.request")
        note(f"Penjaga: model AI kerja lokal memakai {worker['cpu_pct']:.0f}% CPU untuk permintaan yang tidak ditunggu "
             "siapa pun — kuhentikan dan kumulai ulang (cache-nya kupulihkan).")
        await audit.record("jarvis-core", "ops.worker_orphan_reset", None, cpu=worker["cpu_pct"])
        asyncio.create_task(_restore_after_reset())


async def _restore_after_reset() -> None:
    for _ in range(30):
        await asyncio.sleep(10)
        if (ROOT / "worker-reset.result").exists():
            break
    for _ in range(12):
        if await gateway.restore_worker_slot():
            return
        await asyncio.sleep(10)


KIND_TEXT = {"owner": "tugasmu", "meeting": "notulen rapat", "selfimprove": "perbaikan diri", "selfcheck": "cek diri harian",
             "routine": "belajar kebiasaanmu", "situation": "menyiapkan info situasi", "flowcheck": "pengawas alur"}


async def background() -> dict:
    """Everything JARVIS does behind the scenes: now, scheduled, last 24 hours, and its log."""
    from . import db, hermes_studio
    now = time.time()
    ok, reason = await background_ok()
    tasks = await db.pool().fetch(
        """SELECT id, title, kind, status, extract(epoch FROM now() - coalesce(started_at, created_at))::int AS s
           FROM tasks WHERE status IN ('queued', 'running') ORDER BY id""")
    calls = [{"what": CALLERS.get(c["caller"], c["caller"]), "category": c.get("category"),
              "place": "lokal (CPU server)" if str(c.get("provider", "")).startswith("lokal") else (c.get("provider") or "-"),
              "seconds": int(now - c["since"])} for c in gateway.inflight()]
    usage = await db.pool().fetch(
        """SELECT caller, count(*) AS n, round(sum(coalesce(latency_ms, 0)) / 60000.0, 1) AS minutes,
                  coalesce(sum(cost_usd), 0)::float AS cost, bool_or(provider LIKE 'lokal%') AS local
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
                "worker_cpus": _state["worker_cpus"], "worker_cpu_why": worker_policy(await owner_busy())[1],
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
        "rule": "Kerja latar hanya mulai saat tidak ada pekerjaanmu, dan satu per satu. Tidak ada batas CPU: model AI kerja lokal "
                "memakai semua inti, tapi berprioritas paling rendah sehingga layanan lain tidak terganggu.",
        "last24h": {"ai": [{"what": CALLERS.get(r["caller"], r["caller"]), "calls": r["n"], "minutes": float(r["minutes"] or 0),
                            "cost_usd": round(r["cost"], 4), "local": r["local"]} for r in usage],
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
    for _ in range(36):  # the host step takes up to ~2 minutes (Hermes restart, maybe the worker model)
        await asyncio.sleep(5)
        try:
            host = json.loads((ROOT / "relieve.result").read_text()).get("summary", "")
            break
        except (OSError, ValueError):
            continue
    if "AI kerja lokal" in host:  # the worker model restarted: put Hermes' warm prompt cache back
        for _ in range(12):
            if await gateway.restore_worker_slot():
                break
            await asyncio.sleep(10)
    await asyncio.sleep(10)
    after = await hostinfo.snapshot()
    owner = [t for t in stopped if t["kind"] == "owner"]
    text = (f"Server sudah dinetralkan. CPU {before['cpu_pct']:.0f}% → {after['cpu_pct']:.0f}%, RAM "
            f"{before['memory_gb']['used']:.1f} → {after['memory_gb']['used']:.1f} GB. "
            + (f"{len(stopped)} tugas kuhentikan dan kusimpan" + (f", termasuk {len(owner)} milikmu" if owner else "")
               + " — pilih Ulangi atau Tutup di daftar tugas. " if stopped else "Tidak ada tugas yang sedang berjalan. ")
            + "Pekerjaan latar belakangku istirahat 15 menit. " + (host or ""))
    await reports._create(None, "system", text.strip())
