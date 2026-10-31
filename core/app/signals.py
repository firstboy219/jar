"""More to read for Cek berita (owner 2026-10-31: "Tambah sumber data beritanya untuk mempertajam hasilnya termasuk data dari sentimen sosial
media, google trend, tradingview, dll"). A fixed procedure, no AI — the heavy brain reads all of it together with the news:

  trends     Google Trends Indonesia: what people search more than usual today (its public RSS), with the news behind each
  topics     Google News for what he follows and what he holds (its public RSS search, the last day)
  social     Reddit — Indonesian subreddits and the global investing ones (public RSS; two combined requests a day, stops when Reddit says
             slow down): what people talk about, read as opinion and attention, never as fact
  mood       the Crypto Fear & Greed Index (alternative.me) and the coins most searched on CoinGecko
  agenda     this week's high-impact economic calendar (Forex Factory's public weekly feed): central banks, inflation, jobs
  technical  TradingView has no public API: its "technical rating" method (moving averages + oscillators, averaged, ±0.1 / ±0.5) is
             computed here from a year of daily prices (Yahoo Finance), for the markets and his own holdings

StockTwits and X/Twitter are not read: the first refuses servers behind a bot check, the second has no free API."""

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx

TRENDS_URL = "https://trends.google.com/trending/rss?geo=ID"
HT = "{https://trends.google.com/trending/rss}"
NEWS_URL = "https://news.google.com/rss/search"
REDDIT = [("Reddit Indonesia", "https://www.reddit.com/r/indonesia+finansial+sahamindonesia/hot.rss?limit=25"),
          ("Reddit investor global", "https://www.reddit.com/r/wallstreetbets+stocks+investing+CryptoCurrency/hot.rss?limit=25")]
REDDIT_PAUSE = 3.0   # seconds between the two requests: Reddit asks for a slow pace
FNG_URL = "https://api.alternative.me/fng/?limit=8"
COINS_URL = "https://api.coingecko.com/api/v3/search/trending"
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CAL_COUNTRIES = {"USD", "CNY", "EUR", "JPY", "IDR"}
ATOM = "{http://www.w3.org/2005/Atom}"
FNG_WORDS = {"extreme fear": "sangat takut", "fear": "takut", "neutral": "netral", "greed": "serakah", "extreme greed": "sangat serakah"}


def _text(s: str | None) -> str:
    import html
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# ---------- pure parsers ----------

def parse_trends(xml: str, limit: int = 12) -> list[dict]:
    """Google Trends' daily RSS → [{q, traffic, news}]. Pure."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        q = _text(it.findtext("title"))
        if not q:
            continue
        news = [_text(n.findtext(f"{HT}news_item_title")) for n in it.findall(f"{HT}news_item")][:2]
        out.append({"q": q[:80], "traffic": _text(it.findtext(f"{HT}approx_traffic"))[:20], "news": [n[:160] for n in news if n]})
    return out[:limit]


def parse_atom(xml: str, source: str, now: datetime, max_age_h: int = 30, limit: int = 15) -> list[dict]:
    """A Reddit (Atom) feed → [{title, summary, link, source, at}] of the last day, in its own (hot) order. Pure."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for e in root.iter(f"{ATOM}entry"):
        title = _text(e.findtext(f"{ATOM}title"))
        if not title:
            continue
        raw = e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published") or ""
        try:
            at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            at = None
        if at and now - at > timedelta(hours=max_age_h):
            continue
        link = (e.find(f"{ATOM}link").get("href") if e.find(f"{ATOM}link") is not None else "") or ""
        cat = e.find(f"{ATOM}category")
        sub = (cat.get("label") or cat.get("term") or "") if cat is not None else ""
        out.append({"title": title[:200], "summary": sub[:40], "link": link[:400], "source": source, "at": at.isoformat() if at else None})
    return out[:limit]


def parse_fng(js: dict) -> dict | None:
    """alternative.me → {value, label, week_ago, label_week_ago}. Pure."""
    data = (js or {}).get("data") or []
    if not data:
        return None
    word = lambda d: FNG_WORDS.get(str(d.get("value_classification", "")).lower(), str(d.get("value_classification", "")))   # noqa: E731
    try:
        out = {"value": int(data[0]["value"]), "label": word(data[0])}
        if len(data) > 7:
            out |= {"week_ago": int(data[7]["value"]), "label_week_ago": word(data[7])}
        return out
    except (KeyError, TypeError, ValueError):
        return None


def parse_calendar(rows: list, now: datetime, days: int = 7) -> list[dict]:
    """Forex Factory's week → the high-impact events still ahead (or in the last 12 hours, with their actual number when known). Pure."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or r.get("impact") != "High" or r.get("country") not in CAL_COUNTRIES:
            continue
        try:
            at = datetime.fromisoformat(str(r.get("date")))
        except ValueError:
            continue
        if now - timedelta(hours=12) <= at <= now + timedelta(days=days):
            out.append({"at": at.astimezone(timezone.utc).isoformat(), "country": r["country"], "title": str(r.get("title", ""))[:80],
                        "forecast": str(r.get("forecast") or "")[:20], "previous": str(r.get("previous") or "")[:20], "actual": str(r.get("actual") or "")[:20]})
    return sorted(out, key=lambda x: x["at"])[:12]


def _sma(c: list[float], n: int) -> float | None:
    return sum(c[-n:]) / n if len(c) >= n else None


def _ema_series(c: list[float], n: int) -> list[float]:
    if len(c) < n:
        return []
    k, out = 2 / (n + 1), [sum(c[:n]) / n]
    for x in c[n:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def _rsi(c: list[float], n: int = 14) -> float | None:
    if len(c) <= n:
        return None
    gains = [max(0.0, b - a) for a, b in zip(c, c[1:])]
    losses = [max(0.0, a - b) for a, b in zip(c, c[1:])]
    g, l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for gi, li in zip(gains[n:], losses[n:]):   # Wilder's smoothing
        g, l = (g * (n - 1) + gi) / n, (l * (n - 1) + li) / n
    if l == 0:
        return 50.0 if g == 0 else 100.0   # no move at all is neutral, not overbought
    return round(100 - 100 / (1 + g / l), 1)


def _chg(c: list[float], n: int) -> float | None:
    return round(100 * (c[-1] - c[-1 - n]) / c[-1 - n], 2) if len(c) > n and c[-1 - n] else None


def technicals(closes: list) -> dict | None:
    """TradingView's technical-rating method on daily closes: moving averages (SMA & EMA 10/20/50/100/200: +1 above, −1 below) and
    oscillators (RSI 14, MACD 12/26/9, stochastic 14, momentum 10), each group averaged, then the two averaged; ≥0.5 beli kuat, ≥0.1
    beli, ≤−0.1 jual, ≤−0.5 jual kuat, else netral. Pure."""
    c = [float(x) for x in closes if isinstance(x, (int, float))]
    if len(c) < 30:
        return None
    last = c[-1]
    ma_votes = []
    for n in (10, 20, 50, 100, 200):
        for ma in (_sma(c, n), (_ema_series(c, n) or [None])[-1]):
            if ma:
                ma_votes.append(1 if last > ma else -1 if last < ma else 0)
    rsi = _rsi(c)
    e12, e26 = _ema_series(c, 12), _ema_series(c, 26)
    macd = [a - b for a, b in zip(e12[-len(e26):], e26)]
    signal = _ema_series(macd, 9)
    lo, hi = min(c[-14:]), max(c[-14:])
    stoch = 100 * (last - lo) / (hi - lo) if hi > lo else 50.0
    osc = [1 if rsi < 30 else -1 if rsi > 70 else 0] if rsi is not None else []
    if signal:
        osc.append(1 if macd[-1] > signal[-1] + 1e-9 else -1 if macd[-1] < signal[-1] - 1e-9 else 0)
    osc += [1 if stoch < 20 else -1 if stoch > 80 else 0, 1 if last > c[-11] else -1 if last < c[-11] else 0]
    ma_score, osc_score = sum(ma_votes) / len(ma_votes), sum(osc) / len(osc)
    rating = round((ma_score + osc_score) / 2, 2)
    label = "beli kuat" if rating >= 0.5 else "beli" if rating >= 0.1 else "jual kuat" if rating <= -0.5 else "jual" if rating <= -0.1 else "netral"
    ma50, ma200 = _sma(c, 50), _sma(c, 200)
    return {"rating": rating, "label": label, "ma": round(ma_score, 2), "osc": round(osc_score, 2), "rsi": rsi,
            "above_ma50": last > ma50 if ma50 else None, "above_ma200": last > ma200 if ma200 else None,
            "macd_up": macd[-1] > signal[-1] if signal else None, "change_1d": _chg(c, 1), "change_5d": _chg(c, 5), "change_1m": _chg(c, 21)}


def tech_words(t: dict | None) -> str:
    """One line for the brain. Pure."""
    if not t:
        return ""
    parts = [f"rating teknikal {t['label']} ({t['rating']:+.2f})"]
    if t.get("rsi") is not None:
        parts.append(f"RSI {t['rsi']:.0f}")
    if t.get("above_ma50") is not None:
        parts.append(("di atas" if t["above_ma50"] else "di bawah") + " MA50")
    if t.get("above_ma200") is not None:
        parts.append(("di atas" if t["above_ma200"] else "di bawah") + " MA200")
    if t.get("change_1m") is not None:
        parts.append(f"1 bln {t['change_1m']:+.1f}%")
    return ", ".join(parts)


# ---------- fetching (each one fails alone: a source that is down is just left out) ----------

async def trends(c: httpx.AsyncClient) -> list[dict]:
    try:
        r = await c.get(TRENDS_URL)
        return parse_trends(r.text) if r.status_code == 200 else []
    except httpx.HTTPError:
        return []


async def topics(c: httpx.AsyncClient, queries: list[str], now: datetime, per: int = 4) -> list[dict]:
    from .brief import parse_feed

    async def one(q: str) -> list[dict]:
        try:
            r = await c.get(NEWS_URL, params={"q": f"{q} when:1d", "hl": "id", "gl": "ID", "ceid": "ID:id"})
            return parse_feed(r.text, f"Google News · {q}", now, per) if r.status_code == 200 else []
        except httpx.HTTPError:
            return []
    found = await asyncio.gather(*(one(q) for q in queries[:6]))
    return [x for lst in found for x in lst]


async def social(c: httpx.AsyncClient, now: datetime) -> list[dict]:
    out = []
    for i, (name, url) in enumerate(REDDIT):
        if i:
            await asyncio.sleep(REDDIT_PAUSE)   # one request at a time
        try:
            r = await c.get(url)
        except httpx.HTTPError:
            continue
        if r.status_code == 429:
            break
        if r.status_code == 200:
            out += parse_atom(r.text, name, now)
    return out


async def mood(c: httpx.AsyncClient) -> dict:
    out: dict = {}
    try:
        r = await c.get(FNG_URL)
        if r.status_code == 200 and (f := parse_fng(r.json())):
            out["crypto_fng"] = f
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    try:
        r = await c.get(COINS_URL)
        if r.status_code == 200:
            out["coins"] = [f"{x['item']['name']} ({x['item']['symbol']})" for x in r.json().get("coins", [])[:7] if x.get("item")]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return out


async def agenda(c: httpx.AsyncClient, now: datetime) -> list[dict]:
    try:
        r = await c.get(CALENDAR_URL)
        return parse_calendar(r.json(), now) if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return []


async def history(c: httpx.AsyncClient, sym: str) -> list:
    try:
        r = await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "1y", "interval": "1d"})
        return r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] or []
    except Exception:
        return []


async def holdings() -> list[tuple[str, str]]:
    """(name, ticker) of what he holds, from the last Pluang reading."""
    from . import db, invest
    snap = await db.pool().fetchrow("SELECT data FROM invest_snapshots ORDER BY id DESC LIMIT 1")
    out = []
    for a in ((snap["data"] or {}).get("aset") or []) if snap else []:
        try:
            t = invest.ticker_of(a)
        except (KeyError, TypeError):
            t = None
        if t and t not in {x[1] for x in out}:
            out.append((a["nama"][:40], t))
    return out[:8]
