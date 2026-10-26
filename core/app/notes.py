"""The owner's notes & task list (ADR-060) — the app's "Catatan" tab and /notes/ on the web.

A page holds blocks; a to-do block is a task, so "Hari ini / Minggu ini / Semua / Selesai" are queries over every page's to-dos.
Two pages always exist: 📥 Inbox (quick notes — "catat …" by voice lands there) and ✅ Tugas saya (to-dos added without a page).
A finished meeting becomes a page: summary, decisions, open questions, and its action items as to-dos (who, due date).
Saves are versioned: a page edited on two devices answers the stale one with 409 and the current page, never a silent overwrite.
"""

import json
import re
import secrets
from datetime import date, timedelta

from . import audit, db

TYPES = ("p", "h1", "h2", "h3", "bullet", "number", "todo", "quote", "code", "callout", "divider", "toggle")
MAX_BLOCKS, MAX_TEXT, MAX_TITLE = 2000, 10_000, 200
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
SPECIAL = {"inbox": ("📥", "Inbox"), "tasks": ("✅", "Tugas saya")}


class NotesError(ValueError):
    pass


class Stale(Exception):
    def __init__(self, page: dict):
        self.page = page


def new_id() -> str:
    return secrets.token_urlsafe(9)


def clean_block(b: dict) -> dict | None:
    """One block as stored (pure; unit-tested): unknown types become paragraphs, every field is bounded, junk is dropped."""
    if not isinstance(b, dict):
        return None
    t = b.get("type") if b.get("type") in TYPES else "p"
    out = {"id": b["id"] if isinstance(b.get("id"), str) and _ID.match(b["id"]) else new_id(), "type": t,
           "text": str(b.get("text") or "")[:MAX_TEXT]}
    indent = b.get("indent")
    if isinstance(indent, int) and 0 < indent <= 4:
        out["indent"] = indent
    if t == "todo":
        out["checked"] = bool(b.get("checked"))
        if isinstance(b.get("due"), str) and _DATE.match(b["due"]):
            out["due"] = b["due"]
        if isinstance(b.get("priority"), int) and 1 <= b["priority"] <= 3:
            out["priority"] = b["priority"]
        if b.get("who"):
            out["who"] = str(b["who"])[:60]
    if t == "code" and b.get("lang"):
        out["lang"] = str(b["lang"])[:20]
    if t == "callout" and b.get("emoji"):
        out["emoji"] = str(b["emoji"])[:8]
    if t == "toggle" and b.get("open"):
        out["open"] = True
    return out


def clean_blocks(blocks) -> list[dict]:
    if not isinstance(blocks, list):
        raise NotesError("blocks harus berupa daftar")
    if len(blocks) > MAX_BLOCKS:
        raise NotesError(f"halaman terlalu panjang (> {MAX_BLOCKS} blok)")
    out, seen = [], set()
    for b in blocks:
        c = clean_block(b)
        if not c:
            continue
        if c["id"] in seen:
            c["id"] = new_id()
        seen.add(c["id"])
        out.append(c)
    return out


def _page(r) -> dict:
    d = dict(r)
    if isinstance(d.get("blocks"), str):
        d["blocks"] = json.loads(d["blocks"])
    return d


async def ensure_special(kind: str) -> dict:
    icon, title = SPECIAL[kind]
    row = await db.pool().fetchrow("SELECT * FROM note_pages WHERE kind = $1", kind)
    if row:
        if row["archived"]:
            row = await db.pool().fetchrow("UPDATE note_pages SET archived = false WHERE id = $1 RETURNING *", row["id"])
        return _page(row)
    row = await db.pool().fetchrow(
        "INSERT INTO note_pages (kind, title, icon, pinned) VALUES ($1, $2, $3, true) ON CONFLICT DO NOTHING RETURNING *", kind, title, icon)
    return _page(row or await db.pool().fetchrow("SELECT * FROM note_pages WHERE kind = $1", kind))


async def list_pages(archived: bool = False) -> list[dict]:
    await ensure_special("inbox")
    await ensure_special("tasks")
    rows = await db.pool().fetch(
        """SELECT id, parent_id, title, icon, kind, meeting_id, pinned, archived, version, created_at, updated_at,
                  (SELECT count(*) FROM jsonb_array_elements(blocks) b WHERE b->>'type' = 'todo' AND NOT coalesce((b->>'checked')::bool, false)) AS open_tasks,
                  left((SELECT string_agg(b->>'text', ' ') FROM (SELECT b FROM jsonb_array_elements(blocks) b WHERE b->>'text' <> '' LIMIT 3) x), 160) AS preview
           FROM note_pages WHERE archived = $1
           ORDER BY CASE kind WHEN 'inbox' THEN 0 WHEN 'tasks' THEN 1 ELSE 2 END, pinned DESC, updated_at DESC""", archived)
    return [dict(r) for r in rows]


async def get(page_id: str) -> dict | None:
    try:
        row = await db.pool().fetchrow("SELECT * FROM note_pages WHERE id = $1::uuid", page_id)
    except Exception:
        return None
    return _page(row) if row else None


async def create(title: str = "", icon: str = "", parent_id: str | None = None, blocks=None, actor: str = "owner",
                 kind: str = "page", meeting_id: str | None = None) -> dict:
    row = await db.pool().fetchrow(
        """INSERT INTO note_pages (title, icon, parent_id, blocks, kind, meeting_id) VALUES ($1, $2, $3::uuid, $4, $5, $6::uuid) RETURNING *""",
        (title or "").strip()[:MAX_TITLE], (icon or "")[:8], parent_id or None, clean_blocks(blocks or []), kind, meeting_id)
    await audit.record(actor, "notes.created", f"note:{row['id']}")
    return _page(row)


async def save(page_id: str, title: str, icon: str, blocks, version: int, actor: str = "owner") -> dict:
    """The editor's save. version is the one the editor started from; another device's newer save makes this one Stale."""
    clean = clean_blocks(blocks)
    row = await db.pool().fetchrow(
        """UPDATE note_pages SET title = $2, icon = $3, blocks = $4, version = version + 1, updated_at = now()
           WHERE id = $1::uuid AND version = $5 RETURNING *""", page_id, (title or "").strip()[:MAX_TITLE], (icon or "")[:8], clean, version)
    if row:
        return _page(row)
    cur = await get(page_id)
    if not cur:
        raise NotesError("halaman tidak ditemukan")
    raise Stale(cur)


async def patch(page_id: str, actor: str = "owner", **fields) -> dict:
    allowed = {k: v for k, v in fields.items() if k in ("pinned", "archived", "title", "icon", "parent_id") and v is not None}
    if not allowed:
        cur = await get(page_id)
        if not cur:
            raise NotesError("halaman tidak ditemukan")
        return cur
    if allowed.get("parent_id") == page_id:
        raise NotesError("halaman tidak bisa menjadi induknya sendiri")
    sets, vals = [], []
    for k, v in allowed.items():
        vals.append(v if k != "parent_id" else (v or None))
        sets.append(f"{k} = ${len(vals) + 1}" + ("::uuid" if k == "parent_id" else ""))
    row = await db.pool().fetchrow(f"UPDATE note_pages SET {', '.join(sets)}, updated_at = now() WHERE id = $1::uuid RETURNING *", page_id, *vals)
    if not row:
        raise NotesError("halaman tidak ditemukan")
    if allowed.get("archived"):
        await audit.record(actor, "notes.archived", f"note:{page_id}")
    return _page(row)


async def delete(page_id: str, actor: str = "owner") -> bool:
    """Only a page already in the trash is deleted for good (the special pages never are)."""
    r = await db.pool().execute("DELETE FROM note_pages WHERE id = $1::uuid AND archived AND kind NOT IN ('inbox', 'tasks')", page_id)
    ok = r.endswith("1")
    if ok:
        await audit.record(actor, "notes.deleted", f"note:{page_id}")
    return ok


# ---------- tasks: the to-do blocks of every page ----------

def in_view(task: dict, view: str, today: date) -> bool:
    """Which task list a to-do belongs to (pure; unit-tested). Views: today, week, upcoming, overdue, nodate, all, done."""
    if view == "done":
        return task.get("checked", False)
    if task.get("checked"):
        return False
    due = date.fromisoformat(task["due"]) if task.get("due") else None
    return {"all": True, "nodate": due is None, "overdue": bool(due and due < today), "today": bool(due and due <= today),
            "week": bool(due and due <= today + timedelta(days=7)), "upcoming": bool(due and due > today)}.get(view, True)


def sort_key(task: dict) -> tuple:
    """Overdue and soon first, then high priority, then those without a date (pure)."""
    return (task.get("checked", False), task.get("due") or "9999-99-99", -(task.get("priority") or 0), task.get("text", ""))


async def tasks(view: str = "all", today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = await db.pool().fetch(
        """SELECT p.id AS page_id, p.title AS page_title, p.icon AS page_icon, p.kind AS page_kind, b AS block
           FROM note_pages p, jsonb_array_elements(p.blocks) b WHERE NOT p.archived AND b->>'type' = 'todo' AND b->>'text' <> ''""")
    out = []
    for r in rows:
        b = json.loads(r["block"]) if isinstance(r["block"], str) else r["block"]
        t = {"page_id": str(r["page_id"]), "page_title": r["page_title"], "page_icon": r["page_icon"], "page_kind": r["page_kind"],
             "id": b["id"], "text": b.get("text", ""), "checked": bool(b.get("checked")), "due": b.get("due"),
             "priority": b.get("priority"), "who": b.get("who")}
        if in_view(t, view, today):
            out.append(t)
    out.sort(key=sort_key)
    return out[:500]


async def set_block(page_id: str, block_id: str, actor: str = "owner", **fields) -> dict:
    """Change one block from a task list (tick it, a due date, a priority) without opening its page."""
    page = await get(page_id)
    if not page:
        raise NotesError("halaman tidak ditemukan")
    for b in page["blocks"]:
        if b.get("id") == block_id:
            for k in ("checked", "due", "priority", "text", "who"):
                if k in fields and fields[k] is not None:
                    b[k] = fields[k]
            if fields.get("due") == "":
                b.pop("due", None)
            if fields.get("priority") == 0:
                b.pop("priority", None)
            break
    else:
        raise NotesError("tugas tidak ditemukan di halaman itu")
    return await save(page_id, page["title"], page["icon"], page["blocks"], page["version"], actor)


_WHEN = re.compile(r"\s*(?:,\s*)?(?:untuk\s+|tenggat\s+|deadline\s+|paling lambat\s+)?(hari ini|nanti malam|besok lusa|lusa|besok|minggu depan|pekan depan)\s*[.!]*$",
                   re.IGNORECASE)


def parse_due(text: str, today: date | None = None) -> tuple[str, str | None]:
    """'telepon pak budi besok' → ('telepon pak budi', <tomorrow>) — the dates people say (pure; unit-tested)."""
    today = today or date.today()
    m = _WHEN.search(text or "")
    if not m:
        return (text or "").strip(), None
    days = {"hari ini": 0, "nanti malam": 0, "besok": 1, "lusa": 2, "besok lusa": 2, "minggu depan": 7, "pekan depan": 7}[m.group(1).lower()]
    return text[:m.start()].strip(" ,"), (today + timedelta(days=days)).isoformat()


async def add_task(text: str, due: str | None = None, priority: int | None = None, actor: str = "owner") -> dict:
    page = await ensure_special("tasks")
    block = clean_block({"type": "todo", "text": text, "due": due, "priority": priority})
    saved = await save(str(page["id"]), page["title"], page["icon"], page["blocks"] + [block], page["version"], actor)
    return {"page_id": str(saved["id"]), "task": block}


async def add_note(text: str, title: str = "", actor: str = "owner") -> dict:
    """A quick note: into the Inbox (one dated line), or a page of its own when it has a title."""
    if title:
        page = await create(title, "📝", None, [{"type": "p", "text": line} for line in text.splitlines() if line.strip()] or [{"type": "p", "text": text}], actor)
        return {"page_id": str(page["id"]), "title": page["title"]}
    page = await ensure_special("inbox")
    blocks = page["blocks"] + [{"type": "p", "text": f"{date.today().isoformat()} — {text.strip()}"}]
    saved = await save(str(page["id"]), page["title"], page["icon"], blocks, page["version"], actor)
    return {"page_id": str(saved["id"]), "title": saved["title"]}


async def search(q: str) -> list[dict]:
    q = (q or "").strip()
    if len(q) < 2:
        return []
    like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
    rows = await db.pool().fetch(
        """SELECT p.id, p.title, p.icon, p.kind,
                  (SELECT b->>'text' FROM jsonb_array_elements(p.blocks) b WHERE b->>'text' ILIKE $1 LIMIT 1) AS hit
           FROM note_pages p WHERE NOT p.archived AND (p.title ILIKE $1 OR EXISTS (SELECT 1 FROM jsonb_array_elements(p.blocks) b WHERE b->>'text' ILIKE $1))
           ORDER BY p.updated_at DESC LIMIT 30""", like)
    return [dict(r) for r in rows]


# ---------- meeting minutes ----------

def meeting_blocks(meeting: dict, summary: dict) -> list[dict]:
    """A finished meeting as page blocks (pure; unit-tested): summary, decisions, action items as to-dos, open questions, topics."""
    out = [{"type": "callout", "emoji": "🎙", "text": f"Rapat {meeting.get('started', '')}".strip()
            + (f" · peserta: {', '.join(meeting.get('participants') or [])}" if meeting.get("participants") else "")}]
    if summary.get("ringkasan"):
        out += [{"type": "h2", "text": "Ringkasan"}, {"type": "p", "text": summary["ringkasan"]}]
    if summary.get("keputusan"):
        out += [{"type": "h2", "text": "Keputusan"}] + [{"type": "bullet", "text": str(k)} for k in summary["keputusan"]]
    items = summary.get("action_items") or []
    if items:
        out.append({"type": "h2", "text": "Action items"})
        for a in items:
            due = a.get("tenggat") if isinstance(a.get("tenggat"), str) and _DATE.match(a.get("tenggat") or "") else None
            text = str(a.get("apa") or "").strip() + (f" (tenggat: {a['tenggat']})" if a.get("tenggat") and not due else "")
            out.append({"type": "todo", "text": text, "who": str(a.get("siapa") or "")[:60], "due": due})
    if summary.get("pertanyaan"):
        out += [{"type": "h2", "text": "Pertanyaan terbuka"}] + [{"type": "bullet", "text": str(q)} for q in summary["pertanyaan"]]
    if summary.get("topik"):
        out += [{"type": "h3", "text": "Topik"}, {"type": "p", "text": ", ".join(str(t) for t in summary["topik"])}]
    if meeting.get("document_id"):
        out.append({"type": "p", "text": f"Dokumen notulen (.docx): /api/v1/documents/{meeting['document_id']}"})
    return clean_blocks(out)


async def from_meeting(meeting_id: str, actor: str = "jarvis-meeting") -> dict | None:
    """The page of a finished meeting (made once; asking again returns the same page)."""
    have = await db.pool().fetchrow("SELECT * FROM note_pages WHERE meeting_id = $1::uuid", meeting_id)
    if have:
        return _page(have)
    m = await db.pool().fetchrow("SELECT id, title, summary, context, started_at, document_id FROM meetings WHERE id = $1::uuid AND status = 'done'",
                                 meeting_id)
    if not m:
        return None
    summary = m["summary"] if isinstance(m["summary"], dict) else json.loads(m["summary"] or "{}")
    info = {"started": m["started_at"].strftime("%d %b %Y %H:%M") if m["started_at"] else "", "participants": list((m["context"] or {}).get("participants") or []),
            "document_id": str(m["document_id"]) if m["document_id"] else None}
    return await create(f"Rapat: {m['title']}", "🎙", None, meeting_blocks(info, summary), actor, kind="meeting", meeting_id=str(m["id"]))


async def meetings_to_import() -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT m.id, m.title, m.done_at FROM meetings m WHERE m.status = 'done'
           AND NOT EXISTS (SELECT 1 FROM note_pages p WHERE p.meeting_id = m.id) ORDER BY m.done_at DESC NULLS LAST LIMIT 30""")
    return [dict(r) for r in rows]
