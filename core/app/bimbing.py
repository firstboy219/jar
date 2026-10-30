"""Bimbing (ADR-087, mockup 8): JARVIS guides the owner step by step while he shares his screen — "cara mengaktifkan e-Faktur di aplikasi
ini?" — looking at what is on the screen each time it changes and saying the ONE next thing to do (and where it is), until the goal is
reached. JARVIS only guides here; the owner taps.

The phone shares its screen and reads its text itself (ML Kit) and sends it with each change; each next step is a master-flow job (the
light brain usually; Hermes escalates when it fails). The phone shows the instruction in a floating bubble and speaks it."""

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import db, hub, master
from .appauth import owner

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/guide"
MAX_STEPS = 40


class GuideError(ValueError):
    pass


def screen_key(text: str) -> str:
    return hashlib.sha1(" ".join((text or "").split()).lower().encode()).hexdigest()[:16]


def clean_step(d: dict) -> dict:
    status = str((d or {}).get("status") or "lanjut").lower()
    try:
        left = max(0, min(int((d or {}).get("sisa") or 0), 30))
    except (TypeError, ValueError):
        left = 0
    return {"instruksi": str((d or {}).get("instruksi") or "")[:300], "target": str((d or {}).get("target") or "")[:80],
            "posisi": str((d or {}).get("posisi") or "")[:40], "status": status if status in ("lanjut", "selesai", "buntu") else "lanjut",
            "catatan": str((d or {}).get("catatan") or "")[:200], "sisa": left}


def approved_app(app: str) -> str | None:
    """The approved app (phone_agent.APPS id) the guided screen belongs to — only those can be done for him. Pure."""
    from .phone_agent import APPS
    a = (app or "").strip().lower()
    if not a:
        return None
    for k, v in APPS.items():
        if a == k or a in [p.lower() for p in v.get("packages", [])] or a == str(v.get("label", "")).lower():
            return k
    return None


async def start(goal: str) -> dict:
    await db.pool().execute("UPDATE guide_sessions SET status = 'stopped', updated_at = now() WHERE status = 'active'")
    gid = await db.pool().fetchval("INSERT INTO guide_sessions (goal) VALUES ($1) RETURNING id", goal.strip()[:300])
    await hub.broadcast({"type": "guide", "id": gid, "mode": "start", "goal": goal[:300]})   # the phone starts sharing and reading its screen
    return {"id": gid, "goal": goal}


async def step(gid: int, screen_text: str, app: str = "") -> dict:
    g = await db.pool().fetchrow("SELECT * FROM guide_sessions WHERE id = $1", gid)
    if not g or g["status"] != "active":
        raise GuideError("bimbingan ini sudah selesai")
    steps = list(g["steps"] or [])
    key = screen_key(screen_text)
    if steps and steps[-1].get("screen") == key:
        return {**steps[-1], "same_screen": True}   # nothing changed on the screen: the same advice
    if len(steps) >= MAX_STEPS:
        raise GuideError("bimbingan terlalu panjang — mulai lagi dengan tujuan yang lebih kecil")
    history = "\n".join(f"{i + 1}. {s['instruksi']}" for i, s in enumerate(steps[-8:]))
    msgs = [{"role": "system", "content": (
        "Kamu membimbing pemilik langkah demi langkah di HP-nya. Dari teks layar sekarang, beri SATU langkah berikutnya yang paling jelas menuju tujuan: "
        "apa yang diketuk/diisi, tulisannya persis seperti di layar, dan letaknya (atas/bawah/kiri/kanan/tengah). Jangan pernah menyuruh mengetik PIN/OTP ke "
        "kamu; pemilik mengisinya sendiri. Bila tujuan sudah tercapai → status selesai; bila layar tidak berhubungan → status buntu dengan saran. JSON: "
        "{\"instruksi\": \"kalimat pendek\", \"target\": \"teks tombol/kolom\", \"posisi\": \"kanan atas\", \"status\": \"lanjut|selesai|buntu\", \"catatan\": \"\", "
        "\"sisa\": perkiraan berapa langkah lagi setelah ini}")},
        {"role": "user", "content": f"Tujuan: {g['goal']}\nAplikasi: {app or '?'}\nLangkah sebelumnya:\n{history or '-'}\n\nLAYAR SEKARANG:\n{screen_text[:6000]}"}]
    r = await master.run(master.Job("bimbing", "langkah", f"langkah berikutnya: {g['goal'][:80]}", trigger="event", messages=msgs, json_out=True,
                                    no_free=True, max_tokens=300))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise GuideError(r.get("error") or "tidak bisa membaca langkah berikutnya")
    s = {**clean_step(r["result"]), "screen": key, "n": len(steps) + 1, "lane": r.get("lane"), "app": app[:120]}
    s["total"] = s["n"] + (0 if s["status"] == "selesai" else s["sisa"])
    steps.append(s)
    await db.pool().execute("UPDATE guide_sessions SET steps = $2, status = CASE WHEN $3 THEN 'done' ELSE status END, updated_at = now() WHERE id = $1",
                            gid, steps, s["status"] == "selesai")
    await hub.broadcast({"type": "guide", "id": gid, "mode": "step", **{k: s[k] for k in ("instruksi", "target", "posisi", "status", "n", "total")}})
    return s


async def do_for_me(gid: int) -> dict:
    """"Kerjakan untukku": the rest done by JARVIS on the phone — only in an approved app (the phone agent's rules: no PIN, no top-up)."""
    g = await db.pool().fetchrow("SELECT goal, steps, status FROM guide_sessions WHERE id = $1", gid)
    if not g or g["status"] != "active":
        raise GuideError("bimbingan ini sudah selesai")
    app = approved_app(next((x.get("app") for x in reversed(g["steps"] or []) if x.get("app")), ""))
    if not app:
        raise GuideError("JARVIS hanya boleh mengerjakan di aplikasi yang disetujui (Gojek, Kopi Kenangan, Qpon, JobStreet) — di sini kamu yang mengetuk")
    if app == "pluang":   # buying/selling always goes through Investasi: the options, the limit, the price guard and his admin password
        raise GuideError("transaksi Pluang hanya lewat layar Investasi (dengan password admin) — di sini kamu yang mengetuk")
    r = await master.run(master.Job("bimbing", "kerjakan", f"kerjakan untuk pemilik: {g['goal'][:80]}", trigger="owner", phone={"app": app, "goal": g["goal"]},
                                    title=g["goal"][:80], no_free=True))
    if r["status"] == "failed":
        raise GuideError(r.get("error") or "tidak bisa mulai")
    await stop(gid)
    return {"status": r["status"], "task_id": r.get("task_id"), "app": app}


async def stop(gid: int) -> None:
    await db.pool().execute("UPDATE guide_sessions SET status = 'stopped', updated_at = now() WHERE id = $1 AND status = 'active'", gid)
    await hub.broadcast({"type": "guide", "id": gid, "mode": "stop"})


class StartIn(BaseModel):
    goal: str = Field(min_length=4, max_length=300)


class StepIn(BaseModel):
    screen_text: str = Field(min_length=1, max_length=20000)
    app: str = Field(default="", max_length=120)


@router.get(API)
async def api_list(device: dict = Depends(owner)):
    rows = await db.pool().fetch("SELECT id, goal, status, steps, created_at, updated_at FROM guide_sessions ORDER BY id DESC LIMIT 10")
    return {"sessions": [dict(r) for r in rows], "active": next((dict(r) for r in rows if r["status"] == "active"), None)}


@router.post(API)
async def api_start(body: StartIn, device: dict = Depends(owner)):
    return await start(body.goal)


@router.post(API + "/{gid}/do")
async def api_do(gid: int, device: dict = Depends(owner)):
    try:
        return await do_for_me(gid)
    except GuideError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/{gid}/step")
async def api_step(gid: int, body: StepIn, device: dict = Depends(owner)):
    try:
        return await step(gid, body.screen_text, body.app)
    except GuideError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/{gid}/repeat")
async def api_repeat(gid: int, device: dict = Depends(owner)):
    """Say the last step again (the phone shows and speaks it)."""
    steps = await db.pool().fetchval("SELECT steps FROM guide_sessions WHERE id = $1", gid) or []
    if not steps:
        raise HTTPException(409, "belum ada langkah")
    s = steps[-1]

    async def say():
        await hub.broadcast({"type": "guide", "id": gid, "mode": "step", **{k: s.get(k) for k in ("instruksi", "target", "posisi", "status", "n")}})
        return s
    await master.run(master.Job("bimbing", "ulangi", "ulangi langkah bimbingan", skill=say))
    return s


@router.post(API + "/{gid}/stop")
async def api_stop(gid: int, device: dict = Depends(owner)):
    await stop(gid)
    return {"ok": True}
