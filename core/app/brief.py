"""Brief pagi (ADR-087): every morning (05.45 by default) the state of Indonesia and the world, the markets, the weather — and first, the
few things that touch the owner himself (his business, his investments, his trip, his day).

Gathering is a fixed procedure (RSS from several newsrooms, market quotes, Open-Meteo); writing it is one job of the master flow (Hermes
decides which brain; the light one normally, the heavy one when the light one fails). Each item keeps its source link. The result is kept
per day and the phone gets a notification that opens it."""

import asyncio
import html as htmlmod
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Awaitable, Callable

import httpx
from fastapi import APIRouter, Depends

from . import appclock, appsettings, db, home, hub, master, setup_status
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/brief"

FEEDS = {
    "indonesia": [("Antara", "https://www.antaranews.com/rss/terkini.xml"), ("CNN Indonesia", "https://www.cnnindonesia.com/nasional/rss"),
                  ("Tempo", "https://rss.tempo.co/nasional")],
    "ekonomi": [("CNBC Indonesia", "https://www.cnbcindonesia.com/news/rss"), ("Antara Ekonomi", "https://www.antaranews.com/rss/ekonomi.xml")],
    "dunia": [("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"), ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml")],
}
MARKETS = [("IHSG", "^JKSE"), ("Rupiah/USD", "IDR=X"), ("Emas", "GC=F"), ("S&P 500", "^GSPC"), ("Bitcoin", "BTC-USD")]
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
    try:
        r = await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "5d", "interval": "1d"})
        res = r.json()["chart"]["result"][0]
        closes = res["indicators"]["quote"][0]["close"]
        last = next((v for v in reversed(closes) if isinstance(v, (int, float))), None)
        return {"label": label, "symbol": sym, "last": round(last, 2) if last else None, "change": change_pct(closes)}
    except Exception:
        return None


async def gather() -> dict:
    """News, markets and weather — the fixed part of the brief (no AI)."""
    from . import weather
    now = datetime.now(timezone.utc)
    async with _client() as c:
        feeds = {k: await asyncio.gather(*(_feed(c, s, u, now) for s, u in v)) for k, v in FEEDS.items()}
        quotes = [q for q in await asyncio.gather(*(_quote(c, l, s) for l, s in MARKETS)) if q]
    news = {k: [x for lst in v for x in lst] for k, v in feeds.items()}
    about = []
    for name, fn in CONTEXT.items():
        try:
            if t := await asyncio.wait_for(fn(), 6):
                about.append(f"- {name}: {t}")
        except Exception:
            pass
    return {"news": news, "markets": quotes, "weather": await weather.today_text(), "about": about}


def prompt(g: dict, owner_facts: list[str], topics: list[str]) -> list[dict]:
    lines = []
    for k, items in g["news"].items():
        lines.append(f"[{k.upper()}]")
        lines += [f"{i}. {x['title']} — {x['summary'][:160]} ({x['source']})" for i, x in enumerate(items[:16], 1)]
    mk = "; ".join(f"{q['label']} {q['change']:+.2f}%" for q in g["markets"] if q.get("change") is not None)
    sys = ("Kamu menulis BRIEF PAGI untuk pemilik JARVIS: pengusaha di Indonesia (Bogor–Jakarta) yang juga berinvestasi. Pakai HANYA berita yang "
           "diberikan — jangan menambah fakta. Bahasa Indonesia, singkat, tenang, langsung ke inti. Kembalikan JSON:\n"
           '{"perlu": [{"judul": "…", "isi": "1–2 kalimat: apa artinya BAGI PEMILIK dan apa yang sebaiknya ia lakukan", "nomor": "INDONESIA 3"}] (maks 3, '
           'hanya yang benar-benar menyentuh bisnis/investasi/perjalanan/hari pemilik; boleh kosong),\n'
           ' "indonesia": [{"isi": "1 kalimat", "nomor": "INDONESIA 1"}] (3–4 terpenting), "ekonomi": [{"isi": "…", "nomor": "EKONOMI 2"}] (2–3),'
           ' "dunia": [{"isi": "…", "nomor": "DUNIA 1"}] (2–3), "ucapan": "2–3 kalimat pembuka untuk DIBACAKAN (sebut 1 hal paling penting)"}\n'
           '"nomor" = bagian dan nomor berita sumbernya persis seperti di daftar.')
    user = (f"Tentang pemilik:\n" + "\n".join(owner_facts[:15] + g["about"]) + (f"\nTopik yang ia ikuti: {', '.join(topics)}" if topics else "")
            + f"\n\nCuaca: {g['weather'] or '-'}\nPasar kemarin: {mk or '-'}\n\nBERITA (24 jam terakhir):\n" + "\n".join(lines))
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


def link_sources(data: dict, news: dict) -> dict:
    """Each written item gets the link of the news it came from ('nomor' → that item). Pure."""
    def find(ref: str):
        m = re.match(r"\s*([A-Za-z]+)\s+(\d+)", ref or "")
        if not m:
            return None
        items = news.get(m.group(1).lower()) or []
        i = int(m.group(2)) - 1
        return items[i] if 0 <= i < len(items) else None
    out = {}
    for sec in ("perlu", "indonesia", "ekonomi", "dunia"):
        rows = []
        for x in data.get(sec) or []:
            if isinstance(x, str):
                x = {"isi": x}
            if not isinstance(x, dict) or not (x.get("isi") or x.get("judul")):
                continue
            src = find(str(x.get("nomor") or ""))
            rows.append({"judul": str(x.get("judul") or "")[:160], "isi": str(x.get("isi") or "")[:400],
                         "sumber": src["source"] if src else "", "link": src["link"] if src else ""})
        out[sec] = rows[:4]
    out["ucapan"] = str(data.get("ucapan") or "")[:600]
    return out


async def compose(trigger: str = "schedule") -> dict:
    from . import memory
    s = await appsettings.get("brief")
    g = await gather()
    facts = [m["text"] for m in await memory.list_("personal", limit=30) if not m.get("stale")]
    r = await master.run(master.Job("brief", "compose", "susun brief pagi dari berita, pasar, dan konteks pemilik", trigger=trigger,
                                    messages=prompt(g, facts, s.get("topics") or []), json_out=True, max_tokens=1600))
    if r["status"] != "done":
        raise RuntimeError(r.get("error") or "brief gagal")
    data = link_sources(r["result"] if isinstance(r["result"], dict) else {}, g["news"])
    data |= {"markets": g["markets"], "weather": g["weather"], "lane": r.get("lane"), "count": sum(len(v) for v in g["news"].values())}
    day = datetime.now(WIB).date()
    srcs = sorted({x["source"] for v in g["news"].values() for x in v})
    await db.pool().execute("""INSERT INTO briefs (day, data, sources, run_id) VALUES ($1, $2, $3, $4)
                               ON CONFLICT (day) DO UPDATE SET data = EXCLUDED.data, sources = EXCLUDED.sources, run_id = EXCLUDED.run_id, created_at = now()""",
                            day, data, srcs, r["run_id"])
    first = (data["perlu"] or data["indonesia"] or [{"isi": "Brief pagi siap."}])[0]
    await hub.broadcast({"type": "notify", "title": "Brief pagi siap", "text": (first.get("judul") or first.get("isi"))[:200], "kind": "info", "route": "#/brief"})
    return data


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
    if m.slot not in ("subuh", "pagi", "kerja"):
        return []
    b = await today()
    if not b or b["day"] != m.now.date():
        return []
    d = b["data"]
    n = len(d.get("perlu") or [])
    return [{"id": "brief", "title": "Brief pagi", "sub": f"{n} hal yang menyangkut kamu" if n else "Indonesia, dunia, pasar", "route": "#/brief",
             "icon": "news", "tone": "amber", "score": 55 if m.slot in ("subuh", "pagi") else 25, "cta": "Baca brief" if m.slot == "pagi" else None}]


@setup_status.check("brief")
async def _ready() -> dict:
    return setup_status.ready()


@router.get(API)
async def api_brief(device: dict = Depends(owner)):
    return {"brief": await today(), "settings": await appsettings.get("brief")}


@router.post(API + "/now")
async def api_brief_now(device: dict = Depends(owner)):
    return {"brief": {"data": await compose("owner"), "day": datetime.now(WIB).date().isoformat()}}
