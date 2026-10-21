"""Flow watcher ("Pengawas Alur", ADR-028): a dedicated worker that keeps checking how JARVIS handles
the owner's requests, tells the owner when something is wrong, and works on fixing it.

Each run (after a conversation pauses, at most every 20 minutes, or on demand) looks at what happened
since the previous run:
  - deterministic checks (no AI): a reply that promised work while nothing started, the same reply
    repeated, error replies, very slow replies, failed or very slow tasks, reports never heard;
  - a judge model reads the new owner ↔ main agent turns (never private ones) and flags answers that
    do not fit what the owner said or the conversation.
Issues are stored (flow_issues), the owner hears a short summary (at most every 3 hours), and one fix
task per day works on them within the self-improvement scope (perf.SCOPE): skills, settings, or a
tested, owner-approved code change. Each run is also listed as a task (kind 'flowcheck').
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

from . import db, llm, reports

log = logging.getLogger("jarvis-core.auditor")

SLOW_REPLY_MS = 45_000
# A promise of FUTURE work ("aku cek dulu", "akan kucari") — not a finished direct action ("Oke, kuputar X")
# and not a failure ("belum bisa kuputar").
_FUTURE = re.compile(r"\b(akan|mau|segera|nanti)\s+(ku|aku |saya )?(cek|cari|carikan|putar|putarkan|tampilkan|siapkan|"
                     r"buatkan|kerjakan|urus|periksa|kabari)|\b(cek|cari|carikan|periksa)\s+dulu\b", re.IGNORECASE)
_FAILED = re.compile(r"\b(maaf|belum bisa|tidak bisa|gagal)\b", re.IGNORECASE)
_ACK = re.compile(r"^(oke|ok|okay|sip|siap|makasih|terima ?kasih|thanks|ya|iya|baik|mantap|good)\b.{0,25}$", re.IGNORECASE)
SLOW_TASK_S = 15 * 60
_state = {"last_run": None}

JUDGE = """Kamu PENGAWAS ALUR JARVIS. Untuk setiap giliran, nilai apakah jawaban JARVIS (agen utama, bicara lewat \
suara) SESUAI dengan ucapan pemilik dan konteks obrolannya. Masalah yang dicari: tidak nyambung / menjawab hal lain, \
salah paham maksud, mengulang jawaban sebelumnya, berjanji mengerjakan tanpa kejelasan, mengarang fakta, menyangkal \
kemampuan, terlalu panjang untuk suara. Abaikan perbedaan gaya kecil. Balas HANYA JSON array: \
[{"i": <nomor giliran>, "ok": true|false, "masalah": "<singkat, jika ok=false>"}]"""

FIX_TASK = """[pengawas alur] Aku (Pengawas Alur JARVIS) menemukan masalah dalam cara JARVIS melayani pemilik:

{issues}

{scope}

Pakai skill jarvis-flow-audit. Untuk tiap pola masalah: cari akar penyebabnya di alur (prompt agen utama di
core/app/assistant.py, aksi langsung di core/app/router.py, pekerja cepat core/app/quick.py, delegasi di
core/app/workers.py, skill Hermes), lalu perbaiki dengan cara paling ringan — skill/setelan, atau perubahan kode
lewat propose_code_change dengan tes yang mereproduksi masalahnya. Bila penyebabnya bukan kode (mis. model
lokal terlalu kecil, saldo habis), katakan terus terang dan sarankan langkah pemilik.
Akhiri dengan ringkasan lisan 2–3 kalimat: masalahnya, penyebabnya, apa yang diperbaiki/diusulkan."""

KIND_TEXT = {"off_context": "jawaban tidak sesuai konteks", "promise_unkept": "janji mengerjakan tapi tidak ada tugas",
             "repeated": "jawaban berulang", "error_reply": "jawaban error", "slow_reply": "jawaban sangat lambat",
             "task_failed": "tugas gagal", "task_slow": "tugas sangat lama", "report_unheard": "laporan tidak terdengar",
             "other": "lainnya"}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def turn_checks(turns: list[dict], spawned_at: list[tuple[str, datetime]]) -> list[dict]:
    """Deterministic issues in a list of messages (oldest first). Pure, unit-tested.
    turns: {"id","session_id","role","content","route","created_at","trace"}; spawned_at: (session, time)
    of every owner task created."""
    issues, last_user, previous, prev_said = [], {}, {}, {}
    for m in turns:
        sid = m["session_id"]
        if m["role"] == "user":
            if sid in last_user:
                prev_said[sid] = _norm(last_user[sid]["content"])
            last_user[sid] = m
            continue
        if m["route"] not in ("assistant", "error"):
            continue
        said = last_user.get(sid, {}).get("content", "")
        base = {"session_id": sid, "message_id": m["id"], "owner_said": said[:500], "jarvis_said": m["content"][:500]}
        if m["route"] == "error":
            issues.append({**base, "kind": "error_reply", "severity": "high", "detail": m["content"][:300]})
            continue
        trace = m.get("trace") or {}
        if isinstance(trace, dict) and (trace.get("total_ms") or 0) > SLOW_REPLY_MS:
            issues.append({**base, "kind": "slow_reply", "severity": "low",
                           "detail": f"{trace['total_ms'] // 1000} detik sampai menjawab ({(trace.get('route') or {}).get('model', '-')})"})
        direct = (trace.get("route") or {}).get("model") == "aksi-langsung" if isinstance(trace, dict) else False
        if (_FUTURE.search(m["content"]) and not _FAILED.search(m["content"]) and not direct
                and said and not _ACK.match(said.strip())):
            t0 = last_user.get(sid, m)["created_at"] - timedelta(seconds=5)
            t1 = m["created_at"] + timedelta(seconds=30)
            if not any(s == sid and t0 <= at <= t1 for s, at in spawned_at):
                issues.append({**base, "kind": "promise_unkept", "severity": "high",
                               "detail": "JARVIS bilang akan mengerjakan, tapi tidak ada tugas yang dimulai"})
        key = _norm(m["content"])[:200]
        recent = previous.setdefault(sid, [])
        same_ask = _norm(said) == prev_said.get(sid)  # the owner asked the same thing again: same answer is fine
        if key and key in recent[-3:] and not same_ask and _norm(said) not in ("", "ulangi", "apa", "hah"):
            issues.append({**base, "kind": "repeated", "severity": "medium",
                           "detail": "jawaban sama persis dengan jawaban sebelumnya untuk ucapan yang berbeda"})
        recent.append(key)
    return issues


def parse_verdicts(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else []
    except ValueError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("ok") is False and isinstance(d.get("i"), int)]


async def _judge(turns: list[dict]) -> list[dict]:
    """Ask the judge model about the newest non-private owner ↔ main agent turns."""
    pairs, history, last_user = [], {}, {}
    for m in turns:
        sid = m["session_id"]
        if m["route"] == "private":
            continue
        if m["role"] == "user":
            last_user[sid] = m
        elif m["route"] == "assistant" and sid in last_user:
            ctx = " / ".join(history.get(sid, [])[-4:])
            pairs.append((last_user[sid], m, ctx))
        history.setdefault(sid, []).append(f"{'Pemilik' if m['role'] == 'user' else 'JARVIS'}: {m['content'][:160]}")
    pairs = pairs[-8:]
    if not pairs:
        return []
    listing = "\n\n".join(f"#{i + 1}\nKONTEKS SEBELUMNYA: {ctx or '-'}\nPEMILIK: {u['content'][:300]}\nJARVIS: {a['content'][:400]}"
                          for i, (u, a, ctx) in enumerate(pairs))
    try:
        raw = await llm.complete([{"role": "system", "content": JUDGE}, {"role": "user", "content": listing}],
                                 category="analisis", caller="flowwatch", max_tokens=500, temperature=0.1)
    except llm.LLMError as e:
        log.info("flow judge unavailable: %s", e)
        return []
    out = []
    for v in parse_verdicts(raw):
        if 1 <= v["i"] <= len(pairs):
            u, a, _ = pairs[v["i"] - 1]
            out.append({"kind": "off_context", "severity": "medium", "session_id": a["session_id"], "message_id": a["id"],
                        "owner_said": u["content"][:500], "jarvis_said": a["content"][:500],
                        "detail": str(v.get("masalah") or "tidak sesuai konteks")[:300]})
    return out


async def _since() -> datetime:
    last = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'flowwatch:since'")
    if isinstance(last, str):
        return datetime.fromisoformat(last)
    return datetime.now(timezone.utc) - timedelta(hours=24)


async def due(now: datetime | None = None) -> bool:
    """New owner turns since the last run, the conversation paused ≥ 2 min, last run ≥ 20 min ago."""
    now = now or datetime.now(timezone.utc)
    if _state["last_run"] and now - _state["last_run"] < timedelta(minutes=20):
        return False
    last_owner = await db.pool().fetchval("SELECT max(created_at) FROM messages WHERE role = 'user'")
    return bool(last_owner and last_owner > await _since() and now - last_owner > timedelta(minutes=2))


async def run(actor: str = "jarvis-core") -> dict:
    """One pass of the flow watcher. Returns {"task_id", "new": [...], "fix_task_id"}."""
    q = db.pool()
    now = datetime.now(timezone.utc)
    _state["last_run"] = now
    since = await _since()
    task_id = await q.fetchval(
        """INSERT INTO tasks (session_id, title, instruction, kind, category, status, started_at)
           VALUES ('flowwatch', 'Pengawas alur: periksa obrolan & alur', 'cek otomatis', 'flowcheck', 'latar-belakang',
                   'running', now()) RETURNING id""")
    turns = [dict(r) for r in await q.fetch(
        """SELECT id, session_id, role, content, route, created_at, trace FROM messages
           WHERE created_at > $1::timestamptz - interval '10 minutes' AND route NOT IN ('report', 'silent', 'core')
           ORDER BY id""", since)]
    spawned = [(r["session_id"], r["created_at"]) for r in await q.fetch(
        "SELECT session_id, created_at FROM tasks WHERE kind = 'owner' AND created_at > $1::timestamptz - interval '15 minutes'", since)]
    new_turns = [t for t in turns if t["created_at"] > since]
    found = [i for i in turn_checks(turns, spawned) if any(t["id"] == i["message_id"] for t in new_turns)]
    found += await _judge(turns) if new_turns else []
    found = [i for i in found if any(t["id"] == i["message_id"] for t in new_turns)]
    for t in await q.fetch(
            """SELECT id, title, status, error, extract(epoch FROM finished_at - started_at)::int AS s FROM tasks
               WHERE kind = 'owner' AND finished_at > $1""", since):
        if t["status"] == "failed":
            found.append({"kind": "task_failed", "severity": "high", "task_id": t["id"],
                          "detail": f"{t['title']}: {(t['error'] or '')[:200]}"})
        elif (t["s"] or 0) > SLOW_TASK_S:
            found.append({"kind": "task_slow", "severity": "medium", "task_id": t["id"],
                          "detail": f"{t['title']}: {t['s'] // 60} menit"})
    for r in await q.fetch("SELECT id, task_id, text FROM reports WHERE status = 'unheard' AND created_at > $1", since):
        found.append({"kind": "report_unheard", "severity": "low", "task_id": r["task_id"], "detail": r["text"][:200]})

    new = []
    for i in found:
        row = await q.fetchrow(
            """INSERT INTO flow_issues (kind, severity, session_id, message_id, task_id, owner_said, jarvis_said, detail)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING RETURNING id, kind, severity, detail, owner_said""",
            i["kind"], i["severity"], i.get("session_id"), i.get("message_id"), i.get("task_id"),
            i.get("owner_said"), i.get("jarvis_said"), i.get("detail", ""))
        if row:
            new.append(dict(row))
    await q.execute(
        """INSERT INTO settings_kv (key, value) VALUES ('flowwatch:since', $1)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", now.isoformat())
    if await q.fetchval("SELECT status FROM tasks WHERE id = $1", task_id) != "running":
        return {"task_id": task_id, "new": new, "fix_task_id": None}  # the owner cancelled this run: no fix, no report
    serious = [i for i in new if i["severity"] in ("medium", "high")]
    fix = await _start_fix() if serious else None
    summary = (f"{len(new)} masalah baru ({len(serious)} perlu diperbaiki) dari {len(new_turns)} pesan."
               if new else f"Tidak ada masalah dari {len(new_turns)} pesan.")
    await q.execute("UPDATE tasks SET status = 'completed', result = $2, finished_at = now() WHERE id = $1 AND status = 'running'",
                    task_id, summary)
    if serious:
        await _tell_owner(serious, fix)
    return {"task_id": task_id, "new": new, "fix_task_id": fix["id"] if fix else None}


async def _start_fix() -> dict | None:
    """One fix task a day for everything still open."""
    from . import perf, workers
    q = db.pool()
    signature = "flow:" + datetime.now(timezone.utc).date().isoformat()
    if await q.fetchval("SELECT 1 FROM repair_attempts WHERE signature = $1", signature):
        return None
    open_ = await q.fetch(
        """SELECT id, kind, detail, owner_said, jarvis_said FROM flow_issues
           WHERE status = 'open' AND severity IN ('medium', 'high') ORDER BY id DESC LIMIT 15""")
    if not open_:
        return None
    listing = "\n".join(
        f"- #{r['id']} {KIND_TEXT.get(r['kind'], r['kind'])}: {r['detail']}"
        + (f"\n  pemilik: \"{(r['owner_said'] or '')[:160]}\" → JARVIS: \"{(r['jarvis_said'] or '')[:160]}\"" if r["owner_said"] else "")
        for r in open_)
    t = await workers.spawn("Pengawas alur: perbaiki masalah obrolan", FIX_TASK.format(issues=listing, scope=perf.SCOPE),
                            "selfimprove", "jarvis-core", kind="selfimprove", category="coding")
    await q.execute("UPDATE flow_issues SET status = 'fixing', fix_task_id = $2 WHERE id = ANY($1::bigint[])",
                    [r["id"] for r in open_], t["id"])
    await q.execute("INSERT INTO repair_attempts (signature, task_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    signature, t["id"])
    return t


async def _tell_owner(serious: list[dict], fix: dict | None) -> None:
    """At most every 3 hours — remembered in the database, so a restart does not reset it."""
    now = datetime.now(timezone.utc)
    q = db.pool()
    told = await q.fetchval("SELECT value FROM settings_kv WHERE key = 'flowwatch:told'")
    if isinstance(told, str) and now - datetime.fromisoformat(told) < timedelta(hours=3):
        return
    await q.execute("""INSERT INTO settings_kv (key, value) VALUES ('flowwatch:told', $1)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", now.isoformat())
    kinds = sorted({KIND_TEXT.get(i["kind"], i["kind"]) for i in serious})
    order = ["off_context", "promise_unkept", "repeated", "task_failed", "error_reply"]  # most telling example first
    example = min(serious, key=lambda i: (not i.get("owner_said"), order.index(i["kind"]) if i["kind"] in order else 9))
    text = (f"Pengawas alur menemukan {len(serious)} masalah dalam caraku melayanimu: {', '.join(kinds)}. "
            + (f"Contohnya saat kamu bilang \"{example['owner_said'][:80]}\": {example['detail'][:120]}. " if example.get("owner_said")
               else f"Contohnya: {example['detail'][:140]}. ")
            + ("Aku sedang mencari penyebabnya dan memperbaikinya." if fix else "Perbaikannya sudah berjalan hari ini."))
    await reports._create(None, "system", text)


async def on_fix_done(task_id: int) -> None:
    await db.pool().execute("UPDATE flow_issues SET status = 'fixed' WHERE fix_task_id = $1 AND status = 'fixing'", task_id)


async def list_(limit: int = 50) -> list[dict]:
    rows = await db.pool().fetch("SELECT * FROM flow_issues ORDER BY id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


async def set_status(issue_id: int, status: str) -> bool:
    if status not in ("open", "ignored", "fixed"):
        raise ValueError("status: open | ignored | fixed")
    r = await db.pool().execute("UPDATE flow_issues SET status = $2 WHERE id = $1", issue_id, status)
    return r.endswith("1")
