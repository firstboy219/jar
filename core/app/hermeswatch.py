"""Pengawas Hermes (owner 2026-10-31: "kecuali Hermesnya sedang anomali seperti asal jawab atau memberikan data palsu dll, jika kejadiannya
seperti itu skip flow ke Hermesnya, jadi harus ada entity yg tugasnya mengawasi hermes").

Whatever Hermes plans for JARVIS' workers is checked here before it is used, by rules — never by asking another model:
  * it answered THIS request: the one-time token given in the question comes back, the number of workers is right
  * nothing invented: only workers that exist, each exactly once, none that must run left out
  * its claims match the facts it was given: a source it skips "because it is failing" really failed or came back empty lately
  * numbers within bounds (how many at once), and afterwards: its queue did not make the work clearly slower
An answer that breaks a rule is not used (the built-in order is), and the anomaly is recorded; two in a row and Hermes is passed over for
an hour. Every check is kept (the last 20) so the owner sees what the watchdog saw."""

import json
import re
import time

from . import db

KEY = "hermes:watch"
BYPASS_AFTER = 2           # anomalies in a row …
BYPASS_S = 3600            # … pass Hermes over for this long
KEEP = 20


async def state() -> dict:
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", KEY)
    return {"bad_streak": 0, "bypass_until": 0, "bypass_why": "", "checks": [], **(v or {})}


async def _save(st: dict) -> None:
    await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", KEY, st)


async def bypassed() -> str:
    """Why Hermes is being passed over right now, or '' when it is trusted."""
    st = await state()
    return st["bypass_why"] if st["bypass_until"] > time.time() else ""


async def record(kind: str, problems: list[str], note: str = "") -> dict:
    """One check's outcome. Problems = an anomaly; none = Hermes did its job."""
    st = await state()
    st["checks"] = ([{"at": time.time(), "kind": kind, "ok": not problems, "problems": problems[:5], "note": note[:200]}] + st["checks"])[:KEEP]
    if problems:
        st["bad_streak"] += 1
        if st["bad_streak"] >= BYPASS_AFTER:
            st.update(bypass_until=time.time() + BYPASS_S, bypass_why=f"{st['bad_streak']} anomali berturut-turut: {problems[0]}")
    else:
        st.update(bad_streak=0, bypass_until=0, bypass_why="")
    await _save(st)
    return st


def first_json(text: str):
    """The first JSON object in Hermes' answer (it may wrap it in words or a code fence), or None. Pure."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def check_queue(text: str, token: str, workers: list[str], required: set[str], troubled: set[str], max_at_once: int = 8) -> tuple[dict | None, list[str]]:
    """A queue plan from Hermes → (the plan, []) when every rule holds, else (None, the problems). Pure.
    troubled: the workers whose recent record shows failures or empty results — the only ones it may skip."""
    v = first_json(text)
    if v is None:
        return None, ["jawaban bukan JSON (asal jawab)"]
    problems = []
    if str(v.get("token", "")) != token:
        problems.append("token jebakan tidak dikembalikan — jawaban bukan untuk permintaan ini")
    try:
        if int(v.get("jumlah")) != len(workers):
            problems.append(f"jumlah worker salah ({v.get('jumlah')} ≠ {len(workers)})")
    except (TypeError, ValueError):
        problems.append("jumlah worker tidak ada")
    order = [str(x) for x in (v.get("urutan") or []) if isinstance(x, str)]
    skips = [x for x in (v.get("lewati") or []) if isinstance(x, dict)]
    skipped = [str(x.get("worker", "")) for x in skips]
    named = order + skipped
    if fake := sorted({n for n in named if n not in workers}):
        problems.append(f"nama worker tidak dikenal: {', '.join(fake)}")
    if dup := sorted({n for n in named if named.count(n) > 1}):
        problems.append(f"worker disebut dua kali: {', '.join(dup)}")
    if missing := [w for w in workers if w not in named]:
        problems.append(f"worker hilang dari rencana: {', '.join(missing)}")
    if must := sorted(set(skipped) & required):
        problems.append(f"worker wajib dilewati: {', '.join(must)}")
    for x in skips:
        w = str(x.get("worker", ""))
        if w in workers and w not in required and w not in troubled:
            problems.append(f"klaim tidak sesuai data: {w} dilewati padahal catatannya baik")
        if not str(x.get("alasan", "")).strip():
            problems.append(f"{w} dilewati tanpa alasan")
    if len(skipped) > 3:
        problems.append("terlalu banyak sumber dilewati")
    try:
        at_once = int(v.get("maks_bersamaan"))
        if not 2 <= at_once <= max_at_once:
            problems.append(f"maks_bersamaan di luar batas ({at_once})")
    except (TypeError, ValueError):
        at_once = 0
        problems.append("maks_bersamaan tidak ada")
    if problems:
        return None, problems
    return {"urutan": order, "lewati": [{"worker": str(x["worker"]), "alasan": str(x.get("alasan", ""))[:160]} for x in skips],
            "maks": at_once, "catatan": str(v.get("catatan") or "")[:300]}, []


def too_slow(secs: float, usual: float | None) -> str:
    """After the run: did Hermes' queue clearly slow the collecting down? '' when not. Pure."""
    limit = max(30.0, 2.5 * usual) if usual else 45.0
    return f"antrean Hermes memperlambat pengumpulan ({secs:.0f} d, biasanya ±{usual or 0:.0f} d)" if secs > limit else ""
