"""Watchers (Blueprint v4 Fase 6, ADR-044): prices, tickets, crypto, gold. They NOTIFY — nothing else.

JARVIS never buys, books, pays, logs in or trades from a watcher: a ticket check stops before payment and says so; crypto and gold
messages are information, not investment advice (the wording is fixed here, not left to a model). Crypto is read straight from
CoinGecko's free price API (cheap, no AI); the others are looked up by a background worker (kind 'watcher') that is told it may
only read, and that answers with one machine-readable line. A message is sent when the condition BECOMES true or the price has
moved noticeably since the last message — never every check — and at most once in 6 hours per watcher.
"""

import json
import logging
import re
from datetime import UTC, datetime, timedelta

import httpx

from . import audit, db

log = logging.getLogger("jarvis-core.watchers")
KINDS = ("kripto", "emas", "harga", "tiket")
OPS = ("<=", ">=", "berubah")
MAX_ACTIVE = 10
MIN_EVERY = {"kripto": 15, "emas": 60, "harga": 120, "tiket": 120}   # minutes; web checks cost AI, so they are rarer
MIN_GAP = timedelta(hours=6)
RENEW_PCT = 2.0
COINGECKO = "https://api.coingecko.com/api/v3/simple/price"
INFO_ONLY = "Ini informasi harga saja, bukan nasihat investasi."
STOP_BEFORE_PAY = "Aku berhenti di sini: belum membeli atau memesan apa pun — kamu yang memutuskan dan membayar."
RESULT_LINE = re.compile(r"HASIL:\s*(\{.*\})\s*$", re.S | re.M)

WEB_BRIEF = ("Cek {what}: {query}. Cari harga/ketersediaan TERBARU dari sumber tepercaya dan sebut sumbernya.\n"
             "ATURAN KERAS: hanya MEMBACA. JANGAN membeli, memesan, mengisi data pembayaran, login ke akun, atau menekan tombol "
             "bayar/checkout; berhenti sebelum pembayaran. JANGAN memberi saran membeli atau menjual.\n"
             'Akhiri jawabanmu dengan SATU baris persis: HASIL: {{"value": <angka dalam rupiah, atau null bila tidak ketemu>, '
             '"note": "<sumber & keterangan singkat>"}}')


class WatchError(ValueError):
    pass


def _price(v: float) -> str:
    return "Rp " + f"{round(v):,}".replace(",", ".")


def evaluate(op: str, threshold: float, value: float, last_value: float | None, last_state: bool | None,
             last_alert_at: datetime | None, last_alert_value: float | None, now: datetime) -> tuple[bool, bool]:
    """(condition met now, send a message now). Pure; unit-tested."""
    if op == "<=":
        met = value <= threshold
    elif op == ">=":
        met = value >= threshold
    else:  # 'berubah': moved by at least `threshold` percent since the previous check
        met = last_value not in (None, 0) and abs(value - last_value) / abs(last_value) * 100 >= threshold
    if not met:
        return False, False
    if last_alert_at is not None and now - last_alert_at < MIN_GAP:
        return True, False
    newly = not last_state
    moved = last_alert_value not in (None, 0) and abs(value - last_alert_value) / abs(last_alert_value) * 100 >= RENEW_PCT
    return True, newly or moved


def message(kind: str, label: str, op: str, threshold: float, value: float, note: str = "") -> str:
    cond = {"<=": f"turun ke bawah {_price(threshold)}", ">=": f"naik ke atas {_price(threshold)}",
            "berubah": f"berubah ≥ {threshold:g}% dari pengecekan sebelumnya"}[op]
    text = f"Pantauan {label}: sekarang {_price(value)} — {cond}."
    if note:
        text += f" ({note[:140]})"
    return text + " " + (STOP_BEFORE_PAY if kind == "tiket" else INFO_ONLY if kind in ("kripto", "emas") else "Hanya pemberitahuan.")


def parse_result(text: str) -> tuple[float | None, str]:
    """The 'HASIL: {...}' line of a web check → (value, note). Pure; unit-tested."""
    m = RESULT_LINE.search(text or "")
    if not m:
        return None, "jawaban tanpa baris HASIL"
    try:
        d = json.loads(m.group(1))
        v = d.get("value")
        return (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None), str(d.get("note") or "")[:300]
    except ValueError:
        return None, "baris HASIL tidak terbaca"


async def add(kind: str, label: str, query: str, op: str, threshold: float, every_min: int | None = None) -> dict:
    if kind not in KINDS or op not in OPS:
        raise WatchError("jenis atau syarat pantauan tidak dikenal")
    label, query = label.strip()[:80], query.strip()[:200]
    if not label or not query or threshold < 0:
        raise WatchError("label, apa yang dipantau, dan ambang wajib diisi")
    if kind == "kripto" and not re.fullmatch(r"[a-z0-9-]{2,40}", query):
        raise WatchError("untuk kripto isi id CoinGecko, mis. bitcoin atau ethereum")
    if await db.pool().fetchval("SELECT count(*) FROM watchers WHERE active") >= MAX_ACTIVE:
        raise WatchError(f"maksimal {MAX_ACTIVE} pantauan aktif — hapus yang tak perlu dulu")
    every = max(int(every_min or MIN_EVERY[kind]), MIN_EVERY[kind])
    row = await db.pool().fetchrow(
        "INSERT INTO watchers (kind, label, query, op, threshold, every_min) VALUES ($1, $2, $3, $4, $5, $6) RETURNING *",
        kind, label, query, op, threshold, every)
    await audit.record("owner", "watcher.added", f"watcher:{row['id']}", kind=kind)
    return dict(row)


async def listing() -> list[dict]:
    return [dict(r) for r in await db.pool().fetch("SELECT * FROM watchers ORDER BY id")]


async def set_active(watcher_id: int, active: bool) -> bool:
    return bool(await db.pool().fetchval("UPDATE watchers SET active = $2 WHERE id = $1 RETURNING id", watcher_id, active))


async def remove(watcher_id: int) -> bool:
    return bool(await db.pool().fetchval("DELETE FROM watchers WHERE id = $1 RETURNING id", watcher_id))


def _client(timeout: float) -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10))


async def _coingecko(coin: str) -> float | None:
    try:
        async with _client(15) as c:
            r = await c.get(COINGECKO, params={"ids": coin, "vs_currencies": "idr"})
        v = r.json().get(coin, {}).get("idr") if r.status_code == 200 else None
        return float(v) if v is not None else None
    except (httpx.HTTPError, ValueError):
        return None


async def record(w: dict, value: float | None, note: str = "") -> None:
    """A check came back: update the watcher, and send ONE message if it is time."""
    from . import reports
    now = datetime.now(UTC)
    if value is None:
        await db.pool().execute("UPDATE watchers SET last_checked = now(), last_note = $2, pending_task = NULL WHERE id = $1", w["id"], note[:300])
        return
    met, send = evaluate(w["op"], float(w["threshold"]), value, None if w["last_value"] is None else float(w["last_value"]), w["last_state"],
                         w["last_alert_at"], None if w["last_alert_value"] is None else float(w["last_alert_value"]), now)
    await db.pool().execute(
        """UPDATE watchers SET last_checked = now(), last_value = $2, last_state = $3, last_note = $4, pending_task = NULL,
                  last_alert_at = CASE WHEN $5 THEN now() ELSE last_alert_at END,
                  last_alert_value = CASE WHEN $5 THEN $2 ELSE last_alert_value END WHERE id = $1""",
        w["id"], value, met, note[:300], send)
    if send:
        await reports._create(None, "watcher", message(w["kind"], w["label"], w["op"], float(w["threshold"]), value, note))
        await audit.record("jarvis-core", "watcher.alert", f"watcher:{w['id']}", value=value)


async def on_result(task_id: int, text: str) -> None:
    """The background worker's answer to a web check (workers._deliver, kind 'watcher')."""
    w = await db.pool().fetchrow("SELECT * FROM watchers WHERE pending_task = $1", task_id)
    if w:
        value, note = parse_result(text)
        await record(dict(w), value, note)


async def tick() -> None:
    """Every few minutes: run the checks that are due. Crypto is direct; the rest go to a background worker."""
    from . import ops, workers
    now = datetime.now(UTC)
    for w in await db.pool().fetch("SELECT * FROM watchers WHERE active ORDER BY id"):
        if w["pending_task"]:  # a check in flight: if it died, free the watcher for the next round
            st = await db.pool().fetchval("SELECT status FROM tasks WHERE id = $1", w["pending_task"])
            if st in (None, "failed", "cancelled", "stopped"):
                await db.pool().execute("UPDATE watchers SET pending_task = NULL, last_checked = now() WHERE id = $1", w["id"])
            continue
        if w["last_checked"] and now - w["last_checked"] < timedelta(minutes=w["every_min"]):
            continue
        if w["kind"] == "kripto":
            value = await _coingecko(w["query"])
            await record(dict(w), value, "CoinGecko" if value is not None else "CoinGecko tidak menjawab")
        elif (await ops.background_ok())[0]:
            what = {"emas": "harga emas", "harga": "harga", "tiket": "harga & ketersediaan tiket"}[w["kind"]]
            t = await workers.spawn(f"Pantau {w['label']}", WEB_BRIEF.format(what=what, query=w["query"]), "watcher", "watcher", kind="watcher")
            await db.pool().execute("UPDATE watchers SET pending_task = $2, last_checked = now() WHERE id = $1", w["id"], t["id"])
