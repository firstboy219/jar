"""Hermes Studio: what Hermes set up for itself — schedules, its own skills, kanban boards, its memory —
shown read-only in the web admin and the APK (Hermes' data directory is mounted read-only at /hermes).

Also delivers scheduled-job results: Hermes' cron has no messaging platform to deliver to in JARVIS
("no delivery target resolved" on 2026-10-17), so each new run output becomes a spoken report here,
unless the job answered "[SILENT]".
"""

import json
import logging
import re
import sqlite3
from pathlib import Path

from . import db, reports

log = logging.getLogger("jarvis-core.hermes_studio")
ROOT = Path("/hermes")
STATE_KEY = "hermes:cron_delivered"


def _read(path: Path, limit: int = 20000) -> str:
    try:
        return path.read_text(errors="replace")[:limit]
    except OSError:
        return ""


def cron_jobs() -> list[dict]:
    try:
        jobs = json.loads(_read(ROOT / "cron" / "jobs.json", 2_000_000) or "{}").get("jobs", [])
    except ValueError:
        return []
    return [{"id": j.get("id"), "name": j.get("name"), "enabled": j.get("enabled"),
             "schedule": j.get("schedule_display") or (j.get("schedule") or {}).get("display"),
             "next_run": j.get("next_run_at"), "last_run": j.get("last_run_at"), "last_status": j.get("last_status"),
             "prompt": (j.get("prompt") or "")[:600]} for j in jobs]


def own_skills() -> list[dict]:
    """Skills Hermes wrote itself (not in the bundled manifest)."""
    bundled = {line.split(":", 1)[0] for line in _read(ROOT / "skills" / ".bundled_manifest", 500_000).splitlines()}
    out = []
    for f in sorted((ROOT / "skills").glob("**/SKILL.md")) if (ROOT / "skills").is_dir() else []:
        name = f.parent.name
        if name in bundled:
            continue
        text = _read(f, 4000)
        m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
        out.append({"name": name, "path": str(f.parent.relative_to(ROOT / "skills")),
                    "description": (m.group(1).strip() if m else "")[:300],
                    "modified": f.stat().st_mtime})
    return out


def kanban(limit: int = 50) -> list[dict]:
    path = ROOT / "kanban.db"
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        rows = conn.execute(
            "SELECT title, status, assignee, coalesce(project_id, '') FROM tasks ORDER BY created_at DESC LIMIT ?",
            (limit,)).fetchall()
        conn.close()
    except sqlite3.Error as e:
        log.debug("kanban unreadable: %s", e)
        return []
    return [{"title": r[0], "status": r[1], "assignee": r[2], "board": r[3] or "umum"} for r in rows]


def studio() -> dict:
    return {"cron": cron_jobs(), "skills": own_skills(), "kanban": kanban(),
            "memory": _read(ROOT / "memories" / "MEMORY.md", 6000), "user": _read(ROOT / "memories" / "USER.md", 4000)}


def _response(md: str) -> str:
    m = re.search(r"^## Response\s*\n(.*)", md, re.MULTILINE | re.DOTALL)
    return (m.group(1) if m else "").strip()


async def deliver_cron_outputs() -> int:
    """Turn new cron run outputs into spoken reports. Returns how many were delivered."""
    out_dir = ROOT / "cron" / "output"
    if not out_dir.is_dir():
        return 0
    seen = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", STATE_KEY)
    files = sorted(out_dir.glob("*/*.md"))
    if seen is None:  # first start: everything already there is history, not news
        await _remember([f"{f.parent.name}/{f.name}" for f in files])
        return 0
    seen = set(seen or [])
    names = {j["id"]: j["name"] for j in cron_jobs()}
    delivered, new = 0, []
    for f in files:
        key = f"{f.parent.name}/{f.name}"
        if key in seen:
            continue
        new.append(key)
        text = _response(_read(f))
        if not text or text.strip() == "[SILENT]":
            continue
        name = names.get(f.parent.name) or "terjadwal"
        await reports._create(None, "cron", f"Dari jadwal {name}: {text[:700]}")
        delivered += 1
    if new:
        await _remember(sorted(seen | set(new))[-2000:])
    return delivered


async def _remember(keys: list[str]) -> None:
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ($1, $2)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", STATE_KEY, keys)
