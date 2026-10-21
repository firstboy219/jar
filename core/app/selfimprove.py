"""Self-check and self-improvement ("JARVIS mengecek dirinya sendiri dan memperbaiki kekurangannya").

A self-check worker gets a diagnostics bundle — its own self-description, health, and evidence of
recent shortcomings (errors, failed tasks, unheard reports, low-confidence speech, misunderstandings,
owner corrections) — and proposes improvements. Policy (KB: changes must be reviewable and reversible):
  stt_keyword — add a misheard term to speech recognition      → applied automatically
  lesson      — a short behavioural rule for the main agent    → applied automatically
  setting     — change a whitelisted runtime setting           → owner approval
  code        — anything needing a code change                 → recorded as a proposal for the developer
Everything is versioned in `improvements` and can be reverted from the web admin.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from . import approvals, audit, db, self_model
from .location import WIB

log = logging.getLogger("jarvis-core.selfimprove")

MAX_AUTO_PER_RUN = 5
# Runtime settings a self-check may propose (applied only after approval), with validators.
SETTINGS = {
    "deepgram_model": re.compile(r"^nova-[23](-[a-z]+)?$"),
    "endpointing_ms": re.compile(r"^(?:[5-9]\d\d|1[0-9]\d\d|2000)$"),
    "utterance_end_ms": re.compile(r"^(?:1[0-9]\d\d|2[0-9]\d\d|3000)$"),
    "quiet_hours": re.compile(r"^(([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d)?$"),
}


async def diagnostics(hours: int = 24) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.pool()
    errors = await q.fetch("SELECT left(content, 160) AS c FROM messages WHERE route = 'error' AND created_at > $1 ORDER BY id DESC LIMIT 10", since)
    failed = await q.fetch("SELECT title, left(coalesce(error, ''), 160) AS e FROM tasks WHERE status = 'failed' AND created_at > $1 LIMIT 10", since)
    unheard = await q.fetchval("SELECT count(*) FROM reports WHERE status = 'unheard' AND created_at > $1", since)
    low_conf = await q.fetch(
        """SELECT left(content, 120) AS c, stt_confidence AS k FROM messages
           WHERE role = 'user' AND stt_confidence IS NOT NULL AND stt_confidence < 0.8 AND created_at > $1
           ORDER BY id DESC LIMIT 15""", since)
    confused = await q.fetch(
        r"""SELECT left(u.content, 120) AS heard, left(a.content, 120) AS said FROM messages a
            JOIN LATERAL (SELECT content FROM messages u WHERE u.session_id = a.session_id AND u.role = 'user'
                          AND u.id < a.id ORDER BY u.id DESC LIMIT 1) u ON true
            WHERE a.role = 'assistant' AND a.created_at > $1
              AND a.content ~* '(tidak menangkap|belum menangkap|terpotong|tidak yakin maksud|belum paham|tidak punya informasi)'
            ORDER BY a.id DESC LIMIT 12""", since)
    corrections = await q.fetch(
        r"""SELECT left(content, 140) AS c FROM messages WHERE role = 'user' AND created_at > $1
            AND content ~* '^(bukan|salah|maksud saya|maksudku|nggak gitu|ga gitu|masa kamu)' ORDER BY id DESC LIMIT 10""", since)
    silent = await q.fetchval("SELECT count(*) FROM messages WHERE route = 'silent' AND created_at > $1", since)
    total = await q.fetchval("SELECT count(*) FROM messages WHERE role = 'user' AND created_at > $1", since)
    applied = await q.fetch("SELECT kind, summary FROM improvements WHERE status = 'applied' ORDER BY id DESC LIMIT 20")

    def block(title, rows, fmt):
        return f"{title}:\n" + ("\n".join(f"- {fmt(r)}" for r in rows) if rows else "- (tidak ada)")

    return "\n\n".join([
        "DESKRIPSI DIRI SAAT INI:\n" + await self_model.describe(full=True),
        f"STATISTIK {hours} JAM: {total} ucapan pemilik, {silent} sengaja tidak dijawab, {unheard} laporan tidak terdengar.",
        block("JAWABAN ERROR", errors, lambda r: r["c"]),
        block("TUGAS GAGAL", failed, lambda r: f"{r['title']}: {r['e']}"),
        block("UCAPAN DENGAN KEYAKINAN TRANSKRIP RENDAH", low_conf, lambda r: f"({r['k']:.2f}) {r['c']}"),
        block("SAAT KAMU TIDAK PAHAM / TIDAK TAHU", confused, lambda r: f"dengar: «{r['heard']}» → jawab: «{r['said']}»"),
        block("KOREKSI DARI PEMILIK", corrections, lambda r: r["c"]),
        block("PERBAIKAN YANG SUDAH BERLAKU", applied, lambda r: f"[{r['kind']}] {r['summary']}"),
    ])


SELFCHECK_TASK = """Kamu bertugas MENGECEK DIRI JARVIS dan mengusulkan perbaikan atas kekurangannya. {focus}

{diag}

Analisis polanya (bukan kasus tunggal): kata yang sering salah dengar (nama, istilah), kebiasaan menjawab \
yang membuat pemilik kesal, ketidaktahuan tentang diri sendiri, tugas yang sering gagal. Kamu juga boleh \
memakai self_info dan alat lain untuk memverifikasi. Jangan mengulang perbaikan yang sudah berlaku.

Jenis perbaikan:
- "stt_keyword": istilah yang sering salah didengar, field "term" (≤40 huruf, ejaan benar).
- "lesson": aturan perilaku singkat untuk agen utama (≤200 huruf), field "text".
- "setting": ubah setelan, field "key" (deepgram_model | endpointing_ms | utterance_end_ms | quiet_hours) dan "value".
- "code": butuh perubahan program oleh developer, field "summary" saja.

Akhiri HANYA dengan JSON:
{{"summary_for_owner": "2-3 kalimat lisan: apa yang kamu temukan dan perbaiki",
  "improvements": [{{"kind": "…", "reason": "…", ...}}]}}"""


async def start(focus: str = "", actor: str = "jarvis-core") -> dict:
    from . import workers
    focus_line = f"Fokus khusus dari pemilik: {focus}" if focus else "Pemeriksaan rutin harian."
    return await workers.spawn("Cek & perbaiki diri", SELFCHECK_TASK.format(focus=focus_line, diag=await diagnostics()),
                               "selfcheck", actor, kind="selfcheck")


async def apply(item: dict, task_id: int | None) -> dict:
    """Apply one proposed improvement according to policy. Returns the stored row."""
    kind, reason = item.get("kind"), str(item.get("reason") or "")[:300]
    if kind == "stt_keyword":
        term = str(item.get("term") or "").strip()
        if not (1 <= len(term) <= 40) or not re.fullmatch(r"[\w .'-]+", term):
            return {"skipped": "istilah tidak valid"}
        if await db.pool().fetchval("SELECT 1 FROM improvements WHERE kind = 'stt_keyword' AND status = 'applied' AND payload->>'term' ILIKE $1", term):
            return {"skipped": "sudah ada"}
        return await _store("stt_keyword", f"Kosakata suara: {term} — {reason}", {"term": term}, "applied", task_id)
    if kind == "lesson":
        text = str(item.get("text") or "").strip()
        if not (5 <= len(text) <= 200):
            return {"skipped": "pelajaran tidak valid"}
        return await _store("lesson", f"Pelajaran: {text}", {"text": text, "reason": reason}, "applied", task_id)
    if kind == "setting":
        key, value = str(item.get("key") or ""), str(item.get("value") or "").strip()
        if key not in SETTINGS or not SETTINGS[key].match(value):
            return {"skipped": "setelan tidak diizinkan"}
        row = await _store("setting", f"Ubah {key} → {value}: {reason}", {"key": key, "value": value}, "awaiting_approval", task_id)
        a = await approvals.create("setting_change", f"JARVIS ingin mengubah {key} menjadi {value}",
                                   {"key": key, "value": value, "reason": reason, "improvement_id": row["id"]},
                                   "jarvis-selfcheck", "low", idempotency_key=f"setting:{key}:{value}:{row['id']}")
        await db.pool().execute("UPDATE improvements SET approval_id = $2 WHERE id = $1", row["id"], a["id"])
        return row | {"approval_id": a["id"]}
    if kind == "code":
        summary = str(item.get("summary") or reason).strip()[:500]
        return await _store("code", summary, {"reason": reason}, "proposed", task_id) if summary else {"skipped": "kosong"}
    return {"skipped": f"jenis tidak dikenal: {kind}"}


async def _store(kind: str, summary: str, payload: dict, status: str, task_id: int | None) -> dict:
    row = await db.pool().fetchrow(
        """INSERT INTO improvements (kind, summary, payload, status, source_task, applied_at)
           VALUES ($1, $2, $3, $4, $5, CASE WHEN $4 = 'applied' THEN now() END) RETURNING *""",
        kind, summary[:500], payload, status, task_id)
    await audit.record("jarvis-selfcheck", f"improvement.{status}", f"improvement:{row['id']}", kind=kind, summary=summary[:200])
    return dict(row)


async def on_selfcheck(task_id: int, result: str) -> str:
    """Self-check worker finished: apply its proposals and return what to tell the owner."""
    from .awareness import parse_json
    data = parse_json(result)
    if not data:  # never claim a check happened when its result could not be read
        return "Cek diriku hari ini tidak menghasilkan temuan yang bisa kubaca, jadi tidak ada yang kuubah."
    proposals = data.get("improvements") or []
    auto = 0
    outcome = {"applied": 0, "approval": 0, "code": 0, "skipped": 0}
    for item in proposals[:15]:
        if not isinstance(item, dict):
            continue
        if item.get("kind") in ("stt_keyword", "lesson"):
            if auto >= MAX_AUTO_PER_RUN:
                outcome["skipped"] += 1
                continue
            auto += 1
        r = await apply(item, task_id)
        if "skipped" in r:
            outcome["skipped"] += 1
        elif r["status"] == "applied":
            outcome["applied"] += 1
        elif r["status"] == "awaiting_approval":
            outcome["approval"] += 1
        else:
            outcome["code"] += 1
    said = str(data.get("summary_for_owner") or "").strip() or "Aku sudah mengecek diriku dan tidak menemukan masalah yang perlu diubah."
    tail = []
    if outcome["applied"]:
        tail.append(f"{outcome['applied']} perbaikan langsung kuterapkan")
    if outcome["approval"]:
        tail.append(f"{outcome['approval']} butuh persetujuanmu")
    if outcome["code"]:
        tail.append(f"{outcome['code']} usulan perubahan program kucatat untuk developer")
    return said + (" " + ", ".join(tail) + "." if tail else "")


async def revert(improvement_id: int, actor: str) -> bool:
    done = await db.pool().execute(
        "UPDATE improvements SET status = 'reverted', reverted_at = now() WHERE id = $1 AND status IN ('applied', 'proposed', 'awaiting_approval')",
        improvement_id)
    if done.endswith("1"):
        await db.pool().execute(
            "DELETE FROM settings_kv WHERE key = (SELECT 'override:' || (payload->>'key') FROM improvements WHERE id = $1 AND kind = 'setting')",
            improvement_id)
        await audit.record(actor, "improvement.reverted", f"improvement:{improvement_id}")
        return True
    return False


async def recent(limit: int = 50) -> list[dict]:
    rows = await db.pool().fetch("SELECT * FROM improvements ORDER BY id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


async def daily_due(last_day) -> bool:
    now = datetime.now(timezone.utc).astimezone(WIB)
    return now.hour == 3 and last_day != now.date()
