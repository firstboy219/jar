"""Dongeng (ADR-087, mockup 22): a bedtime story for the owner's child, read aloud by him (or by JARVIS) — new every night, fitting the
child's age and the themes he likes, with a gentle lesson, never repeating last week's. The 20.00 habit at home offers tonight's story.

Writing it is a master-flow job (creative writing: Hermes picks the brain); the child's name stays out of the prompt unless he set it."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appsettings, db, habits, home, hub, master
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/story"
WORDS_PER_MIN = 110   # reading aloud, slowly, to a child


class StoryError(ValueError):
    pass


def pick_theme(themes: list[str], recent: list[str], wanted: str = "") -> str:
    """The theme for tonight: the one he asked for, else the one least told lately. Pure."""
    if wanted:
        return wanted
    pool = themes or ["petualangan"]
    return min(pool, key=lambda t: (sum(1 for r in recent if r == t), pool.index(t)))


def clean_story(d: dict) -> dict:
    paras = [str(p).strip()[:1500] for p in (d or {}).get("paragraf") or [] if str(p).strip()][:40]
    words = sum(len(p.split()) for p in paras)
    return {"judul": str((d or {}).get("judul") or "Dongeng malam ini")[:100], "paragraf": paras, "pesan": str((d or {}).get("pesan") or "")[:300],
            "tokoh": [str(x)[:60] for x in (d or {}).get("tokoh") or []][:6], "menit": max(1, round(words / WORDS_PER_MIN))}


async def compose(theme: str = "", trigger: str = "owner") -> dict:
    s = await appsettings.get("story")
    recent = [dict(r) for r in await db.pool().fetch("SELECT title, theme FROM stories ORDER BY id DESC LIMIT 14")]
    theme = pick_theme(s["themes"], [r["theme"] for r in recent], theme.strip())
    words = int(s["length_min"]) * WORDS_PER_MIN
    child = f"Tokoh utama boleh bernama {s['child_name']}." if s["child_name"] else "Jangan memakai nama anak sungguhan."
    msgs = [{"role": "system", "content": (
        f"Kamu pendongeng anak Indonesia. Tulis dongeng sebelum tidur untuk anak usia {s['child_age']} tahun, tema '{theme}', sekitar {words} kata, "
        "bahasa sederhana dan hangat, kalimat pendek untuk dibacakan, ada sedikit dialog dan suara (mis. 'krek-krek'), akhir yang menenangkan, nilai "
        f"kebaikan yang Islami tanpa menggurui. {child} Jangan mengulang judul ini: {[r['title'] for r in recent]}. Tidak ada kekerasan atau hal menakutkan. "
        "JSON: {\"judul\": \"…\", \"tokoh\": [\"…\"], \"paragraf\": [\"…\"], \"pesan\": \"pesan moral satu kalimat\"}")},
        {"role": "user", "content": f"Dongeng malam {datetime.now(WIB):%A} untuk anak {s['child_age']} tahun, tema {theme}."}]
    r = await master.run(master.Job("dongeng", "tulis", f"tulis dongeng anak tema {theme}", trigger=trigger, messages=msgs, json_out=True, max_tokens=2200))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise StoryError(r.get("error") or "dongeng gagal ditulis")
    d = clean_story(r["result"])
    if not d["paragraf"]:
        raise StoryError("dongengnya kosong")
    sid = await db.pool().fetchval("INSERT INTO stories (title, theme, data, run_id) VALUES ($1, $2, $3, $4) RETURNING id", d["judul"], theme, d, r["run_id"])
    return {"id": sid, "theme": theme, "lane": r.get("lane"), **d}


async def tonight() -> dict | None:
    r = await db.pool().fetchrow("SELECT * FROM stories WHERE created_at::date = (now() AT TIME ZONE 'Asia/Jakarta')::date ORDER BY id DESC LIMIT 1")
    return dict(r) if r else None


@habits.action("story.offer", "Dongeng untuk si kecil")
async def _habit(h: dict) -> dict:
    t = await tonight() or await compose(trigger="habit")
    title = t.get("title") or t.get("judul")
    await hub.broadcast({"type": "notify", "title": "Dongeng malam ini siap", "text": f"\"{title}\" — ±{(t.get('data') or t).get('menit', 5)} menit dibacakan.",
                         "kind": "info", "route": "#/dongeng"})
    return {"story": t["id"]}


@home.provider("story")
async def _home(m: home.Moment) -> list[dict]:
    if m.slot not in ("malam",):
        return []
    t = await tonight()
    return [{"id": "story", "title": "Dongeng malam ini", "sub": (t["title"] if t else "Buat dongeng untuk si kecil")[:80], "route": "#/dongeng",
             "icon": "book", "tone": "violet", "score": 44 if m.place == "rumah" else 22, "cta": "Baca"}]


class ComposeIn(BaseModel):
    theme: str = Field(default="", max_length=60)


class MarkIn(BaseModel):
    status: str = Field(pattern="^(read|liked|skipped)$")


@router.get(API)
async def api_list(device: dict = Depends(owner)):
    rows = await db.pool().fetch("SELECT id, title, theme, data, status, created_at FROM stories ORDER BY id DESC LIMIT 20")
    return {"tonight": await tonight(), "stories": [dict(r) for r in rows], "settings": await appsettings.get("story")}


@router.post(API)
async def api_compose(body: ComposeIn, device: dict = Depends(owner)):
    try:
        return await compose(body.theme, "owner")
    except StoryError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/{story_id}/mark")
async def api_mark(story_id: int, body: MarkIn, device: dict = Depends(owner)):
    await db.pool().execute("UPDATE stories SET status = $2, read_at = CASE WHEN $2 = 'read' THEN now() ELSE read_at END WHERE id = $1", story_id, body.status)
    return {"ok": True}
