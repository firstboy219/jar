"""Kopi (ADR-087, mockup 40; owner 2026-10-29): in the afternoon at the office JARVIS looks at the promos in Kopi Kenangan and Qpon on the
owner's phone and asks him one thing — "Mau kopi? Lagi ada diskon Kopi Kenangan Mantan Rp18 rb" — and when he says which, it orders it in the
app and pays with GoPay (he types the GoPay PIN himself; above his price limit it stops and asks).

  check   one master-flow phone job per app (Hermes reads the promo pages; a learned routine replays it without AI) — the habit siang.kopi
          (14.30 at the office) or his tap; a check younger than CHECK_REUSE_MIN is reused
  offer   when every app has answered: the best promos (and his usual) on the Kopi screen and in a notification
  order   a master-flow phone job started by his tap; what it cost is spending (Gaji, category kopi)"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appsettings, audit, db, habits, home, hub, master, money
from .appauth import actor, owner
from .bisnis import rp_short, to_number
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/coffee"
CHECK_REUSE_MIN = 120
OFFER_HOURS = 3
LABEL = {"kopikenangan": "Kopi Kenangan", "qpon": "Qpon"}


class CoffeeError(ValueError):
    pass


def check_goal(app: str) -> str:
    if app == "qpon":
        return ("Buka Qpon dan cari kupon/promo KOPI hari ini (kopi susu, latte, americano dari merchant mana pun di dekat lokasi). BACA saja, JANGAN membeli. "
                "Di 'selesai' tulis HANYA JSON: {\"promo\": [{\"menu\": \"\", \"merchant\": \"\", \"harga\": 0, \"harga_normal\": 0, \"syarat\": \"\"}]} (maks 6, termurah dulu)")
    return ("Buka Kopi Kenangan dan lihat promo/voucher yang berlaku hari ini serta harga menu kopi populer. BACA saja, JANGAN memesan. Di 'selesai' tulis "
            "HANYA JSON: {\"promo\": [{\"menu\": \"\", \"harga\": 0, \"harga_normal\": 0, \"voucher\": \"kode/nama voucher bila ada\", \"syarat\": \"\"}]} (maks 6)")


def clean_promos(data, app: str) -> list[dict]:
    out = []
    for p in (data or {}).get("promo") or []:
        if not isinstance(p, dict) or not p.get("menu"):
            continue
        harga = to_number(p.get("harga"))
        if not harga or harga <= 0:
            continue
        normal = to_number(p.get("harga_normal")) or harga
        out.append({"app": app, "label": LABEL.get(app, app), "menu": str(p["menu"])[:80], "merchant": str(p.get("merchant") or LABEL.get(app, app))[:60],
                    "harga": harga, "harga_normal": max(normal, harga), "hemat_pct": round((1 - harga / normal) * 100) if normal > harga else 0,
                    "voucher": str(p.get("voucher") or "")[:60], "syarat": str(p.get("syarat") or "")[:160]})
    return out


def best(promos: list[dict], usual: str, max_price: float) -> list[dict]:
    """The promos worth offering: within his limit, his usual menu first when it is on promo, then the biggest saving. Pure."""
    ok = [p for p in promos if p["harga"] <= max_price]
    u = " ".join((usual or "").lower().split())

    def is_usual(p):   # "Americano" is his "Americano less sugar"; "Es Kopi Susu" is not his "Kopi Kenangan Mantan"
        m = " ".join(p["menu"].lower().split())
        return bool(u) and (m in u or u in m)
    return sorted(ok, key=lambda p: (0 if is_usual(p) else 1, -p["hemat_pct"], p["harga"]))[:5]


def order_goal(choice: dict, s: dict) -> str:
    where = f"ambil sendiri (Pick Up) di outlet {s['outlet'] or 'terdekat'}" if s["pickup"] else "antar ke lokasi sekarang (Delivery)"
    voucher = f", pakai voucher/promo \"{choice['voucher']}\"" if choice.get("voucher") else ", pakai promo yang berlaku bila ada"
    if choice["app"] == "qpon":
        return (f"Di Qpon, beli kupon \"{choice['menu']}\" dari {choice.get('merchant', '')} (harga kupon sekitar Rp{int(choice['harga']):,})".replace(",", ".")
                + f"; bayar dengan GoPay. Bila total lebih dari Rp{int(s['max_price']):,}".replace(",", ".") + " berhenti dan tanya pemilik. PIN GoPay diketik pemilik. "
                "Di 'selesai' tulis JSON: {\"pesanan\": \"\", \"total\": 0, \"outlet\": \"\", \"kode\": \"kode kupon/nomor\", \"siap\": \"\"}")
    return (f"Di Kopi Kenangan, pesan 1 {choice['menu']} ({s['sugar']}), {where}{voucher}; bayar dengan GoPay. Bila total lebih dari "
            f"Rp{int(s['max_price']):,}".replace(",", ".") + " berhenti dan tanya pemilik. PIN GoPay diketik pemilik. Di 'selesai' tulis JSON: "
            "{\"pesanan\": \"\", \"total\": 0, \"ongkir\": 0, \"outlet\": \"\", \"kode\": \"nomor pesanan\", \"siap\": \"jam siap diambil / perkiraan tiba\"}")


# ---------- checking promos ----------

def learned_usual(menus: list[str], min_count: int = 2) -> str:
    """The menu he ordered most among his recent orders (at least `min_count` times); "" when there is no habit yet. Pure."""
    from collections import Counter
    c = Counter(" ".join(m.split()) for m in menus if m and m.strip())
    if not c:
        return ""
    menu, n = c.most_common(1)[0]
    return menu if n >= min_count else ""


async def _settings() -> dict:
    """His coffee settings; with no usual typed, the usual is learned from what he ordered (the last 15 orders)."""
    s = dict(await appsettings.get("coffee"))
    s["usual_learned"] = False
    if not (s["usual"] or "").strip():
        rows = await db.pool().fetch("SELECT choice->>'menu' AS m FROM coffee_offers WHERE status = 'ordered' AND choice IS NOT NULL ORDER BY id DESC LIMIT 15")
        if u := learned_usual([r["m"] or "" for r in rows]):
            s["usual"], s["usual_learned"] = u, True
    return s


async def check(trigger: str = "owner") -> dict:
    s = await _settings()
    if not s["enabled"]:
        raise CoffeeError("fitur kopi dimatikan")
    recent = await db.pool().fetchrow("SELECT * FROM coffee_offers WHERE status IN ('checking', 'offered') AND created_at > now() - make_interval(mins => $1) ORDER BY id DESC LIMIT 1",
                                      CHECK_REUSE_MIN)
    if recent:
        if recent["status"] == "offered" and trigger != "owner":
            await _tell(dict(recent))
        return dict(recent)
    apps = [a for a in s["apps"] if a in LABEL] or ["kopikenangan"]
    oid = await db.pool().fetchval("INSERT INTO coffee_offers (trigger, result) VALUES ($1, $2) RETURNING id", trigger, {"pending": apps})
    for app in apps:
        r = await master.run(master.Job("kopi", f"cek-promo-{app}", f"cek promo kopi di {LABEL[app]}", trigger=trigger, phone={"app": app, "goal": check_goal(app)},
                                        title=f"Cek promo {LABEL[app]}", on_done="coffee:_check_done", no_free=True, data={"offer": oid, "app": app}))
        if r["status"] == "failed":
            await _check_done(0, {"ok": False, "text": r.get("error") or "", "data": {"offer": oid, "app": app}})
        elif r.get("run_id"):
            await db.pool().execute("UPDATE coffee_offers SET check_run_id = coalesce(check_run_id, $2) WHERE id = $1", oid, r["run_id"])
    return dict(await db.pool().fetchrow("SELECT * FROM coffee_offers WHERE id = $1", oid))


async def _check_done(run_id: int, result: dict) -> None:
    d = result.get("data") or {}
    oid, app = d.get("offer"), d.get("app")
    promos = []
    if result.get("ok"):
        try:
            promos = clean_promos(master.parse_json(result.get("text") or ""), app)
        except ValueError:
            promos = []
    row = await db.pool().fetchrow("SELECT promos, result, status FROM coffee_offers WHERE id = $1", oid)
    if not row or row["status"] != "checking":
        return
    pending = [a for a in (row["result"] or {}).get("pending", []) if a != app]
    errors = (row["result"] or {}).get("errors", []) + ([] if result.get("ok") else [f"{LABEL.get(app, app)}: {(result.get('text') or 'gagal')[:120]}"])
    allp = (row["promos"] or []) + promos
    await db.pool().execute("UPDATE coffee_offers SET promos = $2, result = $3, updated_at = now() WHERE id = $1", oid, allp, {"pending": pending, "errors": errors})
    if pending:
        return
    s = await _settings()
    offer = best(allp, s["usual"], float(s["max_price"]))
    status = "offered" if offer or s["usual"] else "failed"
    await db.pool().execute("UPDATE coffee_offers SET status = $2, updated_at = now() WHERE id = $1", oid, status)
    if status == "offered":
        await _tell(dict(await db.pool().fetchrow("SELECT * FROM coffee_offers WHERE id = $1", oid)))


async def _tell(o: dict) -> None:
    s = await _settings()
    top = best(o["promos"] or [], s["usual"], float(s["max_price"]))
    if top:
        p = top[0]
        text = f"Lagi ada diskon {p['menu']} di {p['label']} {rp_short(p['harga'])}" + (f" (biasanya {rp_short(p['harga_normal'])})" if p["hemat_pct"] else "") + "."
    else:
        text = f"Tidak ada promo menarik; mau {s['usual']} seperti biasa?"
    await hub.broadcast({"type": "notify", "title": "Mau kopi?", "text": text, "kind": "info", "route": "#/kopi"})


@habits.action("coffee.offer", "Tawarkan kopi (cek promo)")
async def _habit(h: dict) -> dict:
    o = await check("habit")
    return {"offer": o["id"], "status": o["status"]}


# ---------- ordering ----------

async def order(offer_id: int, index: int | None, custom: str, who: str) -> dict:
    o = await db.pool().fetchrow("SELECT * FROM coffee_offers WHERE id = $1", offer_id)
    if not o or o["status"] not in ("offered", "failed", "declined"):
        raise CoffeeError("tawaran ini sudah tidak berlaku")
    if o["created_at"] < datetime.now(WIB) - timedelta(hours=OFFER_HOURS):
        raise CoffeeError("promo sudah lama — cek lagi")
    s = await _settings()
    shown = best(o["promos"] or [], s["usual"], float(s["max_price"]))
    if index is not None:
        if not 0 <= index < len(shown):
            raise CoffeeError("pilihan tidak ada")
        choice = shown[index]
    else:
        menu = (custom or s["usual"]).strip()
        if not menu:
            raise CoffeeError("tulis mau kopi apa")
        choice = {"app": "kopikenangan", "label": "Kopi Kenangan", "menu": menu[:80], "harga": float(s["max_price"]), "voucher": ""}
    await audit.record(who, "coffee.order", f"coffee_offer:{offer_id}", menu=choice["menu"], app=choice["app"])
    r = await master.run(master.Job("kopi", "pesan", f"pesan kopi {choice['menu']} di {LABEL.get(choice['app'], choice['app'])}", trigger="owner",
                                    phone={"app": choice["app"], "goal": order_goal(choice, s)}, title=f"Pesan {choice['menu']}",
                                    on_done="coffee:_order_done", no_free=True, data={"offer": offer_id}))
    if r["status"] == "failed":
        raise CoffeeError(r.get("error") or "aplikasi tidak bisa dibuka")
    await db.pool().execute("UPDATE coffee_offers SET status = 'ordering', choice = $2, order_run_id = $3, updated_at = now() WHERE id = $1", offer_id, choice, r.get("run_id"))
    return {"status": r["status"], "task_id": r.get("task_id"), "choice": choice}


async def _order_done(run_id: int, result: dict) -> None:
    oid = (result.get("data") or {}).get("offer")
    try:
        got = master.parse_json(result.get("text") or "")
    except ValueError:
        got = {"catatan": (result.get("text") or "")[:500]}
    got = got if isinstance(got, dict) else {"catatan": str(got)[:500]}
    ok = bool(result.get("ok"))
    await db.pool().execute("UPDATE coffee_offers SET status = $2, result = coalesce(result, '{}'::jsonb) || $3::jsonb, updated_at = now() WHERE id = $1",
                            oid, "ordered" if ok else "failed", {"order": got})
    total = to_number(got.get("total")) if ok else None
    if total:
        choice = await db.pool().fetchval("SELECT choice FROM coffee_offers WHERE id = $1", oid) or {}
        await money.record(total, choice.get("label") or "Kopi", f"coffee:{oid}", "kopi", got.get("pesanan") or choice.get("menu", ""), choice.get("label", ""))
    await hub.broadcast({"type": "notify", "title": "Kopi dipesan ☕" if ok else "Kopi tidak jadi dipesan", "kind": "info", "route": "#/kopi",
                         "text": (f"{got.get('pesanan', '')} · {rp_short(total) if total else ''} · {got.get('outlet', '')} {got.get('siap', '')}".strip(" ·") if ok
                                  else (result.get("text") or "")[:160])})


async def state() -> dict:
    o = await db.pool().fetchrow("SELECT * FROM coffee_offers ORDER BY id DESC LIMIT 1")
    s = await _settings()
    hist = [dict(r) for r in await db.pool().fetch("SELECT id, choice, result, created_at FROM coffee_offers WHERE status = 'ordered' ORDER BY id DESC LIMIT 8")]
    cur = dict(o) if o else None
    if cur:
        cur["best"] = best(cur["promos"] or [], s["usual"], float(s["max_price"]))
        cur["fresh"] = cur["created_at"] > datetime.now(WIB) - timedelta(hours=OFFER_HOURS)
    month = await db.pool().fetchval("SELECT coalesce(sum(amount), 0)::float FROM money_tx WHERE realized AND category = 'kopi' AND direction = 'out' AND at > date_trunc('month', now())")
    return {"offer": cur, "history": hist, "settings": s, "month_total": month}


@home.provider("coffee")
async def _home(m: home.Moment) -> list[dict]:
    o = await db.pool().fetchrow("SELECT * FROM coffee_offers WHERE status IN ('offered', 'ordering', 'ordered') AND created_at > now() - make_interval(hours => $1) ORDER BY id DESC LIMIT 1",
                                 OFFER_HOURS)
    if not o:
        return []
    if o["status"] == "offered":
        s = await _settings()
        top = best(o["promos"] or [], s["usual"], float(s["max_price"]))
        sub = f"Diskon {top[0]['menu']} {rp_short(top[0]['harga'])} di {top[0]['label']}" if top else f"{s['usual']} seperti biasa?"
        return [{"id": "coffee", "title": "Mau kopi?", "sub": sub[:100], "route": "#/kopi", "icon": "coffee", "tone": "amber", "score": 72, "cta": "Pesan"}]
    if o["status"] == "ordering":
        return [{"id": "coffee", "title": "Memesan kopi…", "sub": (o["choice"] or {}).get("menu", ""), "route": "#/kopi", "icon": "coffee", "tone": "cyan", "score": 60}]
    order_ = (o["result"] or {}).get("order") or {}
    return [{"id": "coffee", "title": "Kopi dipesan", "sub": f"{order_.get('outlet', '')} {order_.get('siap', '')}".strip()[:100] or "lihat detail", "route": "#/kopi",
             "icon": "coffee", "tone": "green", "score": 40}]


class OrderIn(BaseModel):
    index: int | None = Field(default=None, ge=0, le=10)
    custom: str = Field(default="", max_length=80)


@router.get(API)
async def api_state(device: dict = Depends(owner)):
    return await state()


@router.post(API + "/check")
async def api_check(device: dict = Depends(owner)):
    try:
        o = await check("owner")
    except CoffeeError as e:
        raise HTTPException(409, str(e))
    return {"id": o["id"], "status": o["status"]}


@router.post(API + "/{offer_id}/order")
async def api_order(offer_id: int, body: OrderIn, device: dict = Depends(owner)):
    try:
        return await order(offer_id, body.index, body.custom, actor(device))
    except CoffeeError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/{offer_id}/decline")
async def api_decline(offer_id: int, device: dict = Depends(owner)):
    await db.pool().execute("UPDATE coffee_offers SET status = 'declined', updated_at = now() WHERE id = $1 AND status = 'offered'", offer_id)
    return {"ok": True}
