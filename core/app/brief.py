"""Cek berita (ADR-087; was "Brief pagi" — owner 2026-10-31: "bukan lg listing berita tp smartnews bisa menyimpulkan situasi saat ini dan
mengumpulkan indikator reasonnya, dan peluang apa yg bisa diambil dari situasi tersebut yg menguntungkan bagi ekonomi saya").

Every morning (05.45 by default, or when he asks) the news of the last day from several newsrooms and the market indicators are gathered (a
fixed procedure, no AI), then the heavy brain (master flow; personal context, so never a free endpoint) reads them together with what JARVIS
knows of his money — salary pots, his investments' mix, his businesses, his job search — and writes an ANALYSIS, not a list: what the
situation is, the themes behind it each with its indicators (numbers from the market data or the news only) and the reasons (each linked to
its news), what it means for him, and the opportunities he could take (with the risk and how sure it is) — never an order to buy or sell.
Kept per day; the phone gets a notice that opens it.

Sharper (owner 2026-10-31: "lebih dipertajam … tp tetap mudah dibaca dan AI memposisikan diri menjadi diri saya dan membuatkan plan … 1-3
bulan kedepan yg bisa saya pilih, plan yg saya pilih akan masuk ke list task di menu catatan"): three points first, each theme as a chain
of cause and effect, 2–3 scenarios for the coming months with the sign of each, and three plans written as if the brain were him (safe,
balanced, bold; 1–3 months; weekly steps). The plan he picks becomes tasks in Catatan, due week by week; the next analyses see how far it
is and say whether to carry on or adjust.

Worked by several workers (owner 2026-10-31: "membagi jadi beberapa worker … pengumpulan dibagi jadi multi worker, lalu … 1 worker untuk
menganalisa, lalu … 1 worker bertindak menjadi saya mengumpulkan data tentang saya lalu dicompare"), each its own run in the master flow:
  1. collectors, in parallel, one per source (news, markets & technicals, Google News, Reddit, Google Trends, Fear & Greed, the agenda,
     the weather) — skills, no AI; one that fails is left out
  2. the analyst (heavy brain): public data only → situation, themes with their chains, indicators and reasons, sentiment, scenarios
  3. the worker that is him: gathers what JARVIS knows of him (memory, money, holdings with their technicals, businesses, job search, the
     plan he follows; a skill), then (heavy brain, as "aku") compares it with the analysis → his position (strong / vulnerable), what each
     theme means for him, three plans, quick opportunities, how his running plan stands
The page follows the steps live and keeps them with the brief."""

import asyncio
import html as htmlmod
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, appsettings, audit, db, home, hub, master, setup_status
from .appauth import actor, owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/brief"

FEEDS = {
    "indonesia": [("Antara", "https://www.antaranews.com/rss/terkini.xml"), ("CNN Indonesia", "https://www.cnnindonesia.com/nasional/rss"),
                  ("Tempo", "https://rss.tempo.co/nasional")],
    "ekonomi": [("CNBC Indonesia", "https://www.cnbcindonesia.com/news/rss"), ("Antara Ekonomi", "https://www.antaranews.com/rss/ekonomi.xml"),
                ("Katadata", "https://katadata.co.id/rss"), ("Detik Finance", "https://finance.detik.com/rss")],
    "pasar": [("CNBC Indonesia Market", "https://www.cnbcindonesia.com/market/rss"), ("Kontan Investasi", "https://investasi.kontan.co.id/rss"),
              ("Kontan Keuangan", "https://keuangan.kontan.co.id/rss"), ("IDX Channel", "https://www.idxchannel.com/rss")],
    "dunia": [("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"), ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
              ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"), ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories")],
}
MARKETS = [("IHSG", "^JKSE"), ("Rupiah/USD", "IDR=X"), ("Emas", "GC=F"), ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Bitcoin", "BTC-USD"),
           ("Ethereum", "ETH-USD"), ("Minyak Brent", "BZ=F"), ("Imbal hasil obligasi AS 10th", "^TNX"), ("Indeks dolar (DXY)", "DX-Y.NYB"),
           ("VIX (indeks ketakutan)", "^VIX")]
DEFAULT_TOPICS = ("harga emas", "IHSG", "suku bunga Bank Indonesia")   # Google News when he follows / holds little
PER_FEED = 12
MAX_AGE_H = 30

# what other features add about the owner (his business numbers, his holdings, his calendar …): name → async () -> str
CONTEXT: dict[str, Callable[[], Awaitable[str]]] = {}


def context(name: str):
    def wrap(fn):
        CONTEXT[name] = fn
        return fn
    return wrap


def _text(s: str | None) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_feed(xml: str, source: str, now: datetime, limit: int = PER_FEED) -> list[dict]:
    """RSS items as {title, summary, link, source, at}, newest first, none older than MAX_AGE_H. Pure."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = _text(it.findtext("title"))
        if not title:
            continue
        at = None
        raw = it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")
        if raw:
            try:
                at = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                try:
                    at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    at = None
        if at and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at and now - at > timedelta(hours=MAX_AGE_H):
            continue
        out.append({"title": title[:200], "summary": _text(it.findtext("description"))[:300], "link": (it.findtext("link") or "").strip()[:400],
                    "source": source, "at": at.isoformat() if at else None})
    out.sort(key=lambda x: x["at"] or "", reverse=True)
    return out[:limit]


def change_pct(closes: list) -> float | None:
    """The last day's change in % from a list of daily closes. Pure."""
    vals = [c for c in closes if isinstance(c, (int, float))]
    if len(vals) < 2 or not vals[-2]:
        return None
    return round(100 * (vals[-1] - vals[-2]) / vals[-2], 2)


def _client() -> httpx.AsyncClient:  # seam for tests
    return httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0 (JARVIS brief)"}, follow_redirects=True)


async def _feed(c: httpx.AsyncClient, source: str, url: str, now: datetime) -> list[dict]:
    try:
        r = await c.get(url)
        return parse_feed(r.text, source, now) if r.status_code == 200 else []
    except httpx.HTTPError:
        return []


async def _quote(c: httpx.AsyncClient, label: str, sym: str) -> dict | None:
    """The last price, its change over 5 trading days (1 day when that is all there is) and the technical rating from a year of closes."""
    from . import signals
    closes = await signals.history(c, sym)
    last = next((v for v in reversed(closes) if isinstance(v, (int, float))), None)
    if last is None:
        return None
    vals = [v for v in closes if isinstance(v, (int, float))]
    five = round(100 * (vals[-1] - vals[-6]) / vals[-6], 2) if len(vals) > 5 and vals[-6] else None
    return {"label": label, "symbol": sym, "last": round(last, 2), "change": five if five is not None else change_pct(closes),
            "change_1d": change_pct(closes), "tech": signals.technicals(closes)}


def mix(lists: list[list[dict]]) -> list[dict]:
    """Several sources' items taken in turn (each source shows up, not just the busiest), the same headline once. Pure."""
    out, seen = [], set()
    for row in zip(*[lst + [None] * (max(map(len, lists), default=0) - len(lst)) for lst in lists]):
        for x in row:
            key = re.sub(r"\W+", "", (x or {}).get("title", "").lower())[:60]
            if x and key not in seen:
                seen.add(key)
                out.append(x)
    return out


# ---------- stage 1: the collectors — one worker per source, all at once (owner 2026-10-31: "pengumpulan dibagi jadi multi worker") ----------

async def _topic_queries() -> list[str]:
    from . import signals
    s = await appsettings.get("brief")
    try:
        held = await signals.holdings()
    except Exception:
        held = []
    return list(dict.fromkeys([*(s.get("topics") or [])[:3], *(n.split(" (")[0] for n, _ in held[:3]), *DEFAULT_TOPICS]))[:6]


async def _c_news(now: datetime) -> dict:
    async with _client() as c:
        feeds = {k: await asyncio.gather(*(_feed(c, src, u, now) for src, u in v)) for k, v in FEEDS.items()}
    return {k: mix(v) for k, v in feeds.items()}


async def _c_markets(now: datetime) -> list:
    async with _client() as c:
        return [q for q in await asyncio.gather(*(_quote(c, l, sym) for l, sym in MARKETS)) if q]


async def _c_topics(now: datetime) -> list:
    from . import signals
    async with _client() as c:
        return await signals.topics(c, await _topic_queries(), now)


async def _c_social(now: datetime) -> list:
    from . import signals
    async with _client() as c:
        return await signals.social(c, now)


async def _c_trends(now: datetime) -> list:
    from . import signals
    async with _client() as c:
        return await signals.trends(c)


async def _c_mood(now: datetime) -> dict:
    from . import signals
    async with _client() as c:
        return await signals.mood(c)


async def _c_agenda(now: datetime) -> list:
    from . import signals
    async with _client() as c:
        return await signals.agenda(c, now)


async def _c_weather(now: datetime) -> str:
    from . import weather
    return await weather.today_text() or ""


COLLECTORS = [("berita", "Berita dari media", _c_news), ("pasar", "Harga & teknikal pasar", _c_markets), ("topik", "Google News topikmu", _c_topics),
              ("sosial", "Obrolan Reddit", _c_social), ("tren", "Google Trends", _c_trends), ("sentimen", "Fear & Greed & CoinGecko", _c_mood),
              ("agenda", "Kalender ekonomi", _c_agenda), ("cuaca", "Cuaca", _c_weather)]
_state: dict = {"running": False, "steps": [], "started": None, "error": None, "log": []}
REQUIRED = {"berita", "pasar"}   # the analysis stands on these: Hermes may never skip them
PLAN_KEY_Q = "brief:antrean"
PLAN_FRESH_S = 24 * 3600
HERMES_SESSION = "jarvis-cekberita-antrean"
_planning: dict = {"task": None}


def _size(v) -> int:
    return sum(len(x) for x in v.values()) if isinstance(v, dict) and all(isinstance(x, list) for x in v.values()) else len(v) if isinstance(v, (list, dict)) else int(bool(v))


async def _step(stage: str, key: str, label: str, r: dict | None, t0: float, n: int = 0) -> dict:
    """One worker's line in the pipeline: shown live while it runs and kept with the brief."""
    st = {"stage": stage, "key": key, "label": label, "status": "jalan" if r is None else ("selesai" if r["status"] == "done" else "gagal"),
          "run_id": (r or {}).get("run_id"), "lane": (r or {}).get("lane"), "secs": round(time.monotonic() - t0, 1), "n": n,
          "error": str((r or {}).get("error") or "")[:160]}
    _state["steps"] = [x for x in _state["steps"] if x["key"] != key] + [st]
    if r is None:
        await log_line(f"▶ {label} mulai")
    elif st["status"] == "selesai":
        await log_line(f"✓ {label} selesai{f' · {n} data' if n else ''} ({st['secs']} d, {LANE_NAMES.get(st['lane'], st['lane'] or '')})", "ok")
    else:
        await log_line(f"✗ {label} gagal: {st['error'] or 'tanpa keterangan'}", "bad")
    return st


LANE_NAMES = {"skill": "tanpa AI", "ringan": "otak ringan", "berat": "otak berat", "hermes": "Hermes"}


async def log_line(text: str, kind: str = "info") -> None:
    """One line of the workers' activity log the page shows under the loader (kept with the brief)."""
    _state["log"] = (_state["log"] + [{"at": datetime.now(timezone.utc).isoformat(), "text": text[:240], "kind": kind}])[-80:]
    await hub.broadcast({"type": "brief", "running": _state["running"], "steps": _state["steps"], "log": _state["log"][-40:]})


async def gather(trigger: str = "schedule") -> dict:
    """Every source by its own worker through the master flow (a skill: no AI), in the order and at the pace Hermes planned (a queue: a
    worker starts when a place frees up); one that fails is left out. Without a trusted plan: all at once, as before."""
    now = datetime.now(timezone.utc)
    plan = await queue_plan()
    by_key = {k: (k, label, fn) for k, label, fn in COLLECTORS}
    slots = asyncio.Semaphore(plan["maks"])
    t_all = time.monotonic()

    async def one(key: str, label: str, fn, pos: int) -> tuple[str, object]:
        note = (f"antrean Hermes: ke-{pos} dari {len(plan['urutan'])}, maks {plan['maks']} bersamaan" if plan["source"] == "hermes"
                else "urutan bawaan (tanpa rencana Hermes)")
        async with slots:
            t0 = time.monotonic()
            await _step("kumpul", key, label, None, t0)
            r = await master.run(master.Job("brief", f"kumpul-{key}", f"cek berita: kumpulkan {label.lower()}", trigger=trigger,
                                            skill=lambda: fn(now), data={"antrean": note}))
        val = r.get("result") if r["status"] == "done" else None
        await _step("kumpul", key, label, r, t0, _size(val))
        return key, val
    for k in plan["urutan"]:   # the queue, visible from the start
        _state["steps"].append({"stage": "kumpul", "key": k, "label": by_key[k][1], "status": "antre", "run_id": None, "lane": None, "secs": 0, "n": 0, "error": ""})
    for sk in plan["lewati"]:
        _state["steps"].append({"stage": "kumpul", "key": sk["worker"], "label": by_key[sk["worker"]][1], "status": "dilewati", "run_id": None,
                                "lane": None, "secs": 0, "n": 0, "error": sk["alasan"]})
        await log_line(f"⤼ {by_key[sk['worker']][1]} dilewati Hermes: {sk['alasan']}", "warn")
    got = dict(await asyncio.gather(*(one(*by_key[k], i) for i, k in enumerate(plan["urutan"], 1))))
    secs = round(time.monotonic() - t_all, 1)
    if plan["source"] == "hermes":   # the watchdog looks at the result too: a queue that clearly slowed the work down is an anomaly
        from . import hermeswatch
        slow = hermeswatch.too_slow(secs, await _usual_collect())
        await hermeswatch.record("antrean-hasil", [slow] if slow else [], f"pengumpulan {secs} d")
        if slow:
            await log_line(f"⚠ Pengawas Hermes: {slow}", "warn")
    news = dict(got.get("berita") or {})
    if got.get("topik"):
        news["topik"] = got["topik"]
    if got.get("sosial"):
        news["sosial"] = got["sosial"]
    return {"news": news, "markets": got.get("pasar") or [], "trends": got.get("tren") or [], "mood": got.get("sentimen") or {},
            "agenda": got.get("agenda") or [], "weather": got.get("cuaca") or "", "collect_secs": secs, "queue": plan}


# ---------- Hermes plans the queue ahead; the watchdog checks it (owner 2026-10-31: "setiap worker melewati Hermes dulu … Hermes tau
# context dan bisa bikin alur antrian … kecuali Hermesnya sedang anomali … skip flow ke Hermesnya") ----------

def default_plan(why: str = "") -> dict:
    return {"urutan": [k for k, _, _ in COLLECTORS], "lewati": [], "maks": len(COLLECTORS), "source": "bawaan", "why": why, "made_at": None}


async def queue_plan() -> dict:
    """The queue for this run: Hermes' latest plan when the watchdog trusts it and it is fresh (asked ahead of time, so no waiting now)."""
    from . import hermeswatch
    if why := await hermeswatch.bypassed():
        await log_line(f"⚠ Pengawas Hermes: Hermes dilewati — {why}; memakai urutan bawaan", "warn")
        return default_plan(f"Hermes dilewati: {why}")
    rec = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", PLAN_KEY_Q)
    keys = [k for k, _, _ in COLLECTORS]
    if not rec or time.time() - rec.get("made_at", 0) > PLAN_FRESH_S or sorted(rec["plan"]["urutan"] + [x["worker"] for x in rec["plan"]["lewati"]]) != sorted(keys):
        refresh_soon()
        await log_line("Hermes belum punya rencana antrean yang segar — memakai urutan bawaan; Hermes menyusunnya untuk berikutnya")
        return default_plan("belum ada rencana Hermes yang segar")
    plan = {**rec["plan"], "source": "hermes", "made_at": rec["made_at"],
            "why": rec["plan"].get("catatan") or f"{len(rec['plan']['urutan'])} worker, maks {rec['plan']['maks']} bersamaan"}
    made = datetime.fromtimestamp(rec["made_at"], WIB).strftime("%H.%M")
    await log_line(f"Hermes: antrean {' → '.join(plan['urutan'])} · maks {plan['maks']} bersamaan (disusun {made}, lolos pengawas)"
                   + (f" · {plan['catatan']}" if plan.get("catatan") else ""))
    return plan


async def _usual_collect() -> float | None:
    rows = await db.pool().fetch("SELECT (data->>'collect_secs')::float AS s FROM briefs WHERE data ? 'collect_secs' ORDER BY day DESC LIMIT 5")
    vals = sorted(r["s"] for r in rows if r["s"])
    return vals[len(vals) // 2] if vals else None


async def queue_facts() -> dict:
    """What Hermes is told to plan with: each worker's record (14 days of runs, the last brief), the server's load now."""
    from . import hostinfo, workers
    rows = await db.pool().fetch("""SELECT action, count(*) AS n, count(*) FILTER (WHERE status = 'failed') AS bad,
                                           avg(EXTRACT(EPOCH FROM (finished_at - started_at)))::float AS secs
                                    FROM flow_runs WHERE feature = 'brief' AND action LIKE 'kumpul-%' AND started_at > now() - interval '14 days'
                                    GROUP BY action""")
    stats = {r["action"].removeprefix("kumpul-"): dict(r) for r in rows}
    last = await db.pool().fetchval("SELECT data->'pipeline' FROM briefs ORDER BY day DESC LIMIT 1") or []
    last_by = {x.get("key"): x for x in (last if isinstance(last, list) else [])}
    out, troubled = [], set()
    for k, label, _ in COLLECTORS:
        st, lb = stats.get(k) or {}, last_by.get(k) or {}
        empty = lb.get("status") == "gagal" or (lb.get("status") == "selesai" and not lb.get("n"))
        bad_rate = (st.get("bad") or 0) / st["n"] if st.get("n") else 0
        if k not in REQUIRED and (empty or (st.get("n", 0) >= 2 and bad_rate >= 0.5)):
            troubled.add(k)
        got = f", {lb['n']} data" if lb.get("n") else ""
        out.append(f"- {k} ({label}){' WAJIB' if k in REQUIRED else ''}: {st.get('n', 0)} kali dalam 14 hari, gagal {st.get('bad', 0)}, "
                   f"rata-rata {st.get('secs') or 0:.1f} d; terakhir: {lb.get('status', '-')}{got}")
    try:
        snap = await hostinfo.snapshot()
        load = f"CPU {snap['cpu_pct']:.0f}%, RAM terpakai {snap['memory_gb']['used']:.1f}/{snap['memory_gb']['total']:.1f} GB"
    except Exception:
        load = "tidak terbaca"
    running = len([t for t in await workers.active() if t["status"] == "running"])
    return {"lines": out, "troubled": troubled, "load": f"{load}; {running} tugas lain sedang berjalan", "usual": await _usual_collect()}


def queue_prompt(facts: dict, token: str) -> str:
    keys = [k for k, _, _ in COLLECTORS]
    return ("Kamu Hermes, pengatur antrean worker JARVIS untuk fitur Cek berita. Susun urutan mulai dan berapa worker boleh jalan bersamaan, "
            "supaya pengumpulan cepat tapi server tidak dibebani sekaligus. Worker yang lambat sebaiknya mulai lebih dulu. Kamu BOLEH melewati "
            "sumber yang tidak wajib HANYA bila catatannya menunjukkan gagal/kosong, dengan alasan. Jangan mengarang nama worker.\n"
            f"WORKER ({len(keys)}):\n" + "\n".join(facts["lines"])
            + f"\nBEBAN SERVER SEKARANG: {facts['load']}"
            + (f"\nPengumpulan biasanya selesai ±{facts['usual']:.0f} detik." if facts.get("usual") else "")
            + f'\nBalas HANYA JSON: {{"token": "{token}", "jumlah": {len(keys)} jika kamu setuju jumlahnya, "maks_bersamaan": 2-8, '
            '"urutan": ["nama worker sesuai urutan mulai"], "lewati": [{"worker": "…", "alasan": "…"}], "catatan": "1 kalimat"}. '
            '"token" harus persis sama. Setiap worker muncul tepat sekali, di "urutan" atau "lewati".')


def refresh_soon() -> None:
    """Ask Hermes for a new queue in the background (once at a time)."""
    if _planning["task"] is None or _planning["task"].done():
        _planning["task"] = asyncio.create_task(refresh_plan())


async def refresh_plan() -> dict | None:
    """Hermes plans the next run's queue from the workers' record and the load; the watchdog checks it before it is kept."""
    import secrets
    from . import hermes, hermeswatch
    if await hermeswatch.bypassed():
        return None
    try:
        facts = await queue_facts()
        token = secrets.token_hex(3).upper()
        t0, text = time.monotonic(), ""

        async def ask() -> str:
            async for ev in hermes.stream(queue_prompt(facts, token), HERMES_SESSION, model="jarvis-ringan"):
                if ev["type"] == "done":
                    return ev["reply"].text
            return ""
        text = await asyncio.wait_for(ask(), 90)
    except Exception as e:   # Hermes down or too slow: that is also a reason not to wait for it
        await hermeswatch.record("antrean", [f"Hermes tidak bisa dihubungi: {type(e).__name__}: {str(e)[:120]}"])
        return None
    plan, problems = hermeswatch.check_queue(text, token, [k for k, _, _ in COLLECTORS], REQUIRED, facts["troubled"])
    await hermeswatch.record("antrean", problems, text[:200])
    if plan is None:
        log.warning("Hermes' queue for Cek berita rejected by the watchdog: %s", "; ".join(problems))
        return None
    rec = {"plan": plan, "made_at": time.time(), "secs": round(time.monotonic() - t0, 1)}
    await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", PLAN_KEY_Q, rec)
    return rec


@appclock.every(3600, "brief.antrean")
async def _plan_tick() -> None:
    """Keep a fresh queue ready (half a day old at most), so the morning run never waits for Hermes."""
    rec = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", PLAN_KEY_Q)
    if not rec or time.time() - rec.get("made_at", 0) > PLAN_FRESH_S / 2:
        await refresh_plan()


async def about_me() -> dict:
    """What JARVIS knows of him: memory, money, holdings (with their technicals), businesses, job search, the plan he follows. No AI."""
    from . import memory, signals
    facts = [m["text"] for m in await memory.list_("personal", limit=30) if not m.get("stale")][:15]
    about = []
    for name, fn in CONTEXT.items():
        try:
            if t := await asyncio.wait_for(fn(), 6):
                about.append(f"- {name}: {t}")
        except Exception:
            pass
    try:
        held = await signals.holdings()
    except Exception:
        held = []
    async with _client() as c:
        holdings = [q for q in await asyncio.gather(*(_quote(c, n, t) for n, t in held)) if q]
    s = await appsettings.get("brief")
    return {"facts": facts, "about": about, "holdings": holdings, "running": await progress(), "topics": s.get("topics") or []}


KINDS = ("emas", "saham_as", "kripto", "reksa_dana", "tabungan", "bisnis", "karier", "belanja", "lainnya")


def news_lines(g: dict) -> list[str]:
    lines = []
    for k, items in g["news"].items():
        lines.append(f"[{k.upper()}]")
        lines += [f"{i}. {x['title']}" + (f" — {x['summary'][:220]}" if x["summary"] else "") + f" ({x['source']})" for i, x in enumerate(items[:18], 1)]
    return lines


def market_lines(qs: list[dict]) -> list[str]:
    from .signals import tech_words
    out = []
    for q in qs:
        if q.get("last") is None:
            continue
        ch = [f"{w} {q[k]:+.2f}%" for k, w in (("change_1d", "1 hari"), ("change", "5 hari")) if q.get(k) is not None]
        tech = tech_words(q.get("tech"))
        out.append(f"{q['label']}: {q['last']}" + (f" ({', '.join(ch)})" if ch else "") + (f"; {tech}" if tech else ""))
    return out


def signal_lines(g: dict) -> str:
    """Sentiment, search trends and the agenda as text for the brain. Pure."""
    parts = []
    m = g.get("mood") or {}
    if f := m.get("crypto_fng"):
        parts.append(f"Fear & Greed kripto: {f['value']} ({f['label']})" + (f"; seminggu lalu {f['week_ago']} ({f['label_week_ago']})" if "week_ago" in f else ""))
    if m.get("coins"):
        parts.append("Koin paling dicari di CoinGecko: " + ", ".join(m["coins"]))
    out = ("SENTIMEN:\n" + "\n".join(parts)) if parts else ""
    if g.get("trends"):
        out += "\n\nGOOGLE TRENDS INDONESIA (pencarian yang melonjak hari ini):\n" + "\n".join(
            f"{i}. {t['q']}" + (f" ({t['traffic']} pencarian)" if t["traffic"] else "") + (f" — {'; '.join(t['news'])}" if t["news"] else "")
            for i, t in enumerate(g["trends"], 1))
    if g.get("agenda"):
        def when(iso: str) -> str:
            d = datetime.fromisoformat(iso).astimezone(WIB)
            return f"{['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'][d.weekday()]} {d.day}/{d.month} {d:%H.%M}"
        out += "\n\nAGENDA EKONOMI BERDAMPAK TINGGI (WIB):\n" + "\n".join(
            f"- {when(a['at'])} {a['country']} {a['title']}" + "".join(f"; {w} {a[k]}" for k, w in (("actual", "hasil"), ("forecast", "perkiraan"), ("previous", "sebelumnya")) if a[k])
            for a in g["agenda"])
    return out.strip()


STYLES = ("aman", "seimbang", "berani")
SENTIMENTS = ("sangat takut", "takut", "netral", "optimis", "euforia")
PLAN_KEY = "brief:plan"


LANGUAGE = ("Bahasa Indonesia sehari-hari yang tajam tapi mudah dibaca: kalimat pendek, istilah ekonomi dijelaskan dalam kurung sekali saja, "
            "tanpa basa-basi.")


def analysis_prompt(g: dict) -> list[dict]:
    """Stage 2 — the analyst: public data only (news, markets, what people search and say, the agenda). Nothing about him."""
    sys = ("Kamu ANALIS JARVIS. Tugasmu BUKAN merangkum berita satu per satu, tetapi MENYIMPULKAN SITUASI SAAT INI dari semua berita, angka pasar, "
           "sentimen, dan agenda: sebab-akibatnya dengan indikator, dan perkiraan 1–3 bulan ke depan. Kamu tidak tahu apa pun tentang pemilik — "
           "worker berikutnya yang membandingkan hasilmu dengan keadaannya; jadi tulis dampak secara umum (bagi rumah tangga, karyawan, investor "
           "emas/saham/kripto, pedagang online di Indonesia).\n"
           "ATURAN: pakai HANYA data yang diberikan — jangan menambah fakta atau angka. Tiap alasan menunjuk nomor berita sumbernya. Indikator "
           "memakai angka dari DATA PASAR atau yang tertulis di berita. Berita (INDONESIA/EKONOMI/PASAR/DUNIA/TOPIK) adalah fakta yang dilaporkan; "
           "SOSIAL (Reddit) dan GOOGLE TRENDS adalah opini & perhatian publik, bukan fakta — pakai untuk membaca sentimen; sentimen ekstrem sering "
           "menandai pembalikan. Rating teknikal (metode TradingView dari harga harian) = sinyal arah jangka pendek, bukan kepastian. AGENDA EKONOMI "
           "dipakai untuk tanda skenario.\n" + LANGUAGE + "\nKembalikan JSON:\n"
           '{"judul": "satu kalimat inti situasi hari ini",\n'
           ' "intinya": ["3 poin, masing-masing maks 20 kata: yang paling perlu diketahui hari ini"],\n'
           ' "situasi": "3–5 kalimat: keadaan ekonomi & dunia sekarang dan arahnya",\n'
           ' "suasana": "positif|campuran|waspada",\n'
           ' "sentimen": {"label": "sangat takut|takut|netral|optimis|euforia", "ringkas": "1–2 kalimat: suasana hati pasar & publik", '
           '"sinyal": [{"sumber": "Google Trends|Reddit|Fear & Greed|CoinGecko|Teknikal|Berita", "isi": "1 kalimat dengan angkanya"}] (2–4)},\n'
           ' "tema": [{"judul": "…", "kesimpulan": "1–2 kalimat", "rantai": ["sebab", "akibat", "akibat berikutnya", "dampak umum"] (3–5 mata rantai, '
           'masing-masing maks 8 kata), "indikator": [{"nama": "…", "nilai": "angka/arah persis dari data", "arti": "singkat"}], '
           '"alasan": [{"isi": "1 kalimat", "nomor": "EKONOMI 3"}]}] (2–4 tema),\n'
           ' "skenario": [{"nama": "…", "kemungkinan": "besar|sedang|kecil", "isi": "apa yang terjadi 1–3 bulan ke depan, 1–2 kalimat", '
           '"tanda": "angka/kejadian yang menandakan skenario ini sedang terjadi"}] (2–3),\n'
           ' "waspada": [{"isi": "…", "nomor": "DUNIA 2"}] (0–3)}\n'
           '"nomor" = bagian dan nomor berita persis seperti di daftar; jangan menulis nomor berita (mis. "DUNIA 3") di kalimat lain.')
    user = (f"CUACA: {g.get('weather') or '-'}\n\nDATA PASAR (terakhir; teknikal metode TradingView dari harga harian):\n"
            + ("\n".join(market_lines(g.get("markets") or [])) or "-")
            + ("\n\n" + signal_lines(g) if signal_lines(g) else "")
            + "\n\nBERITA & MEDIA SOSIAL (24 jam terakhir):\n" + "\n".join(news_lines(g)))
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def _analysis_text(a: dict) -> str:
    """The analyst's result as the next worker reads it (no links, no news numbers). Pure."""
    keep = {k: a.get(k) for k in ("judul", "intinya", "situasi", "suasana", "sentimen", "skenario")}
    keep["tema"] = [{k: t.get(k) for k in ("judul", "kesimpulan", "rantai", "indikator")} for t in a.get("tema") or []]
    keep["waspada"] = [w.get("isi") for w in a.get("waspada") or []]
    return json.dumps(keep, ensure_ascii=False)


def persona_prompt(analysis: dict, me: dict, g: dict) -> list[dict]:
    """Stage 3 — the worker that is him: what it knows about him, compared with the analyst's result → his position, the impact of each
    theme on him, three plans, the quick opportunities, how his running plan stands."""
    sys = ("Kamu adalah PEMILIK sendiri ('aku'): karyawan & pengusaha di Indonesia (Bogor–Jakarta) yang berinvestasi (emas, saham AS, kripto, reksa "
           "dana lewat Pluang) dan punya bisnis online. Seorang analis sudah menyimpulkan situasi hari ini (ANALISIS). Tugasmu: kumpulkan apa yang "
           "kamu tahu tentang dirimu (DATA TENTANG AKU), BANDINGKAN dengan analisis itu — di mana aku kuat, di mana aku rentan, apa arti tiap tema "
           "bagiku — lalu putuskan apa yang akan aku lakukan 1–3 bulan ke depan.\n"
           "ATURAN: pakai HANYA ANALISIS, data pasar, dan DATA TENTANG AKU — jangan menambah fakta atau angka. Jumlah uang hanya dari data "
           "keuanganku (atau persen dari gajiku). Dana darurat dan tagihan didahulukan bila belum aman. Jangan berutang untuk investasi. Investasi "
           "tetap kuputuskan sendiri lewat persetujuan & batas di menu Investasi — rencana bukan perintah beli/jual. Waktuku terbatas (kerja kantoran): "
           "langkah harus muat di malam/akhir pekan. Bila ada RENCANA BERJALAN, nilai dulu: lanjutkan, percepat, atau sesuaikan.\n"
           + LANGUAGE + " Selalu bicara sebagai diriku ('aku').\nKembalikan JSON:\n"
           '{"posisi": {"ringkas": "2–3 kalimat: posisiku sekarang dibanding situasi ini", "kuat": ["…"] (1–3), "rentan": ["…"] (1–3)},\n'
           ' "dampak": [{"tema": "judul tema PERSIS seperti di ANALISIS", "bagiku": "1–2 kalimat: artinya bagiku", "arah": "untung|rugi|campuran"}] (satu per tema),\n'
           ' "rencana": [{"nama": "judul singkat", "gaya": "aman|seimbang|berani", "bulan": 1|2|3, '
           '"kenapa": "2–3 kalimat sebagai aku, merujuk tema/skenario dan posisiku", "target": "hasil terukur di akhir rencana", '
           '"langkah": [{"minggu": 1, "apa": "tindakan konkret yang selesai dalam seminggu, diawali kata kerja", "kaitan": "' + "|".join(KINDS) + '"}] '
           '(4–8 langkah, urut minggu, minggu maks bulan×4), "risiko": "…", "berhenti_jika": "tanda untuk berhenti atau menyesuaikan"}] '
           '(TEPAT 3 rencana: satu aman, satu seimbang, satu berani — PILIHAN yang berdiri sendiri, BUKAN tahapan berurutan: masing-masing lengkap '
           'dan dimulai minggu 1),\n'
           ' "evaluasi_rencana": "bila ada RENCANA BERJALAN: 1–2 kalimat — lanjutkan, percepat, atau sesuaikan, dan kenapa; selain itu kosong",\n'
           ' "peluang": [{"aksi": "yang bisa kulakukan segera", "kenapa": "berdasar tema/indikator mana", "kaitan": "' + "|".join(KINDS) + '", '
           '"horizon": "hari ini|minggu ini|bulan ini", "risiko": "…", "yakin": "rendah|sedang|tinggi"}] (2–4),\n'
           ' "ucapan": "3–4 kalimat untuk DIBACAKAN kepadaku: situasinya, artinya bagiku, dan rencana yang paling masuk akal"}')
    agenda = signal_lines({"agenda": g.get("agenda") or []})
    user = ("ANALISIS (dari worker analis):\n" + _analysis_text(analysis)
            + "\n\nDATA PASAR:\n" + ("\n".join(market_lines(g.get("markets") or [])) or "-")
            + (f"\n\n{agenda}" if agenda else "")
            + "\n\nDATA TENTANG AKU:\n" + ("\n".join(me.get("facts") or []) or "-") + ("\n" + "\n".join(me["about"]) if me.get("about") else "")
            + (f"\nTopik yang kuikuti: {', '.join(me['topics'])}" if me.get("topics") else "")
            + ("\n\nASET MILIKKU (teknikal):\n" + "\n".join(market_lines(me["holdings"])) if me.get("holdings") else "")
            + (f"\n\nRENCANA BERJALAN (pilihanku dari Cek berita sebelumnya):\n{running_text(me['running'])}" if me.get("running") else ""))
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def merge(a: dict, p: dict) -> dict:
    """The analyst's result with the persona's: each theme gets what it means for him (matched by title, else by order). Pure."""
    out = {**a, **{k: p.get(k) for k in ("rencana", "peluang", "evaluasi_rencana", "posisi") if p.get(k)}}
    out["ucapan"] = p.get("ucapan") or a.get("ucapan") or ""
    hits = [d for d in (p.get("dampak") or []) if isinstance(d, dict)]
    by_title = {str(d.get("tema", "")).strip().lower(): d for d in hits}
    tema = []
    for i, t in enumerate([t for t in (a.get("tema") or []) if isinstance(t, dict)]):
        d = by_title.get(str(t.get("judul", "")).strip().lower()) or (hits[i] if i < len(hits) else {})
        tema.append({**t, "dampak": d.get("bagiku") or t.get("dampak") or "", "arah": d.get("arah")})
    out["tema"] = tema
    return out


def _find(news: dict, ref: str):
    m = re.match(r"\s*([A-Za-z]+)\s+(\d+)", ref or "")
    if not m:
        return None
    items = news.get(m.group(1).lower()) or []
    i = int(m.group(2)) - 1
    return items[i] if 0 <= i < len(items) else None


def _reason(x, news: dict) -> dict | None:
    if isinstance(x, str):
        x = {"isi": x}
    if not isinstance(x, dict) or not str(x.get("isi") or "").strip():
        return None
    src = _find(news, str(x.get("nomor") or ""))
    return {"isi": str(x["isi"])[:400], "sumber": src["source"] if src else "", "link": src["link"] if src else ""}


_SECTIONS = r"(?:INDONESIA|EKONOMI|PASAR|DUNIA|TOPIK|SOSIAL)\s+\d+"
_REFS = re.compile(rf"\s*[\(\[]\s*{_SECTIONS}(?:\s*[,;/&]\s*(?:dan\s+)?{_SECTIONS})*\s*[\)\]]|\s*\b{_SECTIONS}\b", re.I)


def _t(v, n: int) -> str:
    """Readable text: one line, no news numbers ('(TOPIK 7, DUNIA 16)') — those belong in 'nomor'. Pure."""
    return _REFS.sub("", " ".join(str(v or "").split())).strip()[:n]


def clean_analysis(data: dict, news: dict) -> dict:
    """The brain's analysis kept to its shape, every reason linked to the news it came from ('nomor'). Pure."""
    t = _t
    out = {"judul": t(data.get("judul"), 200), "situasi": t(data.get("situasi"), 1200), "ucapan": t(data.get("ucapan"), 800),
           "suasana": data.get("suasana") if data.get("suasana") in ("positif", "campuran", "waspada") else "campuran"}
    out["tema"] = []
    for x in (data.get("tema") or [])[:4]:
        if not isinstance(x, dict) or not x.get("judul"):
            continue
        out["tema"].append({"judul": t(x["judul"], 120), "kesimpulan": t(x.get("kesimpulan"), 400), "dampak": t(x.get("dampak"), 400),
                            "arah": x.get("arah") if x.get("arah") in ("untung", "rugi", "campuran") else None,
                            "indikator": [{"nama": t(i.get("nama"), 60), "nilai": t(i.get("nilai"), 60), "arti": t(i.get("arti"), 160)}
                                          for i in (x.get("indikator") or [])[:5] if isinstance(i, dict) and i.get("nama")],
                            "alasan": [r for r in (_reason(r, news) for r in (x.get("alasan") or [])[:5]) if r]})
    out["peluang"] = [{"aksi": t(p.get("aksi"), 200), "kenapa": t(p.get("kenapa"), 300), "risiko": t(p.get("risiko"), 200),
                       "kaitan": p.get("kaitan") if p.get("kaitan") in KINDS else "lainnya",
                       "horizon": p.get("horizon") if p.get("horizon") in ("hari ini", "minggu ini", "bulan ini") else "minggu ini",
                       "yakin": p.get("yakin") if p.get("yakin") in ("rendah", "sedang", "tinggi") else "sedang"}
                      for p in (data.get("peluang") or [])[:5] if isinstance(p, dict) and p.get("aksi")]
    out["waspada"] = [r for r in (_reason(r, news) for r in (data.get("waspada") or [])[:3]) if r]
    out["intinya"] = [t(x, 200) for x in (data.get("intinya") or [])[:6] if isinstance(x, str) and x.strip()][:3]
    for th, x in zip(out["tema"], [x for x in (data.get("tema") or [])[:4] if isinstance(x, dict) and x.get("judul")]):
        th["rantai"] = [t(c, 80) for c in (x.get("rantai") or [])[:8] if isinstance(c, str) and c.strip()][:5]
    out["skenario"] = [{"nama": t(x.get("nama"), 80), "isi": t(x.get("isi"), 300), "tanda": t(x.get("tanda"), 200),
                        "kemungkinan": x.get("kemungkinan") if x.get("kemungkinan") in ("besar", "sedang", "kecil") else "sedang"}
                       for x in (data.get("skenario") or [])[:3] if isinstance(x, dict) and x.get("nama")]
    out["rencana"] = [p for p in (clean_plan(x) for x in (data.get("rencana") or [])[:3]) if p]
    out["evaluasi_rencana"] = t(data.get("evaluasi_rencana"), 400)
    po = data.get("posisi") if isinstance(data.get("posisi"), dict) else {}
    out["posisi"] = {"ringkas": t(po.get("ringkas"), 500), "kuat": [t(x, 160) for x in (po.get("kuat") or [])[:3] if isinstance(x, str) and x.strip()],
                     "rentan": [t(x, 160) for x in (po.get("rentan") or [])[:3] if isinstance(x, str) and x.strip()]} if po.get("ringkas") else None
    se = data.get("sentimen") if isinstance(data.get("sentimen"), dict) else {}
    out["sentimen"] = {"label": se.get("label") if se.get("label") in SENTIMENTS else "netral", "ringkas": t(se.get("ringkas"), 300),
                       "sinyal": [{"sumber": t(x.get("sumber"), 30), "isi": t(x.get("isi"), 200)} for x in (se.get("sinyal") or [])[:4]
                                  if isinstance(x, dict) and x.get("isi")]} if se.get("ringkas") or se.get("sinyal") else None
    return out


def clean_plan(x) -> dict | None:
    """One 'if I were you' plan: 1–3 months, 1–8 weekly steps inside it, in week order, starting in week 1 (each plan is a choice of its
    own, not a later phase of another). Pure."""
    if not isinstance(x, dict) or not x.get("nama"):
        return None
    t = _t
    try:
        months = min(3, max(1, int(x.get("bulan") or 1)))
    except (TypeError, ValueError):
        months = 1
    steps = []
    for st in (x.get("langkah") or [])[:8]:
        if not isinstance(st, dict) or not str(st.get("apa") or "").strip():
            continue
        try:
            week = int(st.get("minggu") or 1)
        except (TypeError, ValueError):
            week = 1
        steps.append({"minggu": min(months * 4, max(1, week)), "apa": t(st["apa"], 160),
                      "kaitan": st.get("kaitan") if st.get("kaitan") in KINDS else "lainnya"})
    if not steps:
        return None
    shift = min(st["minggu"] for st in steps) - 1
    for st in steps:
        st["minggu"] -= shift
    return {"nama": t(x["nama"], 80), "gaya": x.get("gaya") if x.get("gaya") in STYLES else "seimbang", "bulan": months,
            "kenapa": t(x.get("kenapa"), 500), "target": t(x.get("target"), 200), "risiko": t(x.get("risiko"), 200),
            "berhenti_jika": t(x.get("berhenti_jika"), 200), "langkah": sorted(steps, key=lambda st: st["minggu"])}


def plan_tasks(plan: dict, start: date, keep: list[int] | None = None) -> list[dict]:
    """The steps he keeps as Catatan tasks: due at the end of their week, the first week marked important. Pure."""
    steps = [st for i, st in enumerate(plan["langkah"]) if keep is None or i in keep]
    return [{"text": f"{st['apa']} — rencana “{plan['nama']}”", "due": (start + timedelta(days=st["minggu"] * 7 - 1)).isoformat(),
             "priority": 2 if st["minggu"] == 1 else None} for st in steps]


async def compose(trigger: str = "schedule", reserved: bool = False) -> dict:
    """Owner 2026-10-31: collectors (one worker per source, in parallel) → one analyst → one worker that is him, which gathers what is known
    about him and compares it with the analysis. Each step is its own run in the master flow; the steps are shown live and kept.
    reserved: the caller already took the run (the app's button, which answers before the workers finish)."""
    if _state["running"] and not reserved:
        raise RuntimeError("cek berita sedang dibuat — tunggu sebentar")
    _state.update(running=True, steps=[], started=datetime.now(timezone.utc).isoformat(), error=None, log=[])
    await log_line("Cek berita dimulai")
    try:
        return await _compose(trigger)
    except Exception as e:
        _state["error"] = str(e)[:300]
        await log_line(f"✗ Gagal: {_state['error']}", "bad")
        raise
    finally:
        _state["running"] = False
        await hub.broadcast({"type": "brief", "running": False, "steps": _state["steps"], "error": _state["error"], "log": _state["log"][-40:]})
        refresh_soon()   # Hermes plans the next run's queue now, while nobody is waiting


async def _compose(trigger: str) -> dict:
    g = {"news": {}, "markets": [], "trends": [], "mood": {}, "agenda": [], "weather": "", **await gather(trigger)}
    if not any(g["news"].values()) and not g["markets"]:
        raise RuntimeError("tidak ada berita maupun data pasar yang terkumpul — coba lagi nanti")

    t0 = time.monotonic()
    await _step("analisa", "analis", "Analis: simpulkan situasi", None, t0)
    after = {"antrean": "antrean Hermes: setelah semua pengumpul (urutan tetap)"}
    ra = await master.run(master.Job("brief", "analisa", "cek berita: simpulkan situasi, sebab-akibat, sentimen, dan skenario dari data publik",
                                     trigger=trigger, messages=analysis_prompt(g), json_out=True, heavy=True, no_free=True, max_tokens=4000, data=after))
    await _step("analisa", "analis", "Analis: simpulkan situasi", ra, t0)
    if ra["status"] != "done":
        raise RuntimeError(ra.get("error") or "analisis gagal")
    analysis = ra["result"] if isinstance(ra["result"], dict) else {}

    t0 = time.monotonic()
    await _step("jadi-kamu", "tentang-aku", "Jadi kamu: kumpulkan data tentangmu", None, t0)
    rm = await master.run(master.Job("brief", "kumpul-tentang-aku", "cek berita: kumpulkan data tentang pemilik", trigger=trigger, skill=about_me,
                                     data={"antrean": "antrean Hermes: setelah analis (urutan tetap)"}))
    me = rm.get("result") if rm["status"] == "done" else {}
    await _step("jadi-kamu", "tentang-aku", "Jadi kamu: kumpulkan data tentangmu", rm, t0, _size((me or {}).get("about")) + _size((me or {}).get("facts")))
    t0 = time.monotonic()
    await _step("jadi-kamu", "bandingkan", "Jadi kamu: bandingkan & susun rencana", None, t0)
    rp = await master.run(master.Job("brief", "jadi-pemilik", "cek berita: sebagai pemilik, bandingkan analisis dengan keadaannya dan susun rencana",
                                     trigger=trigger, messages=persona_prompt(analysis, me or {}, g), json_out=True, heavy=True, no_free=True,
                                     max_tokens=4500, data={"antrean": "antrean Hermes: terakhir, membandingkan (urutan tetap)"}))
    await _step("jadi-kamu", "bandingkan", "Jadi kamu: bandingkan & susun rencana", rp, t0)
    persona = rp["result"] if rp["status"] == "done" and isinstance(rp["result"], dict) else {}   # without it the analysis still stands

    data = clean_analysis(merge(analysis, persona), g["news"])
    if not data["situasi"] and not data["tema"]:
        raise RuntimeError("analisisnya kosong — coba lagi")
    data |= {"markets": g["markets"], "holdings": (me or {}).get("holdings") or [], "trends": g["trends"][:10], "mood": g["mood"], "agenda": g["agenda"],
             "weather": g["weather"], "lane": ra.get("lane"), "count": sum(len(v) for v in g["news"].values()),
             "social": len(g["news"].get("sosial") or []), "pipeline": _state["steps"], "collect_secs": g.get("collect_secs"),
             "queue": {k: (g.get("queue") or {}).get(k) for k in ("source", "why", "maks", "urutan", "lewati", "made_at")},
             "persona_error": "" if persona else str(rp.get("error") or "worker 'jadi kamu' tidak memberi hasil")[:200]}
    day = datetime.now(WIB).date()
    srcs = sorted({x["source"].split(" · ")[0] for v in g["news"].values() for x in v}) + [n for n, ok in (
        ("Google Trends", g["trends"]), ("Fear & Greed", g["mood"].get("crypto_fng")), ("CoinGecko", g["mood"].get("coins")),
        ("Forex Factory", g["agenda"]), ("Yahoo Finance (teknikal ala TradingView)", g["markets"])) if ok]
    await db.pool().execute("""INSERT INTO briefs (day, data, sources, run_id) VALUES ($1, $2, $3, $4)
                               ON CONFLICT (day) DO UPDATE SET data = EXCLUDED.data, sources = EXCLUDED.sources, run_id = EXCLUDED.run_id, created_at = now()""",
                            day, data, srcs, ra["run_id"])
    await log_line("✓ Cek berita selesai dan tersimpan", "ok")
    await db.pool().execute("UPDATE briefs SET data = data || jsonb_build_object('log', $2::jsonb) WHERE day = $1", day, _state["log"])
    await hub.broadcast({"type": "notify", "title": "Cek berita siap", "text": (data["judul"] or data["situasi"])[:200], "kind": "info", "route": "#/brief"})
    return data


# ---------- the plan he picks ----------

def running_text(run: dict | None) -> str:
    """What the next analysis is told about the plan he is following. Pure."""
    if not run:
        return ""
    nxt = f"; langkah berikutnya: {run['next']['text']} (tenggat {run['next']['due']})" if run.get("next") else ""
    return (f"{run['nama']} ({run['gaya']}, {run['bulan']} bulan, sejak {run['day']}); target: {run['target'] or '-'}; "
            f"selesai {run['done']}/{run['total']} langkah{nxt}; berhenti jika: {run['berhenti_jika'] or '-'}")


async def progress() -> dict | None:
    """The plan he picked and how far it is (ticked in Catatan); None when none, or two weeks after it ended."""
    from . import notes
    rec = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", PLAN_KEY)
    if not rec or date.fromisoformat(rec["ends"]) + timedelta(days=14) < datetime.now(WIB).date():
        return None
    page = await notes.ensure_special("tasks")
    blocks = {b["id"]: b for b in page["blocks"] if b.get("type") == "todo"}
    mine = [blocks[t["id"]] for t in rec["tasks"] if t["id"] in blocks]
    open_ = sorted((b for b in mine if not b.get("checked")), key=lambda b: b.get("due") or "9999")
    return {**{k: rec[k] for k in ("nama", "gaya", "bulan", "target", "berhenti_jika", "day", "ends")},
            "done": sum(1 for b in mine if b.get("checked")), "total": len(rec["tasks"]),
            "next": {"text": open_[0]["text"], "due": open_[0].get("due")} if open_ else None}


async def choose(index: int, keep: list[int] | None, who: str) -> dict:
    """His pick: the plan's steps (those he kept) join Catatan's tasks, week by week from today; it becomes the running plan."""
    from . import notes
    b = await today()
    plans = (b or {}).get("data", {}).get("rencana") or []
    if not 0 <= index < len(plans):
        raise ValueError("rencana itu tidak ada di Cek berita terakhir")
    plan = plans[index]
    if plan.get("dipilih"):
        raise ValueError(f"rencana ini sudah kamu pilih ({plan['dipilih']}) — tugasnya ada di Catatan")
    start = datetime.now(WIB).date()
    tasks = plan_tasks(plan, start, keep)
    if not tasks:
        raise ValueError("pilih minimal satu langkah")
    added = []
    for t in tasks:
        r = await notes.add_task(t["text"], t["due"], t["priority"], who, "#/brief")
        added.append({"id": r["task"]["id"], "text": t["text"], "due": t["due"]})
    rec = {"nama": plan["nama"], "gaya": plan["gaya"], "bulan": plan["bulan"], "target": plan["target"], "berhenti_jika": plan["berhenti_jika"],
           "day": start.isoformat(), "ends": (start + timedelta(days=plan["bulan"] * 28)).isoformat(), "brief_day": str(b["day"]), "tasks": added}
    await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", PLAN_KEY, rec)
    plans[index] = {**plan, "dipilih": start.isoformat()}
    await db.pool().execute("UPDATE briefs SET data = jsonb_set(data, '{rencana}', $2::jsonb) WHERE day = $1", b["day"], plans)
    await audit.record(who, "brief.plan_chosen", f"brief:{b['day']}", plan=plan["nama"], tasks=len(added))
    return {"ok": True, "added": len(added), "plan": rec}


async def _brief_time() -> str:
    s = await appsettings.get("brief")
    return s["time"] if s.get("enabled") else ""


@appclock.daily(_brief_time, "brief.daily")
async def daily() -> None:
    await compose("schedule")


async def today() -> dict | None:
    row = await db.pool().fetchrow("SELECT day, data, sources, created_at FROM briefs ORDER BY day DESC LIMIT 1")
    return dict(row) if row else None


@home.provider("brief")
async def _home(m: home.Moment) -> list[dict]:
    if _state["running"]:   # the workers are at it: a card that says so, whatever the hour
        done = len([x for x in _state["steps"] if x["status"] in ("selesai", "gagal", "dilewati")])
        return [{"id": "brief", "title": "Cek berita sedang dianalisis…", "sub": f"{done}/{len(COLLECTORS) + 3} worker selesai · ketuk untuk melihat log",
                 "route": "#/brief", "icon": "news", "tone": "cyan", "score": 70}]
    if m.slot not in ("subuh", "pagi", "kerja"):
        return []
    b = await today()
    if not b or b["day"] != m.now.date():
        return []
    d = b["data"]
    n = len(d.get("rencana") or [])
    return [{"id": "brief", "title": "Cek berita", "sub": (d.get("judul") or "situasi hari ini & peluangmu")[:90] + (f" · {n} rencana untukmu" if n else ""),
             "route": "#/brief", "icon": "news", "tone": "amber", "score": 55 if m.slot in ("subuh", "pagi") else 25, "cta": "Baca" if m.slot == "pagi" else None}]


@setup_status.check("brief")
async def _ready() -> dict:
    return setup_status.ready()


@router.get(API)
async def api_brief(device: dict = Depends(owner)):
    from . import hermeswatch
    rec = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", PLAN_KEY_Q)
    if not _state["running"] and (not rec or time.time() - rec.get("made_at", 0) > 6 * 3600):
        refresh_soon()   # he is looking: have a fresh queue ready before he taps
    w = await hermeswatch.state()
    return {"brief": await today(), "settings": await appsettings.get("brief"), "running": await progress(),
            "progress": {**{k: _state[k] for k in ("running", "steps", "started", "error")}, "log": _state["log"][-40:]},
            "hermes": {"bypass": await hermeswatch.bypassed(), "checks": w["checks"][:5], "plan_at": (rec or {}).get("made_at")}}


class PlanIn(BaseModel):
    index: int = Field(ge=0, le=2)
    keep: list[int] | None = Field(default=None, max_length=8)


@router.post(API + "/plan")
async def api_brief_plan(body: PlanIn, device: dict = Depends(owner)):
    """The plan he picks → tasks in Catatan (master flow; a skill: no AI)."""
    who = actor(device)
    r = await master.run(master.Job("brief", "pilih-rencana", f"rencana dari Cek berita #{body.index + 1} → tugas Catatan", trigger="owner",
                                    skill=lambda: choose(body.index, body.keep, who)))
    if r["status"] != "done":
        raise HTTPException(409, str(r.get("error") or "gagal"))
    return r["result"]


@router.post(API + "/now")
async def api_brief_now(device: dict = Depends(owner)):
    """Starts the workers and answers at once; the page follows them live (events of type 'brief')."""
    if not _state["running"]:
        _state["running"] = True   # taken now, so a second tap does not start a second run
        asyncio.create_task(_now())
    return {"started": True, "progress": {**{k: _state[k] for k in ("running", "steps", "started", "error")}, "log": _state["log"][-40:]}}


async def _now() -> None:
    try:
        await compose("owner", reserved=True)
    except Exception as e:
        log.warning("cek berita (owner) failed: %s", e)
