"""Server usage for the owner (home screen of the app, dashboard, Hermes' host_metrics tool).

Read from /proc and the data volume, which inside the container show the whole host: CPU busy % (from
/proc/stat between two readings), load, memory, swap, disk and uptime. No docker socket is needed.
"""

import asyncio
import os
import shutil
import time

_last: dict = {"at": 0.0, "cpu": None}  # previous /proc/stat reading


def cpu_times(stat_line: str) -> tuple[int, int]:
    """'cpu  user nice system idle iowait irq softirq steal …' → (busy, total). Pure."""
    v = [int(x) for x in stat_line.split()[1:9]]
    idle = v[3] + v[4]
    return sum(v) - idle, sum(v)


def busy_pct(before: tuple[int, int], after: tuple[int, int]) -> float:
    busy, total = after[0] - before[0], after[1] - before[1]
    return round(100.0 * busy / total, 1) if total > 0 else 0.0


def meminfo(text: str) -> dict:
    """/proc/meminfo → GB values. Pure."""
    kb = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if v.strip():
            kb[k] = int(v.split()[0])
    gb = lambda k: round(kb.get(k, 0) / 1024 / 1024, 2)
    return {"total": gb("MemTotal"), "used": round(gb("MemTotal") - gb("MemAvailable"), 2),
            "swap_total": gb("SwapTotal"), "swap_used": round(gb("SwapTotal") - gb("SwapFree"), 2)}


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


async def snapshot() -> dict:
    now = time.monotonic()
    first = _read("/proc/stat").splitlines()[0]
    if _last["cpu"] is None or now - _last["at"] > 60:  # no recent reading: sample over half a second
        before = cpu_times(first)
        await asyncio.sleep(0.5)
        first = _read("/proc/stat").splitlines()[0]
    else:
        before = _last["cpu"]
    after = cpu_times(first)
    _last.update(at=time.monotonic(), cpu=after)
    mem = meminfo(_read("/proc/meminfo"))
    du = shutil.disk_usage("/data") if os.path.isdir("/data") else shutil.disk_usage("/")
    load = _read("/proc/loadavg").split()[:3]
    return {
        "cpu_pct": busy_pct(before, after), "cpu_cores": os.cpu_count(), "load": [float(x) for x in load],
        "memory_gb": {"total": mem["total"], "used": mem["used"],
                      "pct": round(100 * mem["used"] / mem["total"], 1) if mem["total"] else 0},
        "swap_gb": {"total": mem["swap_total"], "used": mem["swap_used"]},
        "disk_gb": {"total": round(du.total / 1e9, 1), "used": round((du.total - du.free) / 1e9, 1),
                    "pct": round(100 * (du.total - du.free) / du.total, 1)},
        "uptime_h": round(float(_read("/proc/uptime").split()[0]) / 3600, 1),
    }
