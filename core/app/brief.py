"""Cek berita (ADR-087; was "Brief pagi" — owner 2026-10-31: "bukan lg listing berita tp smartnews bisa menyimpulkan situasi saat ini dan
mengumpulkan indikator reasonnya, dan peluang apa yg bisa diambil dari situasi tersebut yg menguntungkan bagi ekonomi saya").

Every morning (05.45 by default, or when he asks) the news of the last day from several newsrooms and the market indicators are gathered (a
fixed procedure, no AI), then the heavy brain (master flow; personal context, so never a free endpoint) reads them together with what JARVIS
knows of his money — salary pots, his investments' mix, his businesses, his job search — and writes an ANALYSIS, not a list: what the
situation is, the themes behind it each with its indicators (numbers from the market data or the news only) and the reasons (each linked to
its news), what it means for him, and the opportunities he could take (with the risk and how sure it is) — never an order to buy or sell.
Kept per day; the phone gets a notice that opens it."""

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
MARKETS = [("IHSG", "^JKSE"), ("Rupiah/USD", "IDR=X"), ("Emas", "GC=F"), ("S&P 500", "^GSPC"), ("Nasdaq", "^IXIC"), ("Bitcoin", "BTC-USD"),
           ("Minyak Brent", "BZ=F"), ("Imbal hasil obligasi AS 10th", "^TNX"), ("Indeks dolar (DXY)", "DX-Y.NYB")]
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


KINDS = ("emas", "saham_as", "kripto", "reksa_dana", "tabungan", "bisnis", "karier", "belanja", "lainnya")


def news_lines(g: dict) -> list[str]:
    lines = []
    for k, items in g["news"].items():
        lines.append(f"[{k.upper()}]")
        lines += [f"{i}. {x['title']} — {x['summary'][:220]} ({x['source']})" for i, x in enumerate(items[:18], 1)]
    return lines


def market_lines(g: dict) -> list[str]:
    return [f"{q['label']}: {q['last']} ({q['change']:+.2f}% 5 hari)" if q.get("change") is not None else f"{q['label']}: {q['last']}"
            for q in g["markets"] if q.get("last") is not None]


def prompt(g: dict, owner_facts: list[str], topics: list[str]) -> list[dict]:
    sys = ("Kamu analis JARVIS untuk pemilik: karyawan & pengusaha di Indonesia (Bogor–Jakarta) yang berinvestasi (emas, saham AS, kripto, reksa "
           "dana lewat Pluang) dan punya bisnis online. Tugasmu BUKAN merangkum berita satu per satu, tetapi MENYIMPULKAN SITUASI SAAT INI dari semua "
           "berita dan angka pasar, menjelaskan alasannya dengan indikator, dan menunjukkan PELUANG yang menguntungkan ekonomi pemilik.\n"
           "ATURAN: pakai HANYA berita dan angka yang diberikan — jangan menambah fakta atau angka. Tiap alasan menunjuk nomor berita sumbernya. "
           "Indikator memakai angka dari DATA PASAR atau yang tertulis di berita. Peluang = hal yang bisa ia pertimbangkan, dengan risikonya; "
           "bukan perintah beli/jual, dan sesuaikan dengan konteks keuangannya (pos gaji, porsi investasi, bisnisnya). Bahasa Indonesia, jelas, "
           "tenang. Kembalikan JSON:\n"
           '{"judul": "satu kalimat inti situasi hari ini",\n'
           ' "situasi": "3–5 kalimat: keadaan ekonomi & dunia sekarang dan arahnya",\n'
           ' "suasana": "positif|campuran|waspada",\n'
           ' "tema": [{"judul": "…", "kesimpulan": "1–2 kalimat", "indikator": [{"nama": "…", "nilai": "angka/arah persis dari data", "arti": "singkat"}], '
           '"alasan": [{"isi": "1 kalimat", "nomor": "EKONOMI 3"}], "dampak": "apa artinya bagi pemilik"}] (2–4 tema),\n'
           ' "peluang": [{"aksi": "yang bisa ia lakukan", "kenapa": "berdasar tema/indikator mana", "kaitan": "' + "|".join(KINDS) + '", '
           '"horizon": "hari ini|minggu ini|bulan ini", "risiko": "…", "yakin": "rendah|sedang|tinggi"}] (2–5),\n'
           ' "waspada": [{"isi": "…", "nomor": "DUNIA 2"}] (0–3),\n'
           ' "ucapan": "3–4 kalimat untuk DIBACAKAN: situasinya, alasan utamanya, satu peluang terpenting"}\n'
           '"nomor" = bagian dan nomor berita persis seperti di daftar.')
    user = ("TENTANG PEMILIK & KEUANGANNYA:\n" + "\n".join(owner_facts[:15] + g["about"]) + (f"\nTopik yang ia ikuti: {', '.join(topics)}" if topics else "")
            + f"\n\nCUACA: {g['weather'] or '-'}\n\nDATA PASAR (terakhir):\n" + ("\n".join(market_lines(g)) or "-")
            + "\n\nBERITA (24 jam terakhir):\n" + "\n".join(news_lines(g)))
    return [{"role": "system", "content": sys}, {"role": "user", "content": user}]


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


def clean_analysis(data: dict, news: dict) -> dict:
    """The brain's analysis kept to its shape, every reason linked to the news it came from ('nomor'). Pure."""
    t = lambda v, n: " ".join(str(v or "").split())[:n]   # noqa: E731
    out = {"judul": t(data.get("judul"), 200), "situasi": t(data.get("situasi"), 1200), "ucapan": t(data.get("ucapan"), 800),
           "suasana": data.get("suasana") if data.get("suasana") in ("positif", "campuran", "waspada") else "campuran"}
    out["tema"] = []
    for x in (data.get("tema") or [])[:4]:
        if not isinstance(x, dict) or not x.get("judul"):
            continue
        out["tema"].append({"judul": t(x["judul"], 120), "kesimpulan": t(x.get("kesimpulan"), 400), "dampak": t(x.get("dampak"), 400),
                            "indikator": [{"nama": t(i.get("nama"), 60), "nilai": t(i.get("nilai"), 60), "arti": t(i.get("arti"), 160)}
                                          for i in (x.get("indikator") or [])[:5] if isinstance(i, dict) and i.get("nama")],
                            "alasan": [r for r in (_reason(r, news) for r in (x.get("alasan") or [])[:5]) if r]})
    out["peluang"] = [{"aksi": t(p.get("aksi"), 200), "kenapa": t(p.get("kenapa"), 300), "risiko": t(p.get("risiko"), 200),
                       "kaitan": p.get("kaitan") if p.get("kaitan") in KINDS else "lainnya",
                       "horizon": p.get("horizon") if p.get("horizon") in ("hari ini", "minggu ini", "bulan ini") else "minggu ini",
                       "yakin": p.get("yakin") if p.get("yakin") in ("rendah", "sedang", "tinggi") else "sedang"}
                      for p in (data.get("peluang") or [])[:5] if isinstance(p, dict) and p.get("aksi")]
    out["waspada"] = [r for r in (_reason(r, news) for r in (data.get("waspada") or [])[:3]) if r]
    return out


async def compose(trigger: str = "schedule") -> dict:
    from . import memory
    s = await appsettings.get("brief")
    g = await gather()
    facts = [m["text"] for m in await memory.list_("personal", limit=30) if not m.get("stale")]
    r = await master.run(master.Job("brief", "compose", "cek berita: simpulkan situasi, indikator, dan peluang untuk pemilik", trigger=trigger,
                                    messages=prompt(g, facts, s.get("topics") or []), json_out=True, heavy=True, no_free=True, max_tokens=3000))
    if r["status"] != "done":
        raise RuntimeError(r.get("error") or "cek berita gagal")
    data = clean_analysis(r["result"] if isinstance(r["result"], dict) else {}, g["news"])
    if not data["situasi"] and not data["tema"]:
        raise RuntimeError("analisisnya kosong — coba lagi")
    data |= {"markets": g["markets"], "weather": g["weather"], "lane": r.get("lane"), "count": sum(len(v) for v in g["news"].values())}
    day = datetime.now(WIB).date()
    srcs = sorted({x["source"] for v in g["news"].values() for x in v})
    await db.pool().execute("""INSERT INTO briefs (day, data, sources, run_id) VALUES ($1, $2, $3, $4)
                               ON CONFLICT (day) DO UPDATE SET data = EXCLUDED.data, sources = EXCLUDED.sources, run_id = EXCLUDED.run_id, created_at = now()""",
                            day, data, srcs, r["run_id"])
    await hub.broadcast({"type": "notify", "title": "Cek berita siap", "text": (data["judul"] or data["situasi"])[:200], "kind": "info", "route": "#/brief"})
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
    n = len(d.get("peluang") or [])
    return [{"id": "brief", "title": "Cek berita", "sub": (d.get("judul") or "situasi hari ini & peluangmu")[:90] + (f" · {n} peluang" if n else ""),
             "route": "#/brief", "icon": "news", "tone": "amber", "score": 55 if m.slot in ("subuh", "pagi") else 25, "cta": "Baca" if m.slot == "pagi" else None}]


@setup_status.check("brief")
async def _ready() -> dict:
    return setup_status.ready()


@router.get(API)
async def api_brief(device: dict = Depends(owner)):
    return {"brief": await today(), "settings": await appsettings.get("brief")}


@router.post(API + "/now")
async def api_brief_now(device: dict = Depends(owner)):
    return {"brief": {"data": await compose("owner"), "day": datetime.now(WIB).date().isoformat()}}
