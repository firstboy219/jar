"""Server operations for the owner: who is using the CPU and memory right now, and "Netralkan" (ADR-029).

Netralkan frees the server without losing anything important: every running or queued task is STOPPED
(not deleted) with what it had done so far, so the owner can retry it — it continues from there — or close
it. Background work (self-improvement, flow watcher, situations) then stays quiet for 15 minutes. On the
host, infra/scripts/ops.sh restarts Hermes (frees its browser/agent memory; its data stays on disk),
restarts the local worker model only if it is still busy, and moves swap back into RAM when there is room.
Memories, chats, documents, passwords and settings are never touched.

Per-container usage comes from infra/scripts/usage-collector.sh (docker stats on the host, every 10 s),
because jarvis-core deliberately has no docker socket.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import audit, gateway, reports, workers

ROOT = Path("/data/ops")
CALM_S = 15 * 60
_state = {"calm_until": 0.0}

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


CALLERS = {"chat": "ngobrol denganmu", "worker": "tugas", "hermes": "Hermes", "flowwatch": "pengawas alur",
           "awareness": "memahami situasimu", "meeting": "notulen rapat", "core": "menyusun laporan"}


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
