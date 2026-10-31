"""Pengelola penyimpanan (owner 2026-10-31: "buat kan fitur khusus untuk manager storage sehingga saya tahu mana saja yg bisa dihapus atau
dizip").

The host measures and cleans (infra/scripts/storage.py, run as root by jarvis-storage.path): jarvis-core has no docker socket and cannot
write most of those folders, on purpose. Here: what the app shows (each space user, grouped; what is safe to remove and what it costs,
what is zipped instead, what stays and why; the music collection from the database), a fresh measurement on request and every 6 hours,
and the cleanup — only the host's whitelisted ids, after the owner's approval with the phone's lock, through the master flow (a skill, no
AI). When the disk runs low he is told once a day."""

import asyncio
import json
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, audit, db, hub, master, reports
from .appauth import actor, owner, require_password
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/storage"
ROOT = __import__("pathlib").Path("/data/ops")
STALE_S = 6 * 3600
LOW_FREE = 0.12            # below 12% free he is told
HOST_WAIT_S = 120          # a request still lying there after this: the host watcher is not installed
_told: dict = {"day": None}


class StorageError(ValueError):
    pass


def state() -> dict | None:
    try:
        return json.loads((ROOT / "storage.json").read_text())
    except (OSError, ValueError):
        return None


def pending() -> dict | None:
    """The request the host has not picked up yet (with its age), or None."""
    path = ROOT / "storage.request"
    try:
        return {**json.loads(path.read_text()), "age_s": time.time() - path.stat().st_mtime}
    except (OSError, ValueError):
        return None


def request(action: str, **extra) -> dict:
    ROOT.mkdir(parents=True, exist_ok=True)
    req = {"action": action, "at": time.time(), **extra}
    tmp = ROOT / ".storage-request.tmp"
    tmp.write_text(json.dumps(req))
    tmp.rename(ROOT / "storage.request")
    return req


def summary(st: dict | None) -> dict:
    """Groups for the screen, biggest first; what can be freed. Pure."""
    if not st:
        return {"groups": [], "can_free": 0, "can_zip": 0}
    groups: dict[str, dict] = {}
    for it in st.get("items", []):
        g = groups.setdefault(it["group"], {"name": it["group"], "bytes": 0, "items": []})
        g["bytes"] += it["bytes"]
        g["items"].append(it)
    for g in groups.values():
        g["items"].sort(key=lambda i: (i["action"] is None, -i["bytes"]))
    items = st.get("items", [])
    return {"groups": sorted(groups.values(), key=lambda g: -g["bytes"]),
            "can_free": sum(i["bytes"] for i in items if i["action"] == "hapus"),
            "can_zip": sum(i["bytes"] for i in items if i["action"] == "zip")}


def low(st: dict | None) -> bool:
    d = (st or {}).get("disk") or {}
    return bool(d.get("total")) and d["free"] / d["total"] < LOW_FREE


async def music() -> dict:
    row = await db.pool().fetchrow("SELECT count(*) FILTER (WHERE status = 'siap') AS ready, coalesce(sum(size_bytes) FILTER (WHERE status = 'siap'), 0) AS bytes, "
                                   "count(*) FILTER (WHERE status = 'gagal') AS failed FROM music_library")
    return dict(row)


async def overview() -> dict:
    st, req = state(), pending()
    return {"state": st, **summary(st), "age_s": time.time() - st["at"] if st else None, "low": low(st),
            "pending": req, "host_missing": bool(req and req["age_s"] > HOST_WAIT_S), "music": await music()}


async def clean(items: list[str], who: str) -> dict:
    st = state()
    known = {i["id"] for i in (st or {}).get("items", []) if i["action"]}
    chosen = [i for i in dict.fromkeys(items) if i in known]
    if not chosen:
        raise StorageError("pilih yang ingin dibersihkan")
    if pending():
        raise StorageError("masih ada permintaan yang sedang dikerjakan server — tunggu sebentar")
    try:
        req = request("clean", items=chosen, actor=who)
    except OSError as e:
        raise StorageError(f"folder ops server tidak bisa ditulis: {e}")
    await audit.record(who, "storage.clean", "storage", items=chosen)
    asyncio.create_task(_watch(req["at"]))
    return {"ok": True, "items": chosen}


async def _watch(at: float) -> None:
    """Tell him how much came free once the host is done (Docker cleanups can take minutes)."""
    for _ in range(360):
        await asyncio.sleep(5)
        last = (state() or {}).get("last") or {}
        if last.get("request") == at:
            gb = last.get("freed", 0) / 1024 ** 3
            bad = [i["label"] for i in last.get("items", []) if not i.get("ok")]
            await hub.broadcast({"type": "notify", "title": "Penyimpanan dibersihkan", "kind": "info", "route": "#/penyimpanan",
                                 "text": f"{gb:.1f} GB lega." + (f" Gagal: {', '.join(bad)}." if bad else "")})
            await hub.broadcast({"type": "storage"})
            return


@appclock.every(3600, "storage.watch")
async def _tick() -> None:
    """A fresh measurement every 6 hours; a low disk is said once a day."""
    st = state()
    if not pending() and (not st or time.time() - st.get("at", 0) > STALE_S):
        try:
            request("scan")
        except OSError as e:   # the ops folder is not mounted (tests, a fresh install): nothing to ask yet
            log.warning("storage scan request: %s", e)
    today = datetime.now(WIB).date().isoformat()
    if low(st) and _told["day"] != today:
        _told["day"] = today
        d = st["disk"]
        await reports._create(None, "system", f"Ruang disk server tinggal {d['free'] / 1024 ** 3:.0f} GB "
                              f"({d['free'] / d['total']:.0%}). {summary(st)['can_free'] / 1024 ** 3:.0f} GB bisa dibersihkan dengan aman di Penyimpanan.")


# ---------- API ----------

@router.get(API)
async def api_storage(device: dict = Depends(owner)):
    return await overview()


@router.post(API + "/scan")
async def api_storage_scan(device: dict = Depends(owner)):
    if not pending():
        try:
            request("scan")
        except OSError as e:
            raise HTTPException(503, f"folder ops server tidak bisa ditulis: {e}")
    return await overview()


class CleanIn(BaseModel):
    items: list[str] = Field(min_length=1, max_length=20)
    password: str = Field(default="", max_length=200)


@router.post(API + "/clean")
async def api_storage_clean(body: CleanIn, device: dict = Depends(owner)):
    """Removing is his decision: the phone's lock first; then the master flow hands it to the host."""
    await require_password(device, body.password, "storage:clean")
    who = actor(device)
    r = await master.run(master.Job("sistem", "bersihkan-disk", f"bersihkan penyimpanan: {', '.join(body.items)[:120]}",
                                    trigger="owner", skill=lambda: clean(body.items, who)))
    if r["status"] != "done":
        raise HTTPException(409, str(r.get("error") or "gagal"))
    return r["result"]
