"""Investasi (ADR-087, mockup 39; owner 2026-10-29): JARVIS opens Pluang on the owner's phone and READS the portfolio (no buying), the heavy
brain weighs it against the market and his targets and gives him three options (one is always "hold"), and when he picks one in the app —
with the ADMIN PASSWORD — JARVIS opens Pluang again and carries it out: within his limit, stopping if the price moved more than his guard
since the reading, and never typing the PIN (he types it on the phone).

  read      a master-flow phone job (Hermes operates the app; a learned routine replays it without AI) — weekly, or when he taps "Baca"
  analyse   a heavy-brain job (never a free endpoint)
  execute   a master-flow phone job started only by his pick + admin password; a proposal older than PROPOSAL_HOURS must be read again
  record    what was bought is spending in Gaji (category investasi)"""

import logging
import re
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, appsettings, audit, brief, db, home, hub, master, money
from .appauth import actor, owner, require_password
from .bisnis import rp_short, to_number
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/invest"
PROPOSAL_HOURS = 12
DAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
        "senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "sabtu": 5, "minggu": 6}
TICKERS = {"emas": "GC=F", "gold": "GC=F", "bitcoin": "BTC-USD", "btc": "BTC-USD", "ethereum": "ETH-USD", "eth": "ETH-USD", "solana": "SOL-USD"}
READ_GOAL = ("Buka Pluang dan BACA saja portofolio: total nilai portofolio, saldo kas/tunai, dan setiap aset (nama, kode bila ada, jenis: emas/saham_as/"
             "kripto/reksa_dana/lainnya, jumlah unit/gram, nilai Rupiah, untung/rugi %, harga per unit sekarang). JANGAN membeli, menjual, top up, atau "
             "mengubah apa pun. Di 'selesai', tulis hasil HANYA sebagai JSON: {\"total\": 0, \"kas\": 0, \"aset\": [{\"nama\": \"\", \"kode\": \"\", "
             "\"jenis\": \"\", \"jumlah\": 0, \"nilai\": 0, \"untung_pct\": 0, \"harga\": 0}]}")


class InvestError(ValueError):
    pass


# ---------- pure ----------

def clean_portfolio(data) -> dict:
    """The phone's reading, kept to numbers that make sense. Pure."""
    d = data if isinstance(data, dict) else {}
    assets = []
    for a in d.get("aset") or []:
        if not isinstance(a, dict) or not a.get("nama"):
            continue
        jenis = str(a.get("jenis") or "lainnya").lower().replace(" ", "_")
        assets.append({"nama": str(a["nama"])[:60], "kode": str(a.get("kode") or "")[:20].upper(),
                       "jenis": jenis if jenis in ("emas", "saham_as", "kripto", "reksa_dana") else "lainnya",
                       "jumlah": to_number(a.get("jumlah")) or 0, "nilai": to_number(a.get("nilai")) or 0,
                       "untung_pct": to_number(a.get("untung_pct")), "harga": to_number(a.get("harga"))})
    total = to_number(d.get("total")) or sum(a["nilai"] for a in assets) + (to_number(d.get("kas")) or 0)
    return {"total": total, "kas": to_number(d.get("kas")) or 0, "aset": assets}


def allocation(p: dict) -> dict[str, float]:
    """Share of each kind of asset in %. Pure."""
    total = sum(a["nilai"] for a in p["aset"]) or 1
    out: dict[str, float] = {}
    for a in p["aset"]:
        out[a["jenis"]] = round(out.get(a["jenis"], 0) + a["nilai"] / total * 100, 1)
    return out


def ticker_of(a: dict) -> str | None:
    if a["jenis"] == "saham_as" and re.fullmatch(r"[A-Z.]{1,6}", a["kode"] or ""):
        return a["kode"]
    if a["jenis"] == "kripto" and re.fullmatch(r"[A-Z]{2,6}", a["kode"] or ""):
        return f"{a['kode']}-USD"
    return TICKERS.get(a["nama"].lower().split()[0]) or TICKERS.get((a["kode"] or "").lower())


def clean_options(data, p: dict, limit: float) -> list[dict]:
    """The model's options, kept within the rules: buy/sell only, sell only what he holds, buys within his limit; 'tahan' always there. Pure."""
    held = {a["nama"].lower() for a in p["aset"]} | {a["kode"].lower() for a in p["aset"] if a["kode"]}
    out = []
    for i, o in enumerate((data or {}).get("opsi") or []):
        if not isinstance(o, dict) or not o.get("judul"):
            continue
        acts, ok = [], True
        for a in o.get("aksi") or []:
            if not isinstance(a, dict):
                continue
            jenis, aset, nominal = str(a.get("jenis") or "").lower(), str(a.get("aset") or "").strip()[:60], to_number(a.get("nominal")) or 0
            if jenis not in ("beli", "jual") or not aset or nominal <= 0:
                ok = False
                break
            if jenis == "jual" and aset.lower() not in held:
                ok = False
                break
            acts.append({"jenis": jenis, "aset": aset, "nominal": round(nominal)})
        if not ok or sum(a["nominal"] for a in acts if a["jenis"] == "beli") > limit:
            continue
        out.append({"id": "", "judul": str(o["judul"])[:100], "aksi": acts, "alasan": str(o.get("alasan") or "")[:400], "risiko": str(o.get("risiko") or "")[:200]})
    if not any(not o["aksi"] for o in out):
        out.append({"id": "", "judul": "Tahan dulu", "aksi": [], "alasan": "Tidak ada transaksi minggu ini; pantau lagi pekan depan.", "risiko": ""})
    out = out[:3] if any(not o["aksi"] for o in out[:3]) else out[:2] + [next(o for o in out if not o["aksi"])]
    for i, o in enumerate(out):
        o["id"] = "ABC"[i]
    return out


def exec_goal(option: dict, p: dict, guard_pct: float, limit: float) -> str:
    """What the phone does for the option he picked: each order, the price it was read at, the guard, the PIN rule."""
    prices = {a["nama"].lower(): a for a in p["aset"]}
    lines = []
    for a in option["aksi"]:
        ref = prices.get(a["aset"].lower())
        price = f" (harga saat dibaca: Rp{int(ref['harga']):,}".replace(",", ".") + f"; BATALKAN bila harga sekarang berbeda lebih dari {guard_pct}%)" if ref and ref.get("harga") else \
            f" (periksa harga; BATALKAN bila ringkasan tidak sesuai)"
        lines.append(f"- {a['jenis'].upper()} {a['aset']} senilai Rp{a['nominal']:,}".replace(",", ".") + price)
    return (f"Di Pluang, kerjakan pilihan pemilik \"{option['judul']}\":\n" + "\n".join(lines)
            + f"\nAturan: total pembelian tidak boleh lebih dari Rp{int(limit):,}".replace(",", ".") + "; jangan Top Up/Tarik saldo — bila saldo kurang, berhenti dan "
            "laporkan; periksa ringkasan sebelum konfirmasi; PIN diketik pemilik sendiri. Di 'selesai' tulis JSON: {\"berhasil\": [{\"jenis\": \"beli\", "
            "\"aset\": \"\", \"nominal\": 0, \"harga\": 0}], \"batal\": [{\"aset\": \"\", \"alasan\": \"\"}]}")


# ---------- reading ----------

async def read(trigger: str = "owner") -> dict:
    r = await master.run(master.Job("invest", "baca", "baca portofolio di aplikasi Pluang", trigger=trigger, phone={"app": "pluang", "goal": READ_GOAL},
                                    title="Baca portofolio Pluang", on_done="invest:_read_done", no_free=True))
    if r["status"] == "failed":
        raise InvestError(r.get("error") or "tidak bisa membuka Pluang")
    return r


async def _read_done(run_id: int, result: dict) -> None:
    if not result.get("ok"):
        await hub.broadcast({"type": "notify", "title": "Gagal membaca Pluang", "text": (result.get("text") or "")[:160], "kind": "info", "route": "#/invest"})
        return
    try:
        p = clean_portfolio(master.parse_json(result.get("text") or ""))
    except ValueError:
        p = {"aset": []}
    if not p["aset"]:
        await hub.broadcast({"type": "notify", "title": "Portofolio Pluang tidak terbaca", "text": "Coba lagi dari layar Investasi.", "kind": "info", "route": "#/invest"})
        return
    sid = await db.pool().fetchval("INSERT INTO invest_snapshots (data, run_id, task_id) VALUES ($1, $2, $3) RETURNING id", p, run_id, result.get("task_id"))
    try:
        await analyse(sid, "event")
    except InvestError as e:
        log.warning("invest analysis: %s", e)


async def _market(p: dict) -> list[dict]:
    out = []
    async with brief._client() as c:
        for a in p["aset"]:
            sym = ticker_of(a)
            if sym:
                q = await _quote_30d(c, sym)
                if q:
                    out.append({"aset": a["nama"], **q})
        for label, sym in (("Rupiah/USD", "IDR=X"), ("S&P 500", "^GSPC")):
            q = await _quote_30d(c, sym)
            if q:
                out.append({"aset": label, **q})
    return out


async def _quote_30d(c: httpx.AsyncClient, sym: str) -> dict | None:
    try:
        r = await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "1mo", "interval": "1d"})
        closes = [v for v in r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"] if isinstance(v, (int, float))]
        if len(closes) < 2:
            return None
        return {"symbol": sym, "last": round(closes[-1], 2), "d1": round((closes[-1] / closes[-2] - 1) * 100, 2), "d30": round((closes[-1] / closes[0] - 1) * 100, 2)}
    except Exception:
        return None


async def analyse(snapshot_id: int, trigger: str = "owner") -> dict:
    row = await db.pool().fetchrow("SELECT data, at FROM invest_snapshots WHERE id = $1", snapshot_id)
    if not row:
        raise InvestError("bacaan portofolio tidak ada")
    p, s = row["data"], await appsettings.get("invest")
    mkt = await _market(p)
    prev = await db.pool().fetchval("SELECT data FROM invest_snapshots WHERE id < $1 ORDER BY id DESC LIMIT 1", snapshot_id)
    msgs = [{"role": "system", "content": (
        "Kamu penasihat investasi pribadi yang hati-hati untuk investor ritel Muslim di Indonesia (hindari yang jelas tidak syariah bila ada pilihan). "
        "Dari portofolio Pluang, kondisi pasar, dan target alokasi pemilik, beri TIGA opsi untuk minggu ini; satu opsi harus 'tahan' (tanpa transaksi). "
        f"Batas total pembelian per opsi Rp{int(s['limit']):,}".replace(",", ".") + "; jual hanya aset yang dimiliki; jangan menyarankan aset yang tidak ada di Pluang. "
        "Jelaskan dengan angka. JSON: {\"ringkasan\": \"2–3 kalimat\", \"kondisi\": [\"…\"], \"opsi\": [{\"judul\": \"…\", \"aksi\": [{\"jenis\": \"beli|jual\", "
        "\"aset\": \"nama persis seperti di portofolio atau nama aset Pluang\", \"nominal\": 0}], \"alasan\": \"…\", \"risiko\": \"…\"}]}")},
        {"role": "user", "content": (f"Portofolio (dibaca {row['at']:%Y-%m-%d %H:%M}): total {rp_short(p['total'])}, kas {rp_short(p['kas'])}; aset: "
                                     + "; ".join(f"{a['nama']} ({a['jenis']}) {rp_short(a['nilai'])}, untung {a['untung_pct']}%" for a in p["aset"])
                                     + f"\nAlokasi sekarang: {allocation(p)}; target pemilik: {s['targets'] or 'belum ditentukan'}; profil risiko: {s['risk']}; tujuan: {s['goal'] or '-'}"
                                     + f"\nPasar: {mkt or 'tidak tersedia'}"
                                     + (f"\nBacaan sebelumnya: total {rp_short(prev['total'])}" if prev else ""))}]
    r = await master.run(master.Job("invest", "analisa", "analisa portofolio dan beri tiga pilihan", trigger=trigger, messages=msgs, heavy=True, json_out=True,
                                    no_free=True, max_tokens=1800))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise InvestError(r.get("error") or "analisa gagal")
    opts = clean_options(r["result"], p, float(s["limit"]))
    data = {"ringkasan": str(r["result"].get("ringkasan") or "")[:500], "kondisi": [str(x)[:200] for x in r["result"].get("kondisi") or []][:6],
            "opsi": opts, "pasar": mkt, "alokasi": allocation(p), "lane": r.get("lane")}
    await db.pool().execute("UPDATE invest_proposals SET status = 'expired' WHERE status = 'new'")
    pid = await db.pool().fetchval("INSERT INTO invest_proposals (snapshot_id, data, run_id) VALUES ($1, $2, $3) RETURNING id", snapshot_id, data, r["run_id"])
    await hub.broadcast({"type": "notify", "title": "Pilihan investasi minggu ini", "text": " · ".join(f"{o['id']}: {o['judul']}" for o in opts)[:200],
                         "kind": "info", "route": "#/invest"})
    return {"id": pid, **data}


# ---------- executing his pick ----------

async def choose(proposal_id: int, option_id: str, who: str) -> dict:
    """He picked an option (the admin password was checked by the API). 'Tahan' just closes the proposal."""
    row = await db.pool().fetchrow("SELECT * FROM invest_proposals WHERE id = $1", proposal_id)
    if not row or row["status"] != "new":
        raise InvestError("pilihan ini sudah tidak berlaku")
    if row["created_at"] < datetime.now(WIB) - timedelta(hours=PROPOSAL_HOURS):
        await db.pool().execute("UPDATE invest_proposals SET status = 'expired' WHERE id = $1", proposal_id)
        raise InvestError(f"pilihan sudah lebih dari {PROPOSAL_HOURS} jam — harga bisa berubah; baca portofolio lagi")
    opt = next((o for o in row["data"]["opsi"] if o["id"] == option_id), None)
    if not opt:
        raise InvestError("opsi tidak ada")
    await audit.record(who, "invest.chosen", f"invest_proposal:{proposal_id}", option=option_id, actions=len(opt["aksi"]))
    if not opt["aksi"]:
        await db.pool().execute("UPDATE invest_proposals SET status = 'done', chosen = $2, decided_by = $3, decided_at = now(), result = '{\"tahan\": true}' WHERE id = $1",
                                proposal_id, option_id, who)
        return {"status": "done", "hold": True}
    s = await appsettings.get("invest")
    snap = await db.pool().fetchval("SELECT data FROM invest_snapshots WHERE id = $1", row["snapshot_id"]) or {"aset": []}
    r = await master.run(master.Job("invest", "eksekusi", f"kerjakan pilihan investasi {opt['judul']}", trigger="owner",
                                    phone={"app": "pluang", "goal": exec_goal(opt, snap, float(s["price_guard_pct"]), float(s["limit"]))},
                                    title=f"Pluang: {opt['judul']}", on_done="invest:_exec_done", no_free=True, data={"proposal": proposal_id, "option": option_id}))
    if r["status"] == "failed":
        raise InvestError(r.get("error") or "Pluang tidak bisa dibuka")
    await db.pool().execute("UPDATE invest_proposals SET status = 'running', chosen = $2, decided_by = $3, decided_at = now(), exec_run_id = $4 WHERE id = $1",
                            proposal_id, option_id, who, r["run_id"])
    return {"status": r["status"], "task_id": r.get("task_id"), "lane": r.get("lane")}


async def _exec_done(run_id: int, result: dict) -> None:
    pid = (result.get("data") or {}).get("proposal")
    try:
        got = master.parse_json(result.get("text") or "")
    except ValueError:
        got = {"catatan": (result.get("text") or "")[:1000]}
    ok = bool(result.get("ok"))
    await db.pool().execute("UPDATE invest_proposals SET status = $2, result = $3 WHERE id = $1", pid, "done" if ok else "failed", got if isinstance(got, dict) else {"catatan": str(got)})
    for b in (got.get("berhasil") or []) if ok and isinstance(got, dict) else []:
        n = to_number(b.get("nominal")) or 0
        if b.get("jenis") == "beli" and n > 0:
            await money.record(n, f"Pluang {b.get('aset', '')}"[:60], f"invest:{pid}:{b.get('aset', '')}"[:120], "investasi", f"beli {b.get('aset', '')}", "Pluang")
    await hub.broadcast({"type": "notify", "title": "Investasi selesai" if ok else "Investasi tidak jadi", "kind": "info", "route": "#/invest",
                         "text": "; ".join(f"{b.get('jenis')} {b.get('aset')} {rp_short(to_number(b.get('nominal')) or 0)}" for b in got.get("berhasil") or [])[:200]
                         if ok and isinstance(got, dict) else (result.get("text") or "")[:200]})


async def _due() -> str:
    s = await appsettings.get("invest")
    return s["check_at"] if datetime.now(WIB).weekday() == DAYS.get(str(s["check_day"]).lower(), 0) else ""


@appclock.daily(_due, "invest.weekly")
async def _weekly() -> None:
    try:
        await read("schedule")
    except InvestError as e:
        log.info("weekly Pluang reading: %s", e)


async def state() -> dict:
    snap = await db.pool().fetchrow("SELECT id, at, data FROM invest_snapshots ORDER BY id DESC LIMIT 1")
    prop = await db.pool().fetchrow("SELECT * FROM invest_proposals ORDER BY id DESC LIMIT 1")
    hist = [{"at": r["at"], "total": r["data"].get("total")} for r in await db.pool().fetch("SELECT at, data FROM invest_snapshots ORDER BY id DESC LIMIT 12")][::-1]
    running = await db.pool().fetchrow("SELECT action, task_id FROM flow_runs WHERE feature = 'invest' AND status = 'waiting' AND started_at > now() - interval '30 minutes' ORDER BY id DESC LIMIT 1")
    s = await appsettings.get("invest")
    p = dict(prop) if prop else None
    if p:
        p["fresh"] = p["status"] == "new" and p["created_at"] > datetime.now(WIB) - timedelta(hours=PROPOSAL_HOURS)
    return {"snapshot": dict(snap) if snap else None, "proposal": p, "history": hist, "running": dict(running) if running else None,
            "settings": {k: s[k] for k in ("limit", "price_guard_pct", "targets", "check_day", "check_at", "risk", "goal")},
            "allocation": allocation(snap["data"]) if snap else {}}


@home.provider("invest")
async def _home(m: home.Moment) -> list[dict]:
    prop = await db.pool().fetchrow("SELECT data, created_at FROM invest_proposals WHERE status = 'new' AND created_at > now() - make_interval(hours => $1) ORDER BY id DESC LIMIT 1",
                                    PROPOSAL_HOURS)
    if not prop:
        return []
    return [{"id": "invest", "title": "Pilihan investasi minggu ini", "sub": " · ".join(f"{o['id']}: {o['judul']}" for o in prop["data"]["opsi"])[:110],
             "route": "#/invest", "icon": "invest", "tone": "violet", "score": 57, "cta": "Pilih"}]


# ---------- API ----------

class ChooseIn(BaseModel):
    option: str = Field(pattern="^[ABC]$")
    password: str = Field(min_length=1, max_length=200)


@router.get(API)
async def api_state(device: dict = Depends(owner)):
    return await state()


@router.post(API + "/read")
async def api_read(device: dict = Depends(owner)):
    try:
        r = await read("owner")
    except InvestError as e:
        raise HTTPException(409, str(e))
    return {"status": r["status"], "task_id": r.get("task_id"), "lane": r.get("lane")}


@router.post(API + "/analyse")
async def api_analyse(device: dict = Depends(owner)):
    sid = await db.pool().fetchval("SELECT id FROM invest_snapshots ORDER BY id DESC LIMIT 1")
    if not sid:
        raise HTTPException(409, "belum ada bacaan portofolio — baca dulu")
    try:
        return await analyse(sid, "owner")
    except InvestError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/proposal/{proposal_id}/choose")
async def api_choose(proposal_id: int, body: ChooseIn, device: dict = Depends(owner)):
    await require_password(device, body.password, f"invest_proposal:{proposal_id}")   # always: money leaves his account
    try:
        return await choose(proposal_id, body.option, actor(device))
    except InvestError as e:
        raise HTTPException(409, str(e))
