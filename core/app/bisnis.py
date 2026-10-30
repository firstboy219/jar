"""Bisnis (ADR-087, mockups 33–37): the owner's businesses — Autotoko (his omnichannel SaaS, where he sells as much as he can) and Renature
(inhalers, mouth sprays …) — read from their own APIs, which he enters in the app (Sumber API): base URL, the key (kept encrypted with the
vault key, never shown again), and per number he wants (penjualan, pesanan, dikemas, pencairan, or anything the API gives, e.g. MRR of
the SaaS) where it is in the API's JSON.

  polling     a fixed procedure through the master flow (skill, no AI) every source's interval; each poll keeps a snapshot (how far along
              by this hour) and the day's number per metric (trends); a series endpoint fills months of history at once
  alerts      no AI either: behind the usual for this hour of this weekday, orders not packed in the afternoon, a record day, a source failing
  strategy    a heavy-brain job over 4 months of numbers (weekly, and when he asks)
  peluang     a Hermes job with tools (web research) for new business opportunities (weekly, and when he asks)
  autofill    pasted API documentation → the source form filled in (a light-brain job)

Business numbers are his: every AI job here is no_free (never an endpoint that may log prompts)."""

import asyncio
import ipaddress
import json
import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, appsettings, audit, brief, db, home, hub, master, notes, recap, setup_status, vault
from .appauth import actor, owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/bisnis"

METRICS = {   # the numbers the screens know by name; anything else is shown with the label and unit its endpoint gives
    "penjualan": ("Penjualan", "rp"), "pesanan": ("Pesanan", "n"), "dikemas": ("Sudah dikemas", "n"), "dikirim": ("Dikirim", "n"),
    "pencairan": ("Pencairan", "rp"), "retur": ("Retur", "n"), "pengunjung": ("Pengunjung", "n"), "gmv": ("GMV", "rp"),
    "mrr": ("MRR", "rp"), "pelanggan": ("Pelanggan aktif", "n"), "toko_aktif": ("Toko aktif", "n"), "stok_menipis": ("Stok menipis", "n"),
}
AGGS = ("sum", "count", "value", "avg", "max", "min")
POLL_WINDOW_DAYS = 3        # a series endpoint is re-read for the last days each poll (late orders, cancellations)
BACKFILL_DAYS = 180
FAIL_ALERT = 3


class BisnisError(ValueError):
    pass


# ---------- pure: reading numbers out of an API's JSON ----------

_TOK = re.compile(r"\[\*\]|\[-?\d+\]|[^.\[\]]+")


def walk(doc, path: str) -> list:
    """Every value at a dotted path: 'data.orders[*].total', 'data.items[0].id', '' = the document itself. [*] spreads a list, and a list
    met on the way is spread too ('orders.total' works on a list of orders). Pure."""
    cur = [doc]
    for t in _TOK.findall(path or ""):
        nxt = []
        for c in cur:
            if t == "[*]":
                if isinstance(c, list):
                    nxt.extend(c)
            elif t.startswith("["):
                i = int(t[1:-1])
                if isinstance(c, list) and -len(c) <= i < len(c):
                    nxt.append(c[i])
            else:
                for x in (c if isinstance(c, list) else [c]):
                    if isinstance(x, dict) and t in x:
                        nxt.append(x[t])
        cur = nxt
    return cur


def flat(values: list) -> list:
    out = []
    for v in values:
        out.extend(v) if isinstance(v, list) else out.append(v)
    return out


def first(values: list):
    return values[0] if values else None


def to_number(v) -> float | None:
    """12500, "12.500", "Rp1.234.000", "1,234.56", "4,5" → a number (Indonesian thousands dots understood); None when it is not one. Pure."""
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = re.sub(r"[^\d,.\-]", "", v)
    if not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def keep(item, flt: str) -> bool:
    """'status!=cancelled; paid=true; total>0' — every condition must hold ('=' takes alternatives: 'status=packed,shipped'). Pure."""
    for cond in [c.strip() for c in (flt or "").split(";") if c.strip()]:
        m = re.match(r"^([\w.\[\]*-]+)\s*(!=|>=|<=|=|>|<)\s*(.*)$", cond)
        if not m:
            continue
        key, op, want = m.groups()
        g = first(walk(item, key))
        if op in ("=", "!="):
            opts = {w.strip().lower() for w in want.split(",")}
            hit = (str(g).lower() in opts) if g is not None else bool(opts & {"", "null", "none"})
            if (op == "=") != hit:
                return False
        else:
            a, b = to_number(g), to_number(want)
            if a is None or b is None or not {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]:
                return False
    return True


def aggregate(values: list, how: str) -> float:
    if how == "count":
        return float(len(values))
    nums = [n for n in (to_number(v) for v in values) if n is not None]
    if not nums:
        return 0.0
    return {"sum": sum(nums), "value": nums[0], "avg": mean(nums), "max": max(nums), "min": min(nums)}.get(how, sum(nums))


def day_of(v) -> date | None:
    """An API's date — ISO text (with or without zone, or just the date) or epoch seconds/milliseconds — as the WIB day. Pure."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and re.fullmatch(r"\d{10,13}", v.strip())):
        n = float(v)
        if n > 1e11:
            n /= 1000
        if n < 1e9:
            return None
        return datetime.fromtimestamp(n, timezone.utc).astimezone(WIB).date()
    s = str(v).strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        d = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
        return (d if d.tzinfo else d.replace(tzinfo=WIB)).astimezone(WIB).date()
    except ValueError:
        m = re.match(r"(\d{2})[/-](\d{2})[/-](\d{4})", s)   # 29/10/2026
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def extract(doc, ep: dict, today: date) -> dict:
    """What one endpoint's answer says. 'today' mode: {'value', 'split', 'rows'} (rows that carry a date count only if they are today's);
    'series' mode: {'series': {iso day: value}, 'split_series': {name: {day: value}}, 'rows'}. Pure."""
    rows = [r for r in flat(walk(doc, ep.get("items") or "")) if keep(r, ep.get("filter") or "")]
    vpath = ep.get("value") or ""
    how = ep.get("agg") or ("sum" if vpath else "count")

    def val(r):
        return first(walk(r, vpath)) if vpath else r

    def name(r):
        return str(first(walk(r, ep["split"])) or "lainnya")[:40]
    if ep.get("mode") == "series":
        by, split = defaultdict(list), defaultdict(lambda: defaultdict(list))
        for r in rows:
            d = day_of(first(walk(r, ep.get("date") or "date")))
            if not d:
                continue
            by[d.isoformat()].append(val(r))
            if ep.get("split"):
                split[name(r)][d.isoformat()].append(val(r))
        return {"series": {d: aggregate(v, how) for d, v in sorted(by.items())}, "rows": len(rows),
                "split_series": {k: {d: aggregate(v, how) for d, v in s.items()} for k, s in split.items()}}
    if ep.get("date"):
        rows = [r for r in rows if day_of(first(walk(r, ep["date"]))) in (today, None)]
    out = {"value": aggregate([val(r) for r in rows], how), "rows": len(rows)}
    if ep.get("split"):
        groups = defaultdict(list)
        for r in rows:
            groups[name(r)].append(val(r))
        out["split"] = {k: aggregate(v, how) for k, v in groups.items()}
    return out


def fill(v, now: datetime, window: int = 1):
    """Dates in an endpoint's parameters: {today} {yesterday} {month_start} {from} {to} {from_ts} {to_ts} {from_ms} {to_ms} {now_ts}
    {days_ago:7} — 'from' is the start of the window being read (today for a normal poll, months back for history). Pure."""
    if isinstance(v, dict):
        return {k: fill(x, now, window) for k, x in v.items()}
    if isinstance(v, list):
        return [fill(x, now, window) for x in v]
    if not isinstance(v, str):
        return v
    now = now.astimezone(WIB)
    today = now.date()
    start = datetime(today.year, today.month, today.day, tzinfo=WIB) - timedelta(days=max(1, window) - 1)

    def rep(m):
        k, n = m.group(1), m.group(2)
        vals = {"today": today.isoformat(), "yesterday": (today - timedelta(days=1)).isoformat(), "month_start": today.replace(day=1).isoformat(),
                "from": start.date().isoformat(), "to": today.isoformat(), "from_ts": str(int(start.timestamp())), "to_ts": str(int(now.timestamp())),
                "from_ms": str(int(start.timestamp() * 1000)), "to_ms": str(int(now.timestamp() * 1000)), "now_ts": str(int(now.timestamp())),
                "from_iso": start.isoformat(), "to_iso": now.isoformat()}
        if k == "days_ago":
            return (today - timedelta(days=int(n or 0))).isoformat()
        return vals.get(k, m.group(0))
    return re.sub(r"\{(\w+)(?::(-?\d+))?\}", rep, v)


def label_of(metric: str, ep: dict | None = None) -> tuple[str, str]:
    base, _, channel = metric.partition("@")
    lbl, unit = METRICS.get(base, ((ep or {}).get("label") or base.replace("_", " ").capitalize(), (ep or {}).get("unit") or "n"))
    return (f"{lbl} · {channel}" if channel else lbl), unit


def rp_short(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"Rp{v / 1e9:.1f} M".replace(".", ",")
    if a >= 1e6:
        return f"Rp{v / 1e6:.1f} jt".replace(".", ",").replace(",0 jt", " jt")
    if a >= 1e3:
        return f"Rp{round(v / 1e3)} rb"
    return f"Rp{round(v)}"


def fmt(v: float, unit: str) -> str:
    return rp_short(v) if unit == "rp" else (f"{v:.1f}%".replace(".", ",") if unit == "%" else f"{round(v):,}".replace(",", "."))


def change_pct(cur: float, prev: float) -> float | None:
    return round((cur - prev) / prev * 100, 1) if prev else None


def trend(points: dict[str, float], today: date) -> dict:
    """From a metric's daily numbers: last 30 days vs the 30 before (today, still running, left out), month totals, the average per
    weekday over 8 weeks, a 7-day moving average, and the direction of the last 4 weeks. Pure."""
    by = {date.fromisoformat(k): v for k, v in points.items()}
    s = lambda a, b: sum(by.get(today - timedelta(days=i), 0.0) for i in range(a, b))   # noqa: E731
    last30, prev30 = s(1, 31), s(31, 61)
    months: dict[str, float] = defaultdict(float)
    for d, v in by.items():
        months[d.strftime("%Y-%m")] += v
    wd: dict[int, list] = defaultdict(list)
    for i in range(1, 57):
        d = today - timedelta(days=i)
        wd[d.weekday()].append(by.get(d, 0.0))
    per_wd = {k: round(mean(v), 1) for k, v in wd.items() if v}
    ma = []
    for i in range(89, -1, -1):
        d = today - timedelta(days=i)
        win = [by.get(d - timedelta(days=j), 0.0) for j in range(7)]
        ma.append({"day": d.isoformat(), "value": by.get(d), "ma7": round(mean(win), 1)})
    ma_now, ma_4w = ma[-2]["ma7"] if len(ma) > 1 else 0, ma[-30]["ma7"] if len(ma) >= 30 else 0
    best = max(per_wd, key=per_wd.get) if per_wd and max(per_wd.values()) > 0 else None
    return {"last30": last30, "prev30": prev30, "change30": change_pct(last30, prev30), "months": dict(sorted(months.items())[-7:]),
            "per_weekday": per_wd, "best_weekday": best, "daily": ma, "direction": change_pct(ma_now, ma_4w), "days_with_data": len(by)}


def judge(business: str, now: datetime, today_vals: dict, same_time: dict, max60: float | None, s: dict) -> list[dict]:
    """The alerts a business deserves now (no AI). today_vals = {metric: value so far}; same_time = {metric: [values by this time on the
    same weekday, past weeks]}; max60 = the best day of sales in 60 days. Each alert has a once-a-day key. Pure."""
    day = now.date().isoformat()
    out = []
    if now.hour >= 11:
        for m in ("penjualan", "pesanan"):
            past = [v for v in same_time.get(m, []) if v is not None]
            cur = today_vals.get(m)
            if cur is not None and len(past) >= 2 and mean(past) > 0 and cur < mean(past) * s.get("behind_pct", 60) / 100:
                lbl, unit = label_of(m)
                gap = round((1 - cur / mean(past)) * 100)
                out.append({"key": f"behind:{business}:{m}:{day}", "tone": "amber", "title": f"{business}: {lbl.lower()} tertinggal {gap}%",
                            "text": f"{fmt(cur, unit)} sampai jam {now:%H.%M}, biasanya {fmt(mean(past), unit)} di jam yang sama hari {['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'][now.weekday()]}."})
    after = s.get("unpacked_after", "14:00")
    if f"{now:%H:%M}" >= after and today_vals.get("pesanan") and today_vals.get("dikemas") is not None:
        left = today_vals["pesanan"] - today_vals["dikemas"]
        if left >= max(5, 0.2 * today_vals["pesanan"]):
            out.append({"key": f"unpacked:{business}:{day}", "tone": "amber", "title": f"{business}: {round(left)} pesanan belum dikemas",
                        "text": f"{round(today_vals['dikemas'])} dari {round(today_vals['pesanan'])} pesanan sudah dikemas. Kejar sebelum kurir pick-up."})
    cutoff = s.get("cutoff") or ""
    if re.fullmatch(r"\d{2}:\d{2}", cutoff) and today_vals.get("pesanan") and today_vals.get("dikemas") is not None:
        left = round(today_vals["pesanan"] - today_vals["dikemas"])
        mins = int(cutoff[:2]) * 60 + int(cutoff[3:]) - (now.hour * 60 + now.minute)
        if left > 0 and 0 < mins <= int(s.get("cutoff_warn_min") or 60):
            out.append({"key": f"cutoff:{business}:{day}", "tone": "red", "title": f"{business}: {left} pesanan belum dikemas, batas kirim {cutoff.replace(':', '.')}",
                        "text": f"{mins} menit lagi kurir pick-up. Lewat batas, pesanan dikirim besok dan skor toko bisa turun."})
    if max60 and today_vals.get("penjualan", 0) > max60 and max60 > 0:
        out.append({"key": f"record:{business}:{day}", "tone": "green", "title": f"{business}: rekor penjualan 60 hari!",
                    "text": f"{rp_short(today_vals['penjualan'])} hari ini, tertinggi sejak dua bulan lalu ({rp_short(max60)})."})
    return out


# ---------- sources ----------

def check_url(url: str) -> str:
    """https only, to a public host (not this server's own services, not a private address)."""
    u = urlparse((url or "").strip())
    if u.scheme != "https" or not u.hostname:
        raise BisnisError("alamat API harus https://…")
    h = u.hostname.lower()
    if h == "localhost" or "." not in h or h.endswith((".local", ".internal")):
        raise BisnisError("alamat API harus host publik")
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        ip = None
    if ip and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast):
        raise BisnisError("alamat API harus host publik")
    return url.strip().rstrip("/")


def clean_endpoint(ep: dict) -> dict:
    metric = str(ep.get("metric") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{2,40}", metric):
        raise BisnisError(f"nama angka '{metric}' hanya huruf kecil/angka/_ (mis. penjualan, mrr)")
    path = str(ep.get("path") or "").strip()
    if not path or len(path) > 500:
        raise BisnisError(f"{metric}: path endpoint wajib diisi")
    if path.startswith("http"):
        check_url(path)
    agg = ep.get("agg") or ("sum" if ep.get("value") else "count")
    if agg not in AGGS:
        raise BisnisError(f"{metric}: cara hitung harus salah satu {', '.join(AGGS)}")
    params = ep.get("params") or {}
    if not isinstance(params, dict):
        raise BisnisError(f"{metric}: parameter harus pasangan nama=nilai")
    page = ep.get("page") or None
    if page and not (isinstance(page, dict) and page.get("param")):
        page = None
    return {"metric": metric, "label": str(ep.get("label") or "")[:60], "unit": ep.get("unit") if ep.get("unit") in ("rp", "n", "%") else METRICS.get(metric, ("", "n"))[1],
            "method": "POST" if str(ep.get("method", "GET")).upper() == "POST" else "GET", "path": path,
            "params": {str(k)[:60]: str(v)[:300] for k, v in list(params.items())[:20]}, "body": ep.get("body") if isinstance(ep.get("body"), dict) else None,
            "items": str(ep.get("items") or "")[:200], "value": str(ep.get("value") or "")[:200], "filter": str(ep.get("filter") or "")[:300],
            "agg": agg, "mode": "series" if ep.get("mode") == "series" else "today", "date": str(ep.get("date") or "")[:100],
            "split": str(ep.get("split") or "")[:100],
            "page": {"param": str(page["param"])[:40], "start": int(page.get("start", 1)), "max": max(1, min(int(page.get("max", 5)), 50)),
                     "size_param": str(page.get("size_param") or "")[:40], "size": max(1, min(int(page.get("size", 100)), 1000))} if page else None}


def public(row) -> dict:
    """A source as the screens see it: never the key — only that one is kept, and its last 4 characters."""
    r = dict(row)
    secret = r.pop("secret", None)
    hint = ""
    if secret:
        try:
            hint = "••••" + vault.decrypt(bytes(secret))[-4:]
        except Exception:
            hint = "••••"
    r["key_hint"] = hint
    return r


async def sources(business: str | None = None) -> list[dict]:
    rows = await db.pool().fetch("SELECT * FROM biz_sources " + ("WHERE business = $1 " if business else "") + "ORDER BY business, id", *([business] if business else []))
    return [public(r) for r in rows]


async def save_source(src_id: int | None, data: dict, who: str) -> dict:
    business, name = str(data.get("business") or "").strip()[:60], str(data.get("name") or "").strip()[:80]
    if not business or not name:
        raise BisnisError("isi nama bisnis dan nama sumber")
    base = check_url(data.get("base_url") or "")
    auth = data.get("auth") or {"type": "none"}
    if auth.get("type") not in ("none", "bearer", "header", "query", "basic"):
        raise BisnisError("jenis autentikasi tidak dikenal")
    if auth["type"] in ("header", "query") and not re.fullmatch(r"[\w-]{1,60}", str(auth.get("name") or "")):
        raise BisnisError("isi nama header/parameter untuk kunci API (mis. X-API-Key)")
    auth = {"type": auth["type"], "name": str(auth.get("name") or "")[:60]}
    eps = [clean_endpoint(e) for e in (data.get("endpoints") or [])][:30]
    if not eps:
        raise BisnisError("tambahkan minimal satu angka (endpoint)")
    headers = {str(k)[:60]: str(v)[:300] for k, v in list((data.get("headers") or {}).items())[:10]}
    poll = max(5, min(int(data.get("poll_min") or 15), 1440))
    key = data.get("key")
    secret = vault.encrypt(str(key)) if key else None
    if auth["type"] != "none" and not key and not src_id:
        raise BisnisError("isi kunci API / token")
    if src_id:
        row = await db.pool().fetchrow(
            """UPDATE biz_sources SET business = $2, name = $3, base_url = $4, auth = $5, headers = $6, endpoints = $7, poll_min = $8,
                 secret = coalesce($9, secret), status = $10, fails = 0, last_error = NULL WHERE id = $1 RETURNING *""",
            src_id, business, name, base, auth, headers, eps, poll, secret, "paused" if data.get("paused") else "active")
        if not row:
            raise BisnisError("sumber tidak ada")
    else:
        row = await db.pool().fetchrow(
            """INSERT INTO biz_sources (business, name, base_url, auth, headers, endpoints, poll_min, secret) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
            business, name, base, auth, headers, eps, poll, secret)
    await audit.record(who, "bisnis.source_saved", f"biz_source:{row['id']}", business=business, endpoints=len(eps))
    return public(row)


async def delete_source(src_id: int, who: str) -> None:
    await db.pool().execute("DELETE FROM biz_sources WHERE id = $1", src_id)
    await audit.record(who, "bisnis.source_deleted", f"biz_source:{src_id}")


# ---------- reading an API ----------

def _client(timeout: float = 20) -> httpx.AsyncClient:   # seam for tests
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False)


async def _get(src: dict, ep: dict, now: datetime, window: int, page_no: int | None = None):
    url = ep["path"] if ep["path"].startswith("http") else f"{src['base_url']}/{ep['path'].lstrip('/')}"
    params = fill(ep.get("params") or {}, now, window)
    headers = {"Accept": "application/json", "User-Agent": "JARVIS/1.0", **(src.get("headers") or {})}
    auth = src.get("auth") or {"type": "none"}
    key = vault.decrypt(bytes(src["secret"])) if src.get("secret") else ""
    basic = None
    if auth["type"] == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    elif auth["type"] == "header":
        headers[auth["name"]] = key
    elif auth["type"] == "query":
        params[auth["name"]] = key
    elif auth["type"] == "basic":
        u, _, p = key.partition(":")
        basic = (u, p)
    if page_no is not None and ep.get("page"):
        params[ep["page"]["param"]] = str(page_no)
        if ep["page"].get("size_param"):
            params[ep["page"]["size_param"]] = str(ep["page"]["size"])
    async with _client() as h:
        r = await h.request(ep.get("method", "GET"), url, params=params, headers=headers, auth=basic,
                            json=fill(ep["body"], now, window) if ep.get("body") and ep.get("method") == "POST" else None)
    if r.status_code >= 400:
        raise BisnisError(f"{ep['metric']}: HTTP {r.status_code} {r.text[:160]}")
    try:
        return r.json()
    except ValueError:
        raise BisnisError(f"{ep['metric']}: jawaban API bukan JSON")


async def read_endpoint(src: dict, ep: dict, now: datetime, window: int = 1) -> tuple[dict, object]:
    """(what it says, the raw answer of the first page). Pages are read while they are full, up to the endpoint's limit."""
    if not ep.get("page"):
        doc = await _get(src, ep, now, window)
        return extract(doc, ep, now.astimezone(WIB).date()), doc
    rows, first_doc, pg = [], None, ep["page"]
    for n in range(pg["start"], pg["start"] + pg["max"]):
        doc = await _get(src, ep, now, window, n)
        first_doc = first_doc if first_doc is not None else doc
        got = flat(walk(doc, ep.get("items") or ""))
        rows.extend(got)
        if len(got) < pg["size"]:
            break
    return extract({"__all": rows}, {**ep, "items": "__all"}, now.astimezone(WIB).date()), first_doc


async def _store_day(src: dict, metric: str, day: str, value: float, unit: str) -> None:
    await db.pool().execute(
        """INSERT INTO biz_daily (business, metric, day, value, unit, source_id) VALUES ($1, $2, $3, $4, $5, $6)
           ON CONFLICT (business, metric, day) DO UPDATE SET value = EXCLUDED.value, unit = EXCLUDED.unit, source_id = EXCLUDED.source_id, updated_at = now()""",
        src["business"], metric, date.fromisoformat(day), value, unit, src["id"])


async def poll_source(src: dict, window: int = POLL_WINDOW_DAYS, now: datetime | None = None) -> dict:
    """One source, every endpoint: today's numbers (a snapshot + the day's number), a series' days. Errors per endpoint are kept."""
    now = (now or datetime.now(WIB)).astimezone(WIB)
    today = now.date().isoformat()
    got, errors = {}, []
    for ep in src["endpoints"]:
        try:
            out, _ = await read_endpoint(src, ep, now, window if ep.get("mode") == "series" else 1)
        except (BisnisError, httpx.HTTPError, vault.VaultError) as e:
            errors.append(str(e)[:200])
            continue
        if ep.get("mode") == "series":
            for d, v in out["series"].items():
                await _store_day(src, ep["metric"], d, v, ep["unit"])
            for ch, series in (out.get("split_series") or {}).items():
                for d, v in series.items():
                    await _store_day(src, f"{ep['metric']}@{ch}", d, v, ep["unit"])
            value = out["series"].get(today)
        else:
            value = out["value"]
            await _store_day(src, ep["metric"], today, value, ep["unit"])
            for ch, v in (out.get("split") or {}).items():
                await _store_day(src, f"{ep['metric']}@{ch}", today, v, ep["unit"])
        if value is not None:
            await db.pool().execute("INSERT INTO biz_snapshots (source_id, business, metric, value, at) VALUES ($1, $2, $3, $4, $5)",
                                    src["id"], src["business"], ep["metric"], value, now)
            got[ep["metric"]] = value
    ok = bool(got) or not src["endpoints"]
    await db.pool().execute(
        "UPDATE biz_sources SET last_poll = now(), last_ok = CASE WHEN $2 THEN now() ELSE last_ok END, last_error = $3, fails = CASE WHEN $2 THEN 0 ELSE fails + 1 END WHERE id = $1",
        src["id"], ok and not errors, "; ".join(errors)[:1000] or None)
    if not got and errors:
        raise BisnisError("; ".join(errors)[:300])
    return {"business": src["business"], "values": got, "errors": errors}


async def test_source(data: dict, src_id: int | None = None) -> list[dict]:
    """Read every endpoint once without keeping anything: the number it gives and a piece of the raw answer (for the form)."""
    src = dict(await db.pool().fetchrow("SELECT * FROM biz_sources WHERE id = $1", src_id)) if src_id else {}
    if data:
        src.update({"business": data.get("business") or src.get("business") or "-", "base_url": check_url(data.get("base_url") or src.get("base_url") or ""),
                    "auth": data.get("auth") or src.get("auth") or {"type": "none"}, "headers": data.get("headers") or src.get("headers") or {},
                    "endpoints": [clean_endpoint(e) for e in data.get("endpoints") or []] or src.get("endpoints") or []})
        if data.get("key"):
            src["secret"] = vault.encrypt(str(data["key"]))
    now = datetime.now(WIB)
    out = []
    for ep in src.get("endpoints") or []:
        try:
            res, raw = await read_endpoint(src, ep, now, 30 if ep.get("mode") == "series" else 1)
            out.append({"metric": ep["metric"], "ok": True, "value": res.get("value"), "days": len(res.get("series") or {}), "rows": res.get("rows"),
                        "split": res.get("split") or {}, "sample": json.dumps(raw, ensure_ascii=False)[:1500]})
        except (BisnisError, httpx.HTTPError, vault.VaultError) as e:
            out.append({"metric": ep["metric"], "ok": False, "error": str(e)[:300]})
    return out


# ---------- the clock ----------

async def due_sources(now: datetime) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT * FROM biz_sources WHERE status = 'active' AND (last_poll IS NULL OR last_poll < $1::timestamptz - make_interval(mins => poll_min)) ORDER BY id", now)
    return [dict(r) for r in rows]


async def sync_one(src: dict, trigger: str = "schedule", window: int = POLL_WINDOW_DAYS) -> dict:
    """One poll of one source through the master flow (a fixed procedure: no AI), then the alerts for its business."""
    async def run():
        try:
            r = await poll_source(src, window)
        except BisnisError:
            await alerts(src["business"])   # a source failing again and again is itself worth telling
            raise
        r["alerts"] = await alerts(src["business"])
        return r
    action = "riwayat" if window > POLL_WINDOW_DAYS else "sinkron"
    r = await master.run(master.Job("bisnis", action, f"ambil angka {src['business']} dari {src['name']}", trigger=trigger, skill=run))
    if r["status"] == "done":
        await hub.broadcast({"type": "bisnis", "business": src["business"]})
        if window > POLL_WINDOW_DAYS:
            await db.pool().execute("UPDATE biz_sources SET backfilled = now() WHERE id = $1", src["id"])
    return r


@appclock.every(60, "bisnis.poll")
async def tick() -> list[int]:
    done = []
    for src in await due_sources(datetime.now(WIB)):
        needs_history = not src["backfilled"] and any(e.get("mode") == "series" for e in src["endpoints"])
        await sync_one(src, "schedule", BACKFILL_DAYS if needs_history else POLL_WINDOW_DAYS)
        done.append(src["id"])
    return done


# ---------- numbers for the screens ----------

async def businesses() -> list[str]:
    s = await appsettings.get("bisnis")
    have = [r["business"] for r in await db.pool().fetch("SELECT DISTINCT business FROM biz_sources")]
    return [b for b in s["businesses"] if b in have] + sorted(b for b in have if b not in s["businesses"])


async def _same_time(business: str, metric: str, now: datetime, weeks: int = 4) -> list[float | None]:
    out = []
    for w in range(1, weeks + 1):
        t = now - timedelta(days=7 * w)
        out.append(await db.pool().fetchval(
            "SELECT value::float FROM biz_snapshots WHERE business = $1 AND metric = $2 AND at <= $3 AND at > $3::timestamptz - interval '3 hours' ORDER BY at DESC LIMIT 1",
            business, metric, t))
    return out


async def alerts(business: str, now: datetime | None = None) -> list[dict]:
    """Judge the business now and keep (and tell) each alert once a day."""
    now = (now or datetime.now(WIB)).astimezone(WIB)
    s = await appsettings.get("bisnis")
    if not s["alerts"]:
        return []
    today_vals = {r["metric"]: float(r["value"]) for r in await db.pool().fetch(
        "SELECT metric, value FROM biz_daily WHERE business = $1 AND day = $2 AND position('@' in metric) = 0", business, now.date())}
    same = {m: await _same_time(business, m, now) for m in ("penjualan", "pesanan") if m in today_vals}
    max60 = await db.pool().fetchval("SELECT max(value)::float FROM biz_daily WHERE business = $1 AND metric = 'penjualan' AND day >= $2 AND day < $3",
                                     business, now.date() - timedelta(days=60), now.date())
    found = judge(business, now, today_vals, same, max60 if (await _days(business, "penjualan")) >= 14 else None, s)
    fails = await db.pool().fetch("SELECT id, name, last_error FROM biz_sources WHERE business = $1 AND fails >= $2", business, FAIL_ALERT)
    for f in fails:
        found.append({"key": f"fail:{f['id']}:{now.date()}", "tone": "red", "title": f"Sumber {f['name']} gagal dibaca", "text": (f["last_error"] or "")[:200]})
    new = []
    for a in found:
        got = await db.pool().fetchval("INSERT INTO biz_insights (kind, business, key, data) VALUES ('alert', $1, $2, $3) ON CONFLICT (key) WHERE key <> '' DO NOTHING RETURNING id",
                                       business, a["key"], a)
        if got:
            new.append(a)
            await hub.broadcast({"type": "notify", "title": a["title"], "text": a["text"], "kind": "info", "route": "#/bisnis"})
    return new


async def _days(business: str, metric: str) -> int:
    return await db.pool().fetchval("SELECT count(*) FROM biz_daily WHERE business = $1 AND metric = $2", business, metric) or 0


async def today_view(now: datetime | None = None) -> dict:
    now = (now or datetime.now(WIB)).astimezone(WIB)
    d = now.date()
    out = []
    for b in await businesses():
        rows = await db.pool().fetch("SELECT metric, value::float AS value, unit FROM biz_daily WHERE business = $1 AND day = $2", b, d)
        y = {r["metric"]: r["value"] for r in await db.pool().fetch("SELECT metric, value::float AS value FROM biz_daily WHERE business = $1 AND day = $2", b, d - timedelta(days=1))}
        usual = {r["metric"]: r["v"] for r in await db.pool().fetch(
            "SELECT metric, avg(value)::float AS v FROM biz_daily WHERE business = $1 AND day = ANY($2::date[]) GROUP BY metric", b, [d - timedelta(days=7 * w) for w in range(1, 5)])}
        eps = {e["metric"]: e for s in await db.pool().fetch("SELECT endpoints FROM biz_sources WHERE business = $1", b) for e in s["endpoints"]}
        kpis, channels = [], []
        for r in rows:
            base, _, ch = r["metric"].partition("@")
            if ch:
                if base == "penjualan" or (base == "pesanan" and not any(x["metric"].startswith("penjualan@") for x in rows)):
                    channels.append({"name": ch, "value": r["value"], "metric": base})
                continue
            lbl, unit = label_of(r["metric"], eps.get(r["metric"]))
            by_now = None
            if r["metric"] in ("penjualan", "pesanan"):
                past = [v for v in await _same_time(b, r["metric"], now) if v is not None]
                by_now = round(mean(past), 1) if len(past) >= 2 else None
            kpis.append({"metric": r["metric"], "label": lbl, "unit": r["unit"] or unit, "value": r["value"], "yesterday": y.get(r["metric"]),
                         "usual": usual.get(r["metric"]), "by_now": by_now, "vs_usual": change_pct(r["value"], by_now or 0)})
        order = list(METRICS)
        kpis.sort(key=lambda k: order.index(k["metric"]) if k["metric"] in order else 99)
        vals = {k["metric"]: k["value"] for k in kpis}
        packed = {"done": vals["dikemas"], "total": vals["pesanan"], "pct": round(vals["dikemas"] / vals["pesanan"] * 100) if vals["pesanan"] else 0} \
            if "dikemas" in vals and "pesanan" in vals else None
        al = await db.pool().fetch("SELECT id, data, created_at FROM biz_insights WHERE kind = 'alert' AND business = $1 AND created_at >= $2 ORDER BY id DESC",
                                   b, datetime(d.year, d.month, d.day, tzinfo=WIB))
        src = await db.pool().fetch("SELECT id, name, last_ok, last_error, fails, status FROM biz_sources WHERE business = $1", b)
        out.append({"name": b, "kpis": kpis, "channels": sorted(channels, key=lambda c: -c["value"])[:8], "packed": packed,
                    "alerts": [{"id": a["id"], **a["data"]} for a in al], "synced_at": max((s["last_ok"] for s in src if s["last_ok"]), default=None),
                    "sources": [dict(s) for s in src]})
    return {"businesses": out, "now": now.isoformat()}


async def history(business: str, metric: str, days: int = 120) -> dict:
    d = datetime.now(WIB).date()
    rows = await db.pool().fetch("SELECT day, value::float AS value, unit FROM biz_daily WHERE business = $1 AND metric = $2 AND day > $3 ORDER BY day",
                                 business, metric, d - timedelta(days=max(7, min(days, 400))))
    pts = {r["day"].isoformat(): r["value"] for r in rows}
    unit = rows[0]["unit"] if rows else label_of(metric)[1]
    metrics = [r["metric"] for r in await db.pool().fetch("SELECT DISTINCT metric FROM biz_daily WHERE business = $1 ORDER BY metric", business)]
    return {"business": business, "metric": metric, "label": label_of(metric)[0], "unit": unit, "trend": trend(pts, d), "metrics": metrics,
            "channels": [m for m in metrics if m.startswith(metric + "@")]}


# ---------- strategy (heavy brain) ----------

async def strategy(business: str, trigger: str = "owner") -> dict:
    d = datetime.now(WIB).date()
    metrics = [r["metric"] for r in await db.pool().fetch("SELECT DISTINCT metric FROM biz_daily WHERE business = $1", business)]
    if not metrics:
        raise BisnisError(f"belum ada angka {business} — tambahkan sumber API dulu")
    facts = []
    for m in metrics:
        h = await history(business, m, 130)
        t = h["trend"]
        lbl, unit = label_of(m)
        months = ", ".join(f"{k}: {fmt(v, unit)}" for k, v in t["months"].items())
        wd = ", ".join(f"{['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'][k]} {fmt(v, unit)}" for k, v in sorted(t["per_weekday"].items()))
        facts.append(f"- {lbl} ({m}): 30 hari terakhir {fmt(t['last30'], unit)} vs 30 hari sebelumnya {fmt(t['prev30'], unit)} ({t['change30']}%); "
                     f"arah 4 minggu {t['direction']}%; per bulan: {months}; rata-rata per hari: {wd}")
    prev = await db.pool().fetchval("SELECT data FROM biz_insights WHERE kind = 'strategy' AND business = $1 ORDER BY id DESC LIMIT 1", business)
    alerts_30 = [r["data"]["title"] for r in await db.pool().fetch(
        "SELECT data FROM biz_insights WHERE kind = 'alert' AND business = $1 AND created_at > now() - interval '30 days' ORDER BY id DESC LIMIT 10", business)]
    s = await appsettings.get("bisnis")
    msgs = [{"role": "system", "content": (
        "Kamu konsultan pertumbuhan e-commerce & SaaS di Indonesia untuk pemilik JARVIS. Analisa angka bisnisnya dan susun strategi yang KONKRET "
        "(bisa dikerjakan minggu ini, pakai kanal yang ada: marketplace Shopee/Tokopedia/TikTok Shop, iklan, bundling, live, affiliate, CRM/WA, harga). "
        "Pakai HANYA angka yang diberikan; bila data kurang, katakan. JSON: {\"ringkasan\": \"2–3 kalimat kondisi\", \"temuan\": [\"…\"], "
        "\"strategi\": [{\"judul\": \"…\", \"kenapa\": \"berdasar angka apa\", \"langkah\": [\"…\"], \"dampak\": \"perkiraan\", \"usaha\": \"rendah|sedang|tinggi\", "
        "\"ukur\": \"metrik & target\"}] (3–5, urut dampak), \"minggu_ini\": [\"3 aksi paling penting minggu ini\"], \"risiko\": [\"…\"]}")},
        {"role": "user", "content": (f"Bisnis: {business}. Tentang pemilik & bisnisnya: {s['profile']}\nHari ini {d.isoformat()}.\n\nANGKA:\n" + "\n".join(facts)
                                     + (f"\n\nPeringatan 30 hari: {alerts_30}" if alerts_30 else "")
                                     + (f"\n\nStrategi sebelumnya (tindak lanjuti): {json.dumps(prev, ensure_ascii=False)[:2000]}" if prev else ""))}]
    r = await master.run(master.Job("bisnis", "strategi", f"susun strategi penjualan {business}", trigger=trigger, messages=msgs, heavy=True,
                                    json_out=True, no_free=True, max_tokens=2500))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise BisnisError(r.get("error") or "strategi gagal disusun")
    data = {**r["result"], "lane": r.get("lane"), "model": r.get("model")}
    iid = await db.pool().fetchval("INSERT INTO biz_insights (kind, business, data, run_id) VALUES ('strategy', $1, $2, $3) RETURNING id", business, data, r["run_id"])
    if trigger != "owner":
        await hub.broadcast({"type": "notify", "title": f"Strategi {business} minggu ini siap", "text": (data.get("ringkasan") or "")[:200], "kind": "info", "route": "#/tren"})
    return {"id": iid, "business": business, **data}


async def latest_strategy(business: str) -> dict | None:
    r = await db.pool().fetchrow("SELECT id, data, created_at FROM biz_insights WHERE kind = 'strategy' AND business = $1 ORDER BY id DESC LIMIT 1", business)
    return {"id": r["id"], "created_at": r["created_at"], **r["data"]} if r else None


def _due_weekly(day_key: str, at_key: str):
    async def at() -> str:
        s = await appsettings.get("bisnis")
        return s[at_key] if datetime.now(WIB).weekday() == s[day_key] else ""
    return at


@appclock.daily(_due_weekly("strategy_day", "strategy_at"), "bisnis.strategy")
async def _weekly_strategy() -> None:
    for b in await businesses():
        try:
            await strategy(b, "schedule")
        except BisnisError as e:
            log.info("weekly strategy %s: %s", b, e)


# ---------- opportunities (Hermes with tools) ----------

OPP_FORMAT = ("{\"peluang\": [{\"judul\": \"…\", \"ringkasan\": \"2 kalimat\", \"kenapa_sekarang\": \"tren/data pendukung\", \"modal\": \"perkiraan Rp\", "
              "\"potensi\": \"perkiraan omzet/bulan\", \"cocok\": \"kenapa cocok dengan bisnis yang ada (Autotoko/Renature/kanal)\", \"skor\": 1-10, "
              "\"langkah_pertama\": \"yang bisa dicoba minggu ini\", \"sumber\": [\"url\"]}]}")


async def find_opportunities(trigger: str = "owner") -> dict:
    s = await appsettings.get("bisnis")
    have = await businesses()
    top = []
    for b in have:
        t = (await history(b, "penjualan", 60))["trend"]
        top.append(f"{b}: penjualan 30 hari {rp_short(t['last30'])} ({t['change30']}%)")
    instruction = (
        "Cari 4–6 PELUANG BISNIS ONLINE baru yang realistis untuk pemilik di Indonesia, pakai browser: tren pencarian (Google Trends), produk yang naik "
        "di Shopee/Tokopedia/TikTok Shop, berita industri, celah pasar. Utamakan yang bisa memanfaatkan aset yang sudah ada: SaaS omnichannel "
        "Autotoko (penjual marketplace), brand Renature (inhaler, mouth spray, produk kesehatan herbal), dan kemampuan jualan online. "
        f"Tentang pemilik: {s['profile']}. Angka bisnis sekarang: {'; '.join(top) or 'belum ada'}. "
        f"Hindari yang sudah pernah diusulkan: {', '.join(await _past_titles()) or '-'}. "
        f"Pemilik bilang BUKAN untuknya (pelajari seleranya, jangan usulkan yang mirip): {'; '.join(await _not_for_me()) or '-'}. "
        f"Jawab HANYA JSON: {OPP_FORMAT}")
    r = await master.run(master.Job("bisnis", "peluang", "riset peluang bisnis online baru", trigger=trigger, tools=True, heavy=True, no_free=True,
                                    instruction=instruction, title="Cari peluang bisnis baru", on_done="bisnis:_opportunities_done"))
    if r["status"] == "failed":
        raise BisnisError(r.get("error") or "riset peluang gagal dimulai")
    return r


async def _past_titles() -> list[str]:
    rows = await db.pool().fetch("SELECT data FROM biz_insights WHERE kind = 'opportunity' AND created_at > now() - interval '90 days'")
    return [p.get("judul", "") for r in rows for p in (r["data"].get("peluang") or [])][:30]


async def _not_for_me() -> list[str]:
    """What he said is not for him (and why), so the research learns his taste."""
    rows = await db.pool().fetch("SELECT data FROM biz_insights WHERE kind = 'opportunity' AND created_at > now() - interval '365 days' ORDER BY id DESC")
    return [f"{p['judul']}" + (f" ({p['alasan_tolak']})" if p.get("alasan_tolak") else "") for r in rows for p in (r["data"].get("peluang") or []) if p.get("dismissed")][:20]


def clean_opportunities(data) -> list[dict]:
    out = []
    for p in (data or {}).get("peluang") or []:
        if not isinstance(p, dict) or not p.get("judul"):
            continue
        try:
            skor = max(1, min(int(p.get("skor") or 5), 10))
        except (TypeError, ValueError):
            skor = 5
        out.append({"judul": str(p["judul"])[:120], "ringkasan": str(p.get("ringkasan") or "")[:500], "kenapa_sekarang": str(p.get("kenapa_sekarang") or "")[:400],
                    "modal": str(p.get("modal") or "")[:80], "potensi": str(p.get("potensi") or "")[:80], "cocok": str(p.get("cocok") or "")[:300], "skor": skor,
                    "langkah_pertama": str(p.get("langkah_pertama") or "")[:300],
                    "sumber": [str(u)[:300] for u in (p.get("sumber") or []) if str(u).startswith("http")][:4]})
    return sorted(out, key=lambda x: -x["skor"])[:8]


async def _opportunities_done(run_id: int, result: dict) -> None:
    """Hermes' research came back: its JSON (or, when it wrote prose, the light brain turns that into the list)."""
    if not result.get("ok"):
        await hub.broadcast({"type": "notify", "title": "Riset peluang gagal", "text": "Coba lagi dari layar Peluang.", "kind": "info", "route": "#/peluang"})
        return
    text = result.get("text") or ""
    try:
        items = clean_opportunities(master.parse_json(text))
    except ValueError:
        items = []
    if not items and text.strip():
        r = await master.run(master.Job("bisnis", "peluang-rapikan", "rapikan hasil riset peluang jadi daftar", trigger="event", json_out=True, no_free=True,
                                        messages=[{"role": "system", "content": f"Ubah hasil riset ini jadi JSON {OPP_FORMAT}. Jangan menambah peluang yang tidak ada."},
                                                  {"role": "user", "content": text[:12000]}]))
        items = clean_opportunities(r.get("result") if r["status"] == "done" else {})
    if not items:
        return
    await db.pool().execute("INSERT INTO biz_insights (kind, data, run_id) VALUES ('opportunity', $1, $2)", {"peluang": items, "task_id": result.get("task_id")}, run_id)
    await hub.broadcast({"type": "notify", "title": f"{len(items)} peluang bisnis baru", "text": items[0]["judul"], "kind": "info", "route": "#/peluang"})


@appclock.daily(_due_weekly("opportunity_day", "opportunity_at"), "bisnis.opportunities")
async def _weekly_opportunities() -> None:
    await find_opportunities("schedule")


async def opportunities() -> dict:
    rows = await db.pool().fetch("SELECT id, data, status, created_at FROM biz_insights WHERE kind = 'opportunity' ORDER BY id DESC LIMIT 6")
    running = await db.pool().fetchval("""SELECT task_id FROM flow_runs WHERE feature = 'bisnis' AND action = 'peluang' AND status = 'waiting'
                                          AND started_at > now() - interval '3 hours' ORDER BY id DESC LIMIT 1""")
    return {"batches": [{"id": r["id"], "created_at": r["created_at"], "status": r["status"], **r["data"]} for r in rows], "running_task": running}


async def save_opportunity(batch_id: int, index: int, who: str) -> dict:
    data = await db.pool().fetchval("SELECT data FROM biz_insights WHERE id = $1 AND kind = 'opportunity'", batch_id)
    if not data or not 0 <= index < len(data.get("peluang") or []):
        raise BisnisError("peluang tidak ada")
    p = data["peluang"][index]
    t = await notes.add_task(f"Coba peluang: {p['judul']} — {p['langkah_pertama']}"[:300], None, None, who)
    data["peluang"][index]["saved"] = True
    await db.pool().execute("UPDATE biz_insights SET data = $2, status = 'saved' WHERE id = $1", batch_id, data)
    return t


async def dismiss_opportunity(batch_id: int, index: int, reason: str, who: str) -> None:
    data = await db.pool().fetchval("SELECT data FROM biz_insights WHERE id = $1 AND kind = 'opportunity'", batch_id)
    if not data or not 0 <= index < len(data.get("peluang") or []):
        raise BisnisError("peluang tidak ada")
    data["peluang"][index].update({"dismissed": True, "alasan_tolak": reason.strip()[:200]})
    await db.pool().execute("UPDATE biz_insights SET data = $2 WHERE id = $1", batch_id, data)
    await audit.record(who, "bisnis.opportunity_dismissed", f"biz_insight:{batch_id}", index=index)


DEEP_FORMAT = ("{\"pasar\": \"ukuran & tren dengan angka\", \"pesaing\": [{\"nama\": \"…\", \"harga\": \"…\", \"catatan\": \"…\"}], "
               "\"pemasok\": [\"…\"], \"hitungan\": {\"modal_awal\": \"Rp…\", \"hpp_per_unit\": \"Rp…\", \"harga_jual\": \"Rp…\", \"margin\": \"…%\", "
               "\"balik_modal\": \"…\"}, \"risiko\": [\"…\"], \"rencana_30_hari\": [\"minggu 1: …\"], \"kesimpulan\": \"layak/tidak dan kenapa\", \"sumber\": [\"url\"]}")


async def deep_research(batch_id: int, index: int, trigger: str = "owner") -> dict:
    """One opportunity researched deeper by Hermes with the browser: market, competitors and their prices, suppliers, the numbers, a 30-day plan."""
    data = await db.pool().fetchval("SELECT data FROM biz_insights WHERE id = $1 AND kind = 'opportunity'", batch_id)
    if not data or not 0 <= index < len(data.get("peluang") or []):
        raise BisnisError("peluang tidak ada")
    p = data["peluang"][index]
    s = await appsettings.get("bisnis")
    instruction = (f"Riset MENDALAM satu peluang bisnis untuk pemilik di Indonesia, pakai browser (marketplace, Google Trends, situs pemasok, berita): "
                   f"\"{p['judul']}\" — {p['ringkasan']} Cek harga pesaing nyata di Shopee/Tokopedia/TikTok Shop, pemasok/maklon dan harganya, "
                   f"hitung HPP, margin, dan balik modal dengan angka, lalu rencana 30 hari. Tentang pemilik: {s['profile']}. "
                   f"Jujur bila tidak layak. Jawab HANYA JSON: {DEEP_FORMAT}")
    r = await master.run(master.Job("bisnis", "riset-dalam", f"riset mendalam: {p['judul']}", trigger=trigger, tools=True, heavy=True, no_free=True,
                                    instruction=instruction, title=f"Riset: {p['judul']}"[:80], on_done="bisnis:_deep_done", data={"batch": batch_id, "index": index}))
    if r["status"] == "failed":
        raise BisnisError(r.get("error") or "riset tidak bisa dimulai")
    data["peluang"][index]["riset"] = {"status": "running", "task_id": r.get("task_id")}
    await db.pool().execute("UPDATE biz_insights SET data = $2 WHERE id = $1", batch_id, data)
    return {"status": r["status"], "task_id": r.get("task_id"), "lane": r.get("lane")}


async def _deep_done(run_id: int, result: dict) -> None:
    d = result.get("data") or {}
    data = await db.pool().fetchval("SELECT data FROM biz_insights WHERE id = $1 AND kind = 'opportunity'", d.get("batch"))
    if not data or not 0 <= int(d.get("index", -1)) < len(data.get("peluang") or []):
        return
    p = data["peluang"][int(d["index"])]
    try:
        got = master.parse_json(result.get("text") or "") if result.get("ok") else None
    except ValueError:
        got = None
    p["riset"] = {"status": "done", **got} if isinstance(got, dict) else {"status": "done" if result.get("ok") else "failed", "catatan": (result.get("text") or "")[:3000]}
    await db.pool().execute("UPDATE biz_insights SET data = $2 WHERE id = $1", d["batch"], data)
    await hub.broadcast({"type": "notify", "title": f"Riset selesai: {p['judul']}"[:80], "text": str(p["riset"].get("kesimpulan") or "")[:160], "kind": "info", "route": "#/peluang"})


async def strategy_tasks(business: str, who: str) -> list[dict]:
    """This week's strategy steps → tasks in Catatan (each opens Tren); steps already there are not added twice."""
    st = await latest_strategy(business)
    if not st or not st.get("minggu_ini"):
        raise BisnisError("belum ada strategi minggu ini")
    have = {t["text"] for t in await notes.tasks()}
    out = []
    for step in st["minggu_ini"][:8]:
        text = f"{business}: {step}"[:300]
        if text not in have:
            out.append(await notes.add_task(text, None, None, who, link=f"#/tren?b={quote(business)}"))
    return out


# ---------- the source form: pasted API docs → filled in ----------

async def autofill(text: str) -> dict:
    msgs = [{"role": "system", "content": (
        "Dari dokumentasi API di bawah, isi formulir sumber data bisnis. Angka yang dicari: penjualan (Rp hari ini), pesanan, dikemas (sudah dipacking), "
        "pencairan (Rp), dan angka lain yang tersedia (mis. mrr, pelanggan, toko_aktif untuk SaaS). Untuk setiap angka: endpoint (path), parameter "
        "(pakai {today}, {from}, {to}, {from_ts}, {to_ts} untuk tanggal), items (path JSON ke daftar/nilai, mis. data.orders), value (path nilai per item, "
        "mis. total_amount; kosong bila menghitung jumlah item), filter (mis. status=packed,shipped), agg (sum|count|value|avg|max), mode (today|series; series "
        "bila endpoint memberi banyak hari), date (path tanggal per item), split (path nama kanal/marketplace bila ada). JANGAN menyalin kunci rahasia. JSON: "
        "{\"name\": \"…\", \"base_url\": \"https://…\", \"auth\": {\"type\": \"none|bearer|header|query|basic\", \"name\": \"X-API-Key\"}, "
        "\"endpoints\": [{\"metric\": \"penjualan\", \"path\": \"/v1/…\", \"method\": \"GET\", \"params\": {}, \"items\": \"\", \"value\": \"\", \"filter\": \"\", "
        "\"agg\": \"sum\", \"mode\": \"today\", \"date\": \"\", \"split\": \"\"}], \"catatan\": \"yang perlu dicek pemilik\"}")},
        {"role": "user", "content": text[:20000]}]
    r = await master.run(master.Job("bisnis", "isi-sumber", "baca dokumentasi API dan isi formulir sumber bisnis", messages=msgs, json_out=True, no_free=True, max_tokens=2000))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise BisnisError(r.get("error") or "dokumentasi tidak terbaca")
    g = r["result"]
    eps = []
    for e in g.get("endpoints") or []:
        try:
            eps.append(clean_endpoint(e))
        except (BisnisError, TypeError, ValueError):
            continue
    auth = g.get("auth") if isinstance(g.get("auth"), dict) and (g.get("auth") or {}).get("type") in ("none", "bearer", "header", "query", "basic") else {"type": "none"}
    return {"name": str(g.get("name") or "")[:80], "base_url": str(g.get("base_url") or "")[:300], "auth": {"type": auth["type"], "name": str(auth.get("name") or "")[:60]},
            "endpoints": eps, "catatan": str(g.get("catatan") or "")[:500], "lane": r.get("lane")}


# ---------- what other screens get from here ----------

@home.provider("bisnis")
async def _home(m: home.Moment) -> list[dict]:
    if m.slot in ("larut", "subuh"):
        return []
    d = m.now.astimezone(WIB).date()
    rows = await db.pool().fetch("SELECT business, metric, value::float AS value FROM biz_daily WHERE day = $1 AND metric IN ('penjualan', 'pesanan', 'dikemas')", d)
    if not rows:
        return []
    by: dict[str, dict] = defaultdict(dict)
    for r in rows:
        by[r["business"]][r["metric"]] = r["value"]
    parts = [f"{b} {rp_short(v['penjualan'])}" + (f" · {round(v['pesanan'])} pesanan" if "pesanan" in v else "") for b, v in by.items() if "penjualan" in v or "pesanan" in v]
    n_alerts = await db.pool().fetchval("SELECT count(*) FROM biz_insights WHERE kind = 'alert' AND status = 'new' AND created_at >= $1",
                                        datetime(d.year, d.month, d.day, tzinfo=WIB))
    return [{"id": "bisnis", "title": "Bisnis hari ini" + (f" · {n_alerts} perlu dicek" if n_alerts else ""), "sub": " | ".join(parts)[:120] or "lihat angka hari ini",
             "route": "#/bisnis", "icon": "chart", "tone": "amber" if n_alerts else "green", "score": (62 if n_alerts else 48) + (6 if m.slot in ("sore", "malam") else 0)}]


@brief.context("bisnis")
async def _brief() -> str:
    d = datetime.now(WIB).date() - timedelta(days=1)
    rows = await db.pool().fetch("SELECT business, metric, value::float AS value FROM biz_daily WHERE day = $1 AND metric IN ('penjualan', 'pesanan')", d)
    by: dict[str, dict] = defaultdict(dict)
    for r in rows:
        by[r["business"]][r["metric"]] = r["value"]
    return "; ".join(f"kemarin {b}: {rp_short(v.get('penjualan', 0))}, {round(v.get('pesanan', 0))} pesanan" for b, v in by.items())


@recap.context("bisnis")
async def _recap(day: date) -> str:
    rows = await db.pool().fetch("SELECT business, metric, value::float AS value FROM biz_daily WHERE day = $1 AND metric IN ('penjualan', 'pesanan', 'dikemas')", day)
    by: dict[str, dict] = defaultdict(dict)
    for r in rows:
        by[r["business"]][r["metric"]] = r["value"]
    return "; ".join(f"{b}: {rp_short(v.get('penjualan', 0))}, {round(v.get('pesanan', 0))} pesanan, {round(v.get('dikemas', 0))} dikemas" for b, v in by.items())


@setup_status.check("bisnis")
async def _ready() -> dict:
    n = await db.pool().fetchval("SELECT count(*) FROM biz_sources")
    if not n:
        return setup_status.needs("Tambahkan sumber API bisnismu (Autotoko, Renature)", "#/sumber")
    bad = await db.pool().fetchval("SELECT name FROM biz_sources WHERE fails >= $1 LIMIT 1", FAIL_ALERT)
    return setup_status.needs(f"Sumber {bad} gagal dibaca — periksa", "#/sumber") if bad else setup_status.ready()


# ---------- API ----------

class SourceIn(BaseModel):
    business: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=300)
    auth: dict = Field(default_factory=lambda: {"type": "none"})
    key: str = Field(default="", max_length=4000)
    headers: dict = Field(default_factory=dict)
    endpoints: list[dict] = Field(default_factory=list, max_length=30)
    poll_min: int = Field(default=15, ge=5, le=1440)
    paused: bool = False


class TestIn(BaseModel):
    id: int | None = None                  # an existing source: its stored key is used unless a new one is given
    business: str = ""
    base_url: str = ""
    auth: dict | None = None
    key: str = ""
    headers: dict = Field(default_factory=dict)
    endpoints: list[dict] = Field(default_factory=list, max_length=30)


class BizIn(BaseModel):
    business: str = Field(min_length=1, max_length=60)


class DocIn(BaseModel):
    text: str = Field(min_length=20, max_length=40000)


def _err(e: Exception):
    raise HTTPException(409, str(e))


@router.get(API)
async def api_today(device: dict = Depends(owner)):
    v = await today_view()
    for b in v["businesses"]:
        s = await latest_strategy(b["name"])
        b["strategy"] = {"id": s["id"], "ringkasan": s.get("ringkasan"), "minggu_ini": s.get("minggu_ini"), "created_at": s["created_at"]} if s else None
    return v


@router.get(API + "/trend")
async def api_trend(business: str, metric: str = "penjualan", days: int = 120, device: dict = Depends(owner)):
    return {**await history(business, metric, days), "strategy": await latest_strategy(business)}


@router.post(API + "/strategy")
async def api_strategy(body: BizIn, device: dict = Depends(owner)):
    try:
        return await strategy(body.business, "owner")
    except BisnisError as e:
        _err(e)


@router.get(API + "/opportunities")
async def api_opps(device: dict = Depends(owner)):
    return await opportunities()


@router.post(API + "/opportunities")
async def api_opps_now(device: dict = Depends(owner)):
    try:
        r = await find_opportunities("owner")
    except BisnisError as e:
        _err(e)
    return {"status": r["status"], "task_id": r.get("task_id"), "lane": r.get("lane")}


@router.post(API + "/opportunities/{batch_id}/{index}/save")
async def api_opp_save(batch_id: int, index: int, device: dict = Depends(owner)):
    try:
        return await save_opportunity(batch_id, index, actor(device))
    except BisnisError as e:
        _err(e)


class DismissIn(BaseModel):
    reason: str = Field(default="", max_length=200)


@router.post(API + "/opportunities/{batch_id}/{index}/dismiss")
async def api_opp_dismiss(batch_id: int, index: int, body: DismissIn, device: dict = Depends(owner)):
    try:
        await dismiss_opportunity(batch_id, index, body.reason, actor(device))
    except BisnisError as e:
        _err(e)
    return {"ok": True}


@router.post(API + "/opportunities/{batch_id}/{index}/deep")
async def api_opp_deep(batch_id: int, index: int, device: dict = Depends(owner)):
    try:
        return await deep_research(batch_id, index)
    except BisnisError as e:
        _err(e)


@router.post(API + "/strategy/tasks")
async def api_strategy_tasks(body: BizIn, device: dict = Depends(owner)):
    try:
        return {"tasks": await strategy_tasks(body.business, actor(device))}
    except BisnisError as e:
        _err(e)


@router.post(API + "/alerts/{alert_id}/seen")
async def api_alert_seen(alert_id: int, device: dict = Depends(owner)):
    await db.pool().execute("UPDATE biz_insights SET status = 'seen' WHERE id = $1 AND kind = 'alert'", alert_id)
    return {"ok": True}


@router.get(API + "/sources")
async def api_sources(device: dict = Depends(owner)):
    return {"sources": await sources(), "metrics": [{"metric": k, "label": v[0], "unit": v[1]} for k, v in METRICS.items()],
            "businesses": (await appsettings.get("bisnis"))["businesses"]}


@router.post(API + "/sources")
async def api_source_new(body: SourceIn, device: dict = Depends(owner)):
    try:
        src = await save_source(None, body.model_dump(), actor(device))
    except (BisnisError, vault.VaultError) as e:
        _err(e)
    row = dict(await db.pool().fetchrow("SELECT * FROM biz_sources WHERE id = $1", src["id"]))
    asyncio.create_task(sync_one(row, "owner", BACKFILL_DAYS if any(e.get("mode") == "series" for e in row["endpoints"]) else POLL_WINDOW_DAYS))
    return src


@router.put(API + "/sources/{src_id}")
async def api_source_edit(src_id: int, body: SourceIn, device: dict = Depends(owner)):
    try:
        return await save_source(src_id, body.model_dump(), actor(device))
    except (BisnisError, vault.VaultError) as e:
        _err(e)


@router.delete(API + "/sources/{src_id}")
async def api_source_delete(src_id: int, device: dict = Depends(owner)):
    await delete_source(src_id, actor(device))
    return {"ok": True}


@router.post(API + "/sources/test")
async def api_source_test_new(body: TestIn, device: dict = Depends(owner)):
    try:
        return {"results": await test_source(body.model_dump(exclude={"id"}), body.id)}
    except (BisnisError, vault.VaultError) as e:
        _err(e)


@router.post(API + "/sources/{src_id}/test")
async def api_source_test(src_id: int, device: dict = Depends(owner)):
    if not await db.pool().fetchval("SELECT 1 FROM biz_sources WHERE id = $1", src_id):
        raise HTTPException(404)
    return {"results": await test_source({}, src_id)}


@router.post(API + "/sources/{src_id}/sync")
async def api_source_sync(src_id: int, full: bool = False, device: dict = Depends(owner)):
    """Read the source now; full=true re-reads months of history (series endpoints)."""
    row = await db.pool().fetchrow("SELECT * FROM biz_sources WHERE id = $1", src_id)
    if not row:
        raise HTTPException(404)
    r = await sync_one(dict(row), "owner", BACKFILL_DAYS if full else POLL_WINDOW_DAYS)
    return {"status": r["status"], "lane": r.get("lane"), "result": r.get("result"), "error": r.get("error")}


@router.post(API + "/sources/autofill")
async def api_autofill(body: DocIn, device: dict = Depends(owner)):
    try:
        return await autofill(body.text)
    except BisnisError as e:
        _err(e)
