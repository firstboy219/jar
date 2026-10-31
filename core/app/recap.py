"""Rekap hari ini (ADR-087): when the owner gets home (or at 21.00), what the day was — what got done, what is still open — and the
action plan for tomorrow as real tasks in Catatan, each saying where it came from (a meeting, an email, a mission).

Gathering the day is a fixed procedure (tasks, meetings and their action items, missions, trips, and what other features add); writing it
is a job of the master flow. The recap is a note page of its own (kind 'recap'), one per day — written again, not duplicated, if it runs twice."""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends

from . import db, habits, home, hub, master, notes, setup_status
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/recap"
DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
CONTEXT: dict[str, Callable[[date], Awaitable[str]]] = {}   # other features' part of the day: name → async (day) -> text


def context(name: str):
    def wrap(fn):
        CONTEXT[name] = fn
        return fn
    return wrap


def due_of(text: str, today: date) -> str | None:
    """'besok', 'Jumat', '2026-11-03', 'minggu ini' → an ISO date (or None). Pure."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
        return t
    if t in ("hari ini",):
        return today.isoformat()
    if t == "besok":
        return (today + timedelta(days=1)).isoformat()
    if t == "lusa":
        return (today + timedelta(days=2)).isoformat()
    if t in ("minggu ini", "pekan ini"):
        return (today + timedelta(days=(4 - today.weekday()) % 7 or 7)).isoformat()
    if t in ("minggu depan", "pekan depan"):
        return (today + timedelta(days=7)).isoformat()
    for i, d in enumerate(DAYS):
        if t.startswith(d.lower()[:3]):
            ahead = (i - today.weekday()) % 7 or 7
            return (today + timedelta(days=ahead)).isoformat()
    return None


def blocks_for(data: dict, today: date) -> list[dict]:
    """The recap page: summary, done, still open, the action plan as to-dos (with due date and source), tomorrow. Pure."""
    b = [{"type": "callout", "text": data.get("ringkasan") or "Rekap hari ini."}]
    if data.get("selesai"):
        b.append({"type": "h2", "text": "Selesai"})
        b += [{"type": "bullet", "text": str(x)[:300]} for x in data["selesai"][:10]]
    if data.get("belum"):
        b.append({"type": "h2", "text": "Belum selesai"})
        b += [{"type": "bullet", "text": str(x)[:300]} for x in data["belum"][:10]]
    plan = [p for p in data.get("action_plan") or [] if isinstance(p, dict) and p.get("tugas")]
    if plan:
        b.append({"type": "h2", "text": "Action plan"})
        for p in plan[:12]:
            src = f" — dari {p['dari']}" if p.get("dari") else ""
            b.append({"type": "todo", "text": f"{str(p['tugas'])[:240]}{src}", "due": due_of(str(p.get("tenggat") or ""), today),
                      "priority": 3 if p.get("penting") else None})
    if data.get("besok"):
        b.append({"type": "h2", "text": "Besok"})
        b.append({"type": "p", "text": str(data["besok"])[:400]})
    return b


async def gather(day: date) -> dict:
    """The day, from what JARVIS already knows (no AI)."""
    start = datetime(day.year, day.month, day.day, tzinfo=WIB)
    end = start + timedelta(days=1)
    tasks = await db.pool().fetch(
        """SELECT title, status, result FROM tasks WHERE company_id IS NULL AND dev_role IS NULL AND kind IN ('owner', 'feature')
           AND coalesce(finished_at, created_at) >= $1 AND coalesce(finished_at, created_at) < $2 ORDER BY id""", start, end)
    meet_pages = await db.pool().fetch("SELECT title, blocks FROM note_pages WHERE kind = 'meeting' AND created_at >= $1 AND created_at < $2", start, end)
    meetings = []
    for p in meet_pages:
        blocks = p["blocks"] or []
        todos = [x.get("text", "") for x in blocks if x.get("type") == "todo" and not x.get("checked")]
        decisions = [x.get("text", "") for x in blocks if x.get("type") in ("bullet", "callout")][:6]
        meetings.append({"title": p["title"], "todos": todos[:8], "points": decisions})
    open_tasks = [t for t in await notes.tasks("week", day) if not t.get("checked")]
    trips = await db.pool().fetch("SELECT direction, chosen, status FROM commute_trips WHERE created_at >= $1 AND created_at < $2", start, end)
    flow = await db.pool().fetchrow(
        "SELECT count(*) AS n, count(*) FILTER (WHERE lane = 'skill') AS no_ai, coalesce(sum(cost_usd), 0)::float AS cost FROM flow_runs WHERE started_at >= $1 AND started_at < $2",
        start, end)
    extra = []
    for name, fn in CONTEXT.items():
        try:
            if t := await fn(day):
                extra.append(f"{name}: {t}")
        except Exception:
            pass
    return {"tasks": [{"title": t["title"], "status": t["status"]} for t in tasks], "meetings": meetings,
            "open": [{"text": t["text"], "due": t.get("due"), "page": t.get("page_title")} for t in open_tasks[:20]],
            "trips": [{"direction": t["direction"], "dep": (t["chosen"] or {}).get("dep"), "status": t["status"]} for t in trips],
            "flow": dict(flow) if flow else {}, "extra": extra}


def prompt(g: dict, day: date) -> list[dict]:
    sys = ("Kamu menulis REKAP HARI INI untuk pemilik JARVIS, dalam Bahasa Indonesia yang hangat dan ringkas. Pakai HANYA data yang diberikan; "
           "jangan mengarang. Kembalikan JSON: {\"ringkasan\": \"2–3 kalimat: hari ini seperti apa dan satu hal paling mendesak besok\", "
           "\"selesai\": [\"…\"], \"belum\": [\"…\"], \"action_plan\": [{\"tugas\": \"kalimat perintah yang jelas\", \"tenggat\": \"besok|Jumat|YYYY-MM-DD\", "
           "\"dari\": \"rapat Tim Produk|email Finance|misi riset laptop\", \"penting\": true|false}] (dari item rapat yang belum selesai, tugas terbuka, "
           "dan hal yang belum beres; maks 8; jangan menggandakan tugas yang sudah ada di daftar terbuka), \"besok\": \"1 kalimat\"}")
    user = (f"Hari: {DAYS[day.weekday()]} {day.isoformat()}\n\nMisi/pekerjaan hari ini: {g['tasks']}\n\nRapat hari ini: {g['meetings']}\n\n"
            f"Tugas yang masih terbuka minggu ini: {g['open']}\n\nPerjalanan: {g['trips']}\n\nLainnya: {g['extra']}\n\n"
            f"JARVIS bekerja {g['flow'].get('n', 0)} kali hari ini ({g['flow'].get('no_ai', 0)} tanpa AI).")
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


async def compose(trigger: str = "owner", day: date | None = None) -> dict:
    day = day or datetime.now(WIB).date()
    g = await gather(day)
    r = await master.run(master.Job("rekap", "compose", "tulis rekap hari ini dan action plan besok", trigger=trigger,
                                    messages=prompt(g, day), json_out=True, max_tokens=1500))
    if r["status"] != "done":
        raise RuntimeError(r.get("error") or "rekap gagal")
    data = r["result"] if isinstance(r["result"], dict) else {}
    title = f"Rekap {DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
    blocks = blocks_for(data, day)
    existing = await db.pool().fetchrow("SELECT id, version, blocks FROM note_pages WHERE kind = 'recap' AND title = $1 AND NOT archived", title)
    if existing:   # keep what the owner already ticked off
        ticked = {x.get("text") for x in existing["blocks"] or [] if x.get("type") == "todo" and x.get("checked")}
        for b in blocks:
            if b["type"] == "todo" and b["text"] in ticked:
                b["checked"] = True
        page = await notes.save(str(existing["id"]), title, "🌙", blocks, existing["version"], "jarvis-recap")
    else:
        page = await notes.create(title, "🌙", None, blocks, "jarvis-recap", kind="recap")
    t0 = datetime(day.year, day.month, day.day, tzinfo=WIB)
    mail_done = await db.pool().fetchval("SELECT count(*) FROM inbox_items WHERE status = 'done' AND received_at >= $1::timestamptz - interval '2 days' AND received_at < $2", t0, t0 + timedelta(days=1))
    transport = await db.pool().fetchval("SELECT coalesce(sum(amount), 0)::float FROM money_tx WHERE realized AND category = 'transport' AND direction = 'out' AND at >= $1 AND at < $2",
                                         t0, t0 + timedelta(days=1))
    stats = {"tasks_done": sum(1 for t in g["tasks"] if t["status"] == "completed"), "meetings": len(g["meetings"]),
             "plan": sum(1 for b in blocks if b["type"] == "todo"), "no_ai": g["flow"].get("no_ai", 0), "runs": g["flow"].get("n", 0),
             "mail_done": int(mail_done or 0), "transport": transport}
    await db.pool().execute("""INSERT INTO settings_kv (key, value) VALUES ('recap:last', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                            {"day": day.isoformat(), "page_id": str(page["id"]), "data": data, "stats": stats, "lane": r.get("lane")})
    await hub.broadcast({"type": "notify", "title": "Rekap hari ini siap", "text": (data.get("ringkasan") or "")[:200], "kind": "info", "route": "#/rekap"})
    return {"page_id": str(page["id"]), "title": title, "data": data, "stats": stats, "lane": r.get("lane")}


async def last() -> dict | None:
    return await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'recap:last'")


@habits.action("recap.compose", "Rekap hari ini")
async def _habit(h: dict) -> dict:
    l = await last()
    if l and l.get("day") == datetime.now(WIB).date().isoformat() and h.get("key") == "malam.recap":
        return {"skipped": "rekap hari ini sudah dibuat"}
    r = await compose("habit")
    return {"page": r["page_id"]}


@home.provider("recap")
async def _home(m: home.Moment) -> list[dict]:
    if m.slot not in ("malam", "larut"):
        return []
    l = await last()
    if not l or l.get("day") != m.now.date().isoformat():
        return []
    return [{"id": "recap", "title": "Rekap hari ini", "sub": f"{l['stats'].get('plan', 0)} action plan sudah di Catatan", "route": "#/rekap",
             "icon": "recap", "tone": "cyan", "score": 50}]


@setup_status.check("rekap")
async def _ready() -> dict:
    return setup_status.ready()


@router.get(API)
async def api_recap(device: dict = Depends(owner)):
    l = await last()
    page = await notes.get(l["page_id"]) if l else None
    return {"recap": l, "page": page}


@router.post(API + "/now")
async def api_now(device: dict = Depends(owner)):
    return await compose("owner")
