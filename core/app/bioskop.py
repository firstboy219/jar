"""Bioskop (ADR-087, mockup 31): what is playing today at the cinemas near the owner — each film with its rating, genre, length, the studio
types and prices, and the show times still ahead — read from jadwalnonton.com (the cinema chains' own sites refuse this server).

Reading the schedule is a fixed procedure through the master flow (skill, no AI); if the page's layout changed and nothing can be read,
Hermes looks it up with the browser instead (the same JSON comes back). One reading per city per day is kept (cinema_cache)."""

import asyncio
import html as htmllib
import logging
import re
import time
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appsettings, db, home, master
from .bisnis import to_number
from .appauth import owner
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/cinema"
BASE = "https://jadwalnonton.com"
CACHE_MIN = 180


class CinemaError(ValueError):
    pass


# ---------- pure: reading the pages ----------

def _t(s: str) -> str:
    return " ".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def city_slug(name: str) -> str:
    n = re.sub(r"^(kota|kabupaten|kab\.?)\s+", "", (name or "").strip().lower())
    n = re.sub(r"\s+(pusat|selatan|utara|barat|timur)$", "", n)
    return re.sub(r"[^a-z]+", "-", n).strip("-") or "jakarta"


def parse_city(page: str) -> list[dict]:
    """The cinemas of a city page: [{slug, url, name, chain}]. Pure."""
    out, seen = [], set()
    for m in re.finditer(r'<a href="(https://jadwalnonton\.com/bioskop/di-[\w-]+/([\w-]+)\.html)">\s*<i class="icon (\w+)[^"]*"></i>.*?<span class="judul">(.*?)</span>', page, re.S):
        url, slug, chain, name = m.groups()
        if slug not in seen:
            seen.add(slug)
            out.append({"slug": slug, "url": url, "name": _t(name), "chain": chain.upper()})
    return out


def parse_cinema(page: str) -> dict:
    """One cinema's schedule page: {'date', 'films': [{title, url, poster, rating, genre, minutes, shows: [{type, price, times}]}]}. Pure."""
    dm = re.search(r"hari (\w+, \d{1,2} \w+ \d{4})", page)
    films = []
    chunks = page.split('class="col-sm-10 sched_desc"')
    for i in range(1, len(chunks)):
        c = chunks[i].split('class="col-sm-10 sched_desc"')[0]
        tm = re.search(r'<h2><a href="([^"]+)">(.*?)</a>', c, re.S)
        if not tm:
            continue
        posters = re.findall(r'class="poster" src="([^"]+)"', chunks[i - 1])
        rating = re.search(r'class="right rating[^"]*"[^>]*>([^<]+)<', c)
        info = re.search(r"<p>([^<]*?)\s*-\s*(\d+)\s*Menit</p>", c)
        shows = []
        for g in re.finditer(r'<span class="showgroup"[^>]*>(.*?)</span>\s*(?:<span class="htm">(.*?)</span>)?\s*<ul[^>]*>(.*?)</ul>', c, re.S):
            times = re.findall(r"<li[^>]*>(\d{2}:\d{2})</li>", g.group(3))
            price = re.search(r"Rp\.?\s*([\d.]+)", _t(g.group(2) or ""))
            if times:
                shows.append({"type": _t(g.group(1)), "price": int(price.group(1).replace(".", "")) if price else None, "times": times})
        when = re.search(r"di bioskop .*? hari (ini|\w+, \d{1,2} \w+ \d{4})", _t(c))
        if shows:
            films.append({"title": _t(tm.group(2)), "url": tm.group(1), "poster": posters[-1] if posters else "", "rating": _t(rating.group(1)) if rating else "",
                          "genre": _t(info.group(1)) if info else "", "minutes": int(info.group(2)) if info else None, "shows": shows,
                          "today": not when or when.group(1) == "ini", "day": "" if not when or when.group(1) == "ini" else when.group(1)})
    return {"date": dm.group(1) if dm else "", "films": films}


def presale(cinemas: list[dict]) -> list[dict]:
    """Films already selling tickets for a coming day. Pure."""
    seen, out = set(), []
    for cin in cinemas:
        for f in cin.get("films") or []:
            if f.get("today") is False and f["title"].lower() not in seen:
                seen.add(f["title"].lower())
                out.append({"title": f["title"], "day": f.get("day", ""), "cinema": cin["name"], "poster": f.get("poster", ""), "url": f.get("url", "")})
    return out


def by_film(cinemas: list[dict], now_hm: str) -> list[dict]:
    """Films across cinemas — each with where and when it still plays today (the soonest first). Pure."""
    films: dict[str, dict] = {}
    for cin in cinemas:
        for f in cin.get("films") or []:
            if f.get("today") is False:   # a presale for another day (XXI pages show those when today's is not out)
                continue
            key = f["title"].lower()
            e = films.setdefault(key, {"title": f["title"], **{k: f.get(k) or "" for k in ("url", "poster", "rating", "genre")}, "minutes": f.get("minutes"), "at": []})
            for s in f.get("shows") or []:   # a browser's answer may leave fields out
                left = sorted(t for t in s.get("times") or [] if isinstance(t, str) and t >= now_hm)
                if left:
                    e["at"].append({"cinema": cin["name"], "type": s.get("type") or "", "price": s.get("price"), "times": left})
    out = [f for f in films.values() if f["at"]]
    for f in out:
        f["next"] = min(t for a in f["at"] for t in a["times"])
        f["cheapest"] = min((a["price"] for a in f["at"] if a["price"]), default=None)
    return sorted(out, key=lambda f: f["next"])


# ---------- reading ----------

def _client() -> httpx.AsyncClient:   # seam for tests
    return httpx.AsyncClient(timeout=20, headers={"User-Agent": "Mozilla/5.0 (JARVIS)"}, follow_redirects=True)


async def _city(where: str = "") -> str:
    s = await appsettings.get("cinema")
    if where == "kantor" and s["office_city"]:
        return city_slug(s["office_city"])
    if s["city"]:
        return city_slug(s["city"])
    from . import ibadah
    try:
        _, name, _ = await ibadah.city()
        return city_slug(name)
    except Exception:
        return "jakarta"


async def cinemas_of(city: str) -> list[dict]:
    async with _client() as c:
        r = await c.get(f"{BASE}/bioskop/di-{city}/")
    if r.status_code != 200:
        raise CinemaError(f"daftar bioskop {city} tidak terbaca (HTTP {r.status_code})")
    return parse_city(r.text)


async def read_today(city: str, picks: list[str], limit: int) -> dict:
    all_ = await cinemas_of(city)
    if not all_:
        raise master.SkillMiss("halaman daftar bioskop berubah")
    chosen = [c for c in all_ if c["slug"] in picks] or all_[:limit]
    async with _client() as c:
        pages = await asyncio.gather(*(c.get(x["url"]) for x in chosen), return_exceptions=True)
    out = []
    for cin, p in zip(chosen, pages):
        if isinstance(p, Exception) or p.status_code != 200:
            continue
        got = parse_cinema(p.text)
        out.append({**cin, **got})
    if not any(x["films"] for x in out):
        raise master.SkillMiss("jadwal bioskop tidak terbaca dari halamannya")
    return {"city": city, "cinemas": out, "all": all_, "date": "", "source": "jadwalnonton.com"}


async def today(force: bool = False, trigger: str = "owner", where: str = "") -> dict:
    s = await appsettings.get("cinema")
    city = await _city(where)
    key = f"{city}{'@kantor' if where == 'kantor' else ''}:{datetime.now(WIB).date()}"
    row = await db.pool().fetchrow("SELECT data, fetched_at FROM cinema_cache WHERE key = $1", key)
    if row and not force and (datetime.now(WIB) - row["fetched_at"]).total_seconds() < CACHE_MIN * 60:
        data = row["data"]
    else:
        instruction = (f"Buka jadwalnonton.com (atau situs 21cineplex/CGV/Cinépolis) dan baca jadwal film HARI INI di bioskop di {city}. Jawab HANYA JSON: "
                       "{\"cinemas\": [{\"name\": \"\", \"films\": [{\"title\": \"\", \"rating\": \"\", \"genre\": \"\", \"minutes\": 0, \"shows\": "
                       "[{\"type\": \"Reguler 2D\", \"price\": 40000, \"times\": [\"19:05\"]}]}]}]}")
        picks = s["cinemas"] if where != "kantor" else s["office_cinemas"]
        r = await master.run(master.Job("bioskop", "jadwal", f"jadwal film bioskop hari ini di {city}", trigger=trigger,
                                        skill=lambda: read_today(city, picks, int(s["max"])), tools=True, instruction=instruction,
                                        title=f"Jadwal bioskop {city}", on_done="bioskop:_hermes_done", data={"key": key, "city": city}))
        if r["status"] == "waiting":
            return {"city": city, "waiting": True, "task_id": r.get("task_id"), "films": []}
        if r["status"] != "done":
            raise CinemaError(r.get("error") or "jadwal tidak terbaca")
        data = r["result"]
        await db.pool().execute("INSERT INTO cinema_cache (key, data) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()", key, data)
    now_hm = datetime.now(WIB).strftime("%H:%M")
    return {"city": data["city"], "date": data.get("date", ""), "source": data.get("source", ""), "films": by_film(data["cinemas"], now_hm), "presale": presale(data["cinemas"]),
            "cinemas": [{"slug": c.get("slug", ""), "name": c["name"], "chain": c.get("chain", ""), "films": len(c.get("films") or [])} for c in data["cinemas"]],
            "all": data.get("all", []), "picks": s["cinemas"] if where != "kantor" else s["office_cinemas"], "where": where or "rumah", "office_city": s["office_city"]}


async def _hermes_done(run_id: int, result: dict) -> None:
    """The browser looked it up (the page could not be read): kept like a reading."""
    d = result.get("data") or {}
    try:
        got = master.parse_json(result.get("text") or "")
    except ValueError:
        return
    cins = [c for c in (got.get("cinemas") or []) if isinstance(c, dict) and c.get("name")]
    if cins and result.get("ok"):
        await db.pool().execute("INSERT INTO cinema_cache (key, data) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()",
                                d.get("key"), {"city": d.get("city"), "cinemas": cins, "source": "browser Hermes", "date": ""})
        from . import hub
        await hub.broadcast({"type": "notify", "title": "Jadwal bioskop siap", "text": f"{sum(len(c.get('films') or []) for c in cins)} film hari ini", "kind": "info", "route": "#/bioskop"})


# ---------- other days and booking: the cinema chains' own sites, visited directly (ADR-087 batch H) ----------
# jadwalnonton.com shows today only; 21cineplex / CGV / Cinépolis show the coming days but refuse this server — the phone reads them.

CHAIN_SITE = {"xxi": ("21cineplex.com", "https://21cineplex.com/"), "cgv": ("cgv.id", "https://www.cgv.id/"),
              "cinepolis": ("cinepolis.co.id", "https://www.cinepolis.co.id/")}
DAY_SCHEMA = ('{"films": [{"judul": "", "bioskop": "nama bioskop", "jenis": "2D/IMAX/Premiere", "jam": ["HH:MM"], "harga": 0, "rating": "SU/13+/17+"}]}')
_loading: set[str] = set()
_failed: dict[str, tuple[float, str]] = {}   # a visit that failed, shown (not retried) for a while
RETRY_AFTER_S = 600


def chain_of(name: str) -> str:
    n = (name or "").lower()
    return "cgv" if "cgv" in n else ("cinepolis" if "cinepolis" in n or "cinépolis" in n else "xxi")


def to_cinemas(answer: dict) -> list[dict]:
    """A site visit's answer → the cinemas shape the screen reads (only real HH:MM times). Pure."""
    cins: dict[str, dict] = {}
    for f in (answer or {}).get("films") or []:
        if not isinstance(f, dict) or not f.get("judul"):
            continue
        times = sorted({t for t in (f.get("jam") or []) if isinstance(t, str) and re.fullmatch(r"([01]\d|2[0-3])[:.][0-5]\d", t.strip())})
        if not times:
            continue
        c = cins.setdefault(str(f.get("bioskop") or "Bioskop")[:80], {"name": str(f.get("bioskop") or "Bioskop")[:80], "films": []})
        price = to_number(f.get("harga"))
        c["films"].append({"title": str(f["judul"])[:120], "rating": str(f.get("rating") or "")[:10], "today": True,
                           "shows": [{"type": str(f.get("jenis") or "")[:30], "price": int(price) if price else None, "times": [t.replace(".", ":") for t in times]}]})
    return list(cins.values())


async def other_day(day: date, where: str = "") -> dict:
    """The coming day's schedule at his cinemas, read from each chain's own site (the phone's browser reads it)."""
    from . import webvisit
    s = await appsettings.get("cinema")
    city = await _city(where)
    picks = s["cinemas"] if where != "kantor" else s["office_cinemas"]
    try:
        names = [c["name"] for c in await cinemas_of(city) if not picks or c["slug"] in picks][: int(s["max"])]
    except (CinemaError, httpx.HTTPError):
        names = []
    chains = sorted({chain_of(n) for n in names} or {"xxi"})
    cinemas, errors = [], []
    for ch in chains:
        dom, home_url = CHAIN_SITE[ch]
        mine = [n for n in names if chain_of(n) == ch]
        goal = (f"Jadwal tayang film tanggal {day:%d-%m-%Y} ({['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'][day.weekday()]}) "
                f"di kota {city.replace('-', ' ').title()}" + (f", di bioskop: {', '.join(mine)}" if mine else "") + ": tiap film dengan jam tayang & harga.")
        try:
            r = await webvisit.visit(goal, home_url, [dom], DAY_SCHEMA, feature="bioskop", action="hari-lain", max_pages=6)
            cinemas += to_cinemas(r["answer"])
        except webvisit.WebError as e:
            errors.append(f"{dom}: {e}")
    if not cinemas:
        raise CinemaError("; ".join(errors) or "jadwal hari itu belum ada di situs bioskop")
    return {"city": city, "cinemas": cinemas, "source": " · ".join(CHAIN_SITE[c][0] for c in chains) + " (dibuka langsung)", "date": day.isoformat(), "errors": errors}


async def _fetch_day(key: str, day: date, where: str) -> None:
    from . import hub
    try:
        r = await master.run(master.Job("bioskop", "hari-lain", f"jadwal bioskop {day:%d %b} dari situs bioskop", skill=lambda: other_day(day, where)))
        if r["status"] == "done":
            await db.pool().execute("INSERT INTO cinema_cache (key, data) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, fetched_at = now()", key, r["result"])
            _failed.pop(key, None)
            await hub.broadcast({"type": "cinema", "key": key, "ok": True})
        else:
            _failed[key] = (time.monotonic(), (r.get("error") or "jadwal tidak terbaca")[:200])
            await hub.broadcast({"type": "cinema", "key": key, "ok": False, "error": (r.get("error") or "")[:200]})
    finally:
        _loading.discard(key)


async def day_view(offset: int, where: str = "", retry: bool = False) -> dict:
    """Another day (1–6 days ahead): from the cache, or a visit started in the background (the screen waits for the 'cinema' event)."""
    s = await appsettings.get("cinema")
    city = await _city(where)
    day = datetime.now(WIB).date() + timedelta(days=offset)
    key = f"{city}{'@kantor' if where == 'kantor' else ''}:{day.isoformat()}"
    row = await db.pool().fetchrow("SELECT data, fetched_at FROM cinema_cache WHERE key = $1 AND fetched_at > now() - interval '6 hours'", key)
    base = {"city": city, "date": day.isoformat(), "day": offset, "where": where or "rumah", "office_city": s["office_city"], "picks": s["cinemas"] if where != "kantor" else s["office_cinemas"]}
    if not row:
        failed = _failed.get(key)
        if failed and not retry and time.monotonic() - failed[0] < RETRY_AFTER_S:
            return {**base, "error": failed[1], "films": [], "presale": [], "cinemas": [], "all": [], "source": ""}
        if key not in _loading:
            _loading.add(key)
            asyncio.create_task(_fetch_day(key, day, where))
        return {**base, "loading": True, "films": [], "presale": [], "cinemas": [], "all": [], "source": ""}
    data = row["data"]
    return {**base, "source": data.get("source", ""), "films": by_film(data["cinemas"], "00:00"), "presale": [], "errors": data.get("errors", []),
            "cinemas": [{"slug": "", "name": c["name"], "chain": chain_of(c["name"]), "films": len(c.get("films") or [])} for c in data["cinemas"]], "all": []}


async def book(film: str, cinema: str, day: str, time_: str, seats: int | None = None) -> dict:
    """"Pesan tiket": the phone's browser on the chain's site picks the film, time and seats, and stops at sign-in / payment (he finishes)."""
    s = await appsettings.get("cinema")
    dom, home_url = CHAIN_SITE[chain_of(cinema)]
    n = max(1, min(int(seats or s["seats"]), 8))
    goal = (f"Di situs {dom} ({home_url}), pesan {n} tiket film \"{film}\" di {cinema} tanggal {day} jam {time_}. Pilih {n} kursi berdampingan "
            f"({s['seat_pref']}). Lanjutkan sampai halaman masuk akun atau pembayaran, lalu BERHENTI di situ (jangan masuk akun, jangan bayar) dan tulis "
            "ringkasan: film, bioskop, jam, kursi, total harga.")
    r = await master.run(master.Job("bioskop", "pesan-tiket", f"siapkan tiket {film} {time_}", trigger="owner", phone={"app": "web", "goal": goal},
                                    title=f"Tiket {film} {time_}"[:80], no_free=True))
    if r["status"] == "failed":
        raise CinemaError(r.get("error") or "browser HP tidak bisa dibuka")
    return {"status": r["status"], "task_id": r.get("task_id"), "site": dom}


@home.provider("cinema")
async def _home(m: home.Moment) -> list[dict]:
    if not ("akhir-pekan" in m.tags or m.slot == "sore"):
        return []
    row = await db.pool().fetchrow("SELECT data FROM cinema_cache WHERE key LIKE $1 ORDER BY fetched_at DESC LIMIT 1", f"%:{m.now.astimezone(WIB).date()}")
    films = by_film(row["data"]["cinemas"], m.now.astimezone(WIB).strftime("%H:%M")) if row else []
    sub = f"{films[0]['title']} {films[0]['next'].replace(':', '.')}" + (f" · +{len(films) - 1} film" if len(films) > 1 else "") if films else "Lihat film hari ini"
    return [{"id": "cinema", "title": "Bioskop hari ini", "sub": sub[:100], "route": "#/bioskop", "icon": "film", "tone": "violet", "score": 34 if "akhir-pekan" in m.tags else 16}]


class PicksIn(BaseModel):
    city: str = Field(default="", max_length=60)
    cinemas: list[str] = Field(default_factory=list, max_length=12)
    where: str = Field(default="rumah", pattern="^(rumah|kantor)$")


class BookIn(BaseModel):
    film: str = Field(min_length=1, max_length=120)
    cinema: str = Field(min_length=1, max_length=120)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    seats: int | None = Field(default=None, ge=1, le=8)


@router.post(API + "/book")
async def api_book(body: BookIn, device: dict = Depends(owner)):
    try:
        return await book(body.film, body.cinema, body.date, body.time, body.seats)
    except CinemaError as e:
        raise HTTPException(409, str(e))


@router.get(API)
async def api_today(refresh: bool = False, where: str = "", day: int = 0, device: dict = Depends(owner)):
    try:
        if 1 <= day <= 6:
            return await day_view(day, where if where in ("rumah", "kantor") else "", refresh)
        return await today(refresh, "owner", where if where in ("rumah", "kantor") else "")
    except (CinemaError, httpx.HTTPError) as e:
        raise HTTPException(502, str(e) or "jadwal tidak terbaca")


@router.put(API + "/picks")
async def api_picks(body: PicksIn, device: dict = Depends(owner)):
    if body.where == "kantor":
        await appsettings.put("cinema", {"office_city": body.city, "office_cinemas": [c[:80] for c in body.cinemas]}, "owner")
    else:
        await appsettings.put("cinema", {"city": body.city, "cinemas": [c[:80] for c in body.cinemas]}, "owner")
    await db.pool().execute("DELETE FROM cinema_cache WHERE key LIKE $1", f"%:{datetime.now(WIB).date()}")
    return await appsettings.get("cinema")
