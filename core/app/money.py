"""Gaji & pengeluaran (ADR-087, mockup 38): what the owner spends, per pay period (payday to payday), against the pots he allocated his
salary to — and, before payday, next period's allocation proposed by the heavy brain from what he really spent.

  recording   a fixed procedure through the master flow: GoPay / bank / e-wallet notifications the phone forwards ("Pembayaran Rp25.000 ke
              Kopi Kenangan berhasil") become transactions — never a sensitive one (OTP, PIN); what JARVIS bought itself (coffee, an
              investment) is recorded by those features; he can add one by hand
  categories  rules first (kopi, makan, transport, …); what the rules do not know is labelled by the light brain once a night
  pots        his allocation (settings money.pots: name, amount, categories); a pot at 80% (alert_pct) is told once per period
  allocation  two days before payday: a heavy-brain job proposes next period's pots; he edits and applies it"""

import calendar
import logging
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import appclock, appsettings, audit, brief, db, home, hub, master, recap, setup_status
from .appauth import actor, owner
from .bisnis import rp_short, to_number
from .location import WIB

log = logging.getLogger("jarvis-core")
router = APIRouter()
API = "/api/v1/app/money"

MONEY_APPS = {   # the packages whose notifications are about money
    "com.gojek.gopay": "GoPay", "com.gojek.app": "GoPay", "com.bca": "BCA", "id.bmri.livin": "Livin' Mandiri", "id.co.bri.brimo": "BRImo",
    "src.com.bni": "BNI", "com.jago.digitalBanking": "Jago", "id.co.bankbkemobile.digitalbank": "SeaBank", "ovo.id": "OVO", "id.dana": "DANA",
    "com.shopeepay.id": "ShopeePay", "com.EmasDigi": "Pluang", "com.bsm.activity2": "BSI", "com.btpn.dc": "Jenius",
}
CATEGORIES = {   # rules, in order: the first that matches the merchant/text
    "zakat & sedekah": r"zakat|infa[qk]|sedekah|donasi|masjid|kitabisa|baznas|wakaf",
    "investasi": r"pluang|bibit|ajaib|stockbit|reksa ?dana|emas digital|bareksa|invest",
    "tabungan": r"tabungan|dana darurat|deposito",
    "kopi": r"kopi|coffee|kenangan|janji jiwa|fore |starbucks|tomoro|point coffee|chatime|mixue",
    "makan": r"gofood|grabfood|shopeefood|resto|warung|makan|bakso|mcd|mcdonald|kfc|burger|pizza|sate|nasi|ayam|solaria|hokben|bakery|roti",
    "transport": r"goride|gocar|go-?ride|go-?car|grab(?!food)|krl|kai |commuter|transjakarta|mrt|lrt|tol\b|e-?toll|parkir|bensin|pertamina|shell|bp ak",
    "belanja": r"tokopedia|shopee(?!food|pay)|lazada|tiktok|indomaret|alfamart|superindo|blibli|hypermart|lotte|transmart|ikea|ace hardware",
    "tagihan": r"pln|listrik|token|pdam|air minum|indihome|internet|pulsa|paket data|bpjs|telkomsel|xl|indosat|smartfren|cicilan|asuransi|first media|biznet",
    "anak & keluarga": r"sekolah|spp|susu|popok|pampers|mainan|daycare|les ",
    "kesehatan": r"apotek|apotik|klinik|dokter|rumah sakit|halodoc|alodokter|kimia farma|guardian|watsons",
    "hiburan": r"cgv|xxi|cinema|bioskop|netflix|spotify|youtube premium|disney|vidio|game|steam|playstation",
}
IN_WORDS = re.compile(r"\b(masuk|diterima|menerima|kredit|cashback|refund|pengembalian dana|gaji|transfer dari|dana masuk)\b", re.I)
OUT_WORDS = re.compile(r"\b(bayar|pembayaran|dibayar|debit|pembelian|membeli|kirim|transfer ke|tarik tunai|terpotong|transaksi berhasil|belanja)\b", re.I)
AMOUNT = re.compile(r"Rp\.?\s?([\d.,]+)", re.I)


class MoneyError(ValueError):
    pass


# ---------- pure ----------

def parse_tx(package: str, title: str, text: str) -> dict | None:
    """A money app's notification → {direction, amount, merchant, app} (None when it is not a payment/receipt). Pure."""
    app = MONEY_APPS.get(package or "")
    if not app:
        return None
    blob = f"{title or ''}. {text or ''}"
    m = AMOUNT.search(blob)
    if not m:
        return None
    amount = to_number(m.group(1))
    if not amount or amount <= 0:
        return None
    if re.search(r"\b(top ?up|isi saldo)\b", blob, re.I):   # money moved between his own accounts: not spending
        return None
    direction = "in" if IN_WORDS.search(blob) and not re.search(r"\b(bayar|pembayaran|pembelian)\b", blob, re.I) else ("out" if OUT_WORDS.search(blob) else None)
    if not direction:
        return None
    mm = re.search(r"\b(?:ke|di|kepada|untuk|dari|at)\s+([A-Z0-9][\w&'. -]{1,40}?)(?:\s+(?:berhasil|sebesar|senilai|telah|sudah|pada|via)\b|[.,!]|$)", blob)
    merchant = (mm.group(1).strip() if mm else (title or app)).strip()[:60]
    return {"direction": direction, "amount": amount, "merchant": merchant, "app": app}


def categorize(merchant: str, text: str = "") -> str:
    blob = f"{merchant} {text}".lower()
    for cat, rx in CATEGORIES.items():
        if re.search(rx, blob, re.I):
            return cat
    return "lainnya"


def period_of(today: date, payday: int) -> tuple[date, date]:
    """The pay period today is in: from the last payday (a 31st payday is the month's last day) to the day before the next. Pure."""
    def pd(y, m):
        return date(y, m, min(max(1, payday), calendar.monthrange(y, m)[1]))
    this = pd(today.year, today.month)
    if today >= this:
        start = this
        ny, nm = (today.year + (today.month == 12), today.month % 12 + 1)
        nxt = pd(ny, nm)
    else:
        py, pm = (today.year - (today.month == 1), (today.month - 2) % 12 + 1)
        start, nxt = pd(py, pm), this
    return start, nxt - timedelta(days=1)


def pot_status(pots: list[dict], spent_by_cat: dict[str, float], alert_pct: int) -> list[dict]:
    """Each pot: what was spent in its categories this period, the share, and whether it is over the alert line. Pure."""
    out, claimed = [], set()
    for p in pots:
        cats = [c for c in p.get("categories") or [] if c]
        claimed |= set(cats)
        spent = sum(spent_by_cat.get(c, 0) for c in cats)
        amount = float(p.get("amount") or 0)
        pct = round(spent / amount * 100) if amount else 0
        out.append({"name": p.get("name") or "Pos", "amount": amount, "categories": cats, "spent": spent, "pct": pct, "left": amount - spent,
                    "level": "over" if amount and spent > amount else ("warn" if amount and pct >= alert_pct else "ok")})
    other = sum(v for c, v in spent_by_cat.items() if c not in claimed)
    if other:
        out.append({"name": "Di luar pos", "amount": 0, "categories": [], "spent": other, "pct": 0, "left": 0, "level": "ok", "unplanned": True})
    return out


def emergency_status(saved: float, months: int, monthly: float) -> dict:
    """The emergency fund against its target (`months` of his usual monthly spending). Pure."""
    target = round(max(0, months) * max(0.0, monthly))
    return {"saved": round(saved), "target": target, "months": months, "pct": min(100, round(saved / target * 100)) if target else 0,
            "covers_months": round(saved / monthly, 1) if monthly else 0, "monthly": round(monthly)}


def with_last(pots: list[dict], last_by_cat: dict[str, float]) -> list[dict]:
    """Each pot with what its categories cost in the previous period (to judge a proposed amount). Pure."""
    return [{**p, "last": sum(last_by_cat.get(c, 0) for c in p.get("categories") or [])} for p in pots]


# ---------- recording ----------

async def _insert(at, amount, direction, merchant, source, app="", ref=None, note="", category=None, labeled_by="aturan") -> int | None:
    return await db.pool().fetchval(
        """INSERT INTO money_tx (at, amount, direction, merchant, category, source, app, ref, note, labeled_by) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
           ON CONFLICT (ref) DO NOTHING RETURNING id""",
        at, amount, direction, merchant[:60], category or categorize(merchant, note), source, app, ref, note[:300], labeled_by)


async def record(amount: float, merchant: str, ref: str, category: str | None = None, note: str = "", app: str = "JARVIS") -> int | None:
    """What JARVIS itself bought (coffee, an investment): spending too — once."""
    tid = await _insert(datetime.now(WIB), amount, "out", merchant, "jarvis", app, ref, note, category)
    if tid:
        await check_pots()
    return tid


RECEIPT = re.compile(r"\b(struk|e-?receipt|receipt|invoice|tagihan anda|pembayaran (berhasil|diterima|sukses)|terima kasih (atas|telah) (pesanan|pembelian|berbelanja)|"
                     r"pesanan (anda|kamu) (telah|sudah)|order (confirmed|completed)|bukti (pembayaran|transaksi))\b", re.I)
TOTAL = re.compile(r"\b(?:total(?: pembayaran| tagihan| belanja| bayar)?|jumlah(?: dibayar| pembayaran)?|grand total|amount paid)\b\s*:?\s*(?:Rp\.?|IDR)\s*([\d.,]+)", re.I)


def parse_receipt(sender: str, subject: str, text: str) -> dict | None:
    """A purchase receipt in his email → {amount, merchant} (None when it is not one, or has no total). Pure."""
    blob = f"{subject or ''}. {text or ''}"
    if not RECEIPT.search(blob) or re.search(r"\b(top ?up|isi saldo|refund|pengembalian)\b", blob, re.I):
        return None
    m = TOTAL.search(blob)
    amount = to_number(m.group(1)) if m else None
    if not amount or amount <= 0:
        return None
    merchant = re.sub(r"\s*<.*", "", sender or "").strip() or "Email"
    return {"amount": amount, "merchant": merchant[:60]}


async def ingest_mail() -> int:
    """Receipts in Outlook/Gmail → spending, unless the same amount was already recorded around then (a GoPay/bank notification)."""
    last = (await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'money:last_mail'") or {}).get("id", 0)
    rows = await db.pool().fetch("SELECT id, sender, subject, snippet, received_at FROM inbox_items WHERE id > $1 AND source IN ('outlook', 'gmail') ORDER BY id LIMIT 300", last)
    new = 0
    for r in rows:
        rc = parse_receipt(r["sender"], r["subject"], r["snippet"])
        if not rc:
            continue
        twin = await db.pool().fetchval("SELECT 1 FROM money_tx WHERE direction = 'out' AND amount = $1 AND at BETWEEN $2::timestamptz - interval '1 day' AND $2::timestamptz + interval '1 day' LIMIT 1",
                                        rc["amount"], r["received_at"])
        if not twin and await _insert(r["received_at"], rc["amount"], "out", rc["merchant"], "email", "Email", f"mail:{r['id']}", (r["subject"] or "")[:200]):
            new += 1
    top = max([r["id"] for r in rows], default=last)
    if top != last:
        await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ('money:last_mail', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", {"id": top})
    return new


async def ingest() -> dict:
    """New money notifications → transactions (a fixed procedure). The last notification looked at is remembered."""
    last = (await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'money:last_notif'") or {}).get("id", 0)
    rows = await db.pool().fetch("SELECT id, package, title, text, posted_at FROM notifications WHERE id > $1 AND package = ANY($2) AND NOT sensitive ORDER BY id LIMIT 500",
                                 last, list(MONEY_APPS))
    new = 0
    for r in rows:
        tx = parse_tx(r["package"], r["title"], r["text"])
        if tx and await _insert(r["posted_at"], tx["amount"], tx["direction"], tx["merchant"], "notif", tx["app"], f"notif:{r['id']}", (r["text"] or "")[:200]):
            new += 1
    top = max([r["id"] for r in rows], default=last)
    if top != last:
        await db.pool().execute("INSERT INTO settings_kv (key, value) VALUES ('money:last_notif', $1) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", {"id": top})
    new += await ingest_mail()
    alerts = await check_pots() if new else []
    return {"new": new, "seen": len(rows), "alerts": len(alerts)}


@appclock.every(120, "money.ingest")
async def tick() -> dict | None:
    last = (await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'money:last_notif'") or {}).get("id", 0)
    last_mail = (await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = 'money:last_mail'") or {}).get("id", 0)
    if not await db.pool().fetchval("SELECT 1 FROM notifications WHERE id > $1 AND package = ANY($2) AND NOT sensitive LIMIT 1", last, list(MONEY_APPS)) \
            and not await db.pool().fetchval("SELECT 1 FROM inbox_items WHERE id > $1 AND source IN ('outlook', 'gmail') LIMIT 1", last_mail):
        return None   # nothing new from a money app or the mail: no work to run
    r = await master.run(master.Job("uang", "catat", "catat transaksi dari notifikasi GoPay/bank & struk email", trigger="event", skill=ingest))
    return r.get("result")


@appclock.daily(lambda: "02:30", "money.label")
async def label_unknown() -> dict:
    """What the rules could not place: the light brain labels it (personal content: never a free endpoint)."""
    rows = [dict(r) for r in await db.pool().fetch("SELECT id, merchant, note, amount FROM money_tx WHERE category = 'lainnya' AND labeled_by = 'aturan' ORDER BY id DESC LIMIT 40")]
    if not rows:
        return {"labeled": 0}
    cats = list(CATEGORIES) + ["lainnya"]
    msgs = [{"role": "system", "content": f"Beri kategori pengeluaran untuk tiap transaksi. Kategori: {', '.join(cats)}. JSON: {{\"items\": [{{\"id\": 1, \"kategori\": \"…\"}}]}}"},
            {"role": "user", "content": "\n".join(f"{r['id']}: {r['merchant']} — {r['note'][:120]} (Rp{int(r['amount'])})" for r in rows)}]
    r = await master.run(master.Job("uang", "kategori", "beri kategori transaksi yang belum dikenal", trigger="schedule", messages=msgs, json_out=True, no_free=True, max_tokens=1200))
    n = 0
    ids = {x["id"] for x in rows}
    for it in (r.get("result") or {}).get("items") or [] if r["status"] == "done" else []:
        try:
            i = int(it.get("id"))
        except (TypeError, ValueError):
            continue
        if i in ids and it.get("kategori") in cats:
            await db.pool().execute("UPDATE money_tx SET category = $2, labeled_by = 'ai' WHERE id = $1", i, it["kategori"])
            n += 1
    if n:
        await check_pots()
    return {"labeled": n}


# ---------- the period, the pots ----------

def _span(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime(start.year, start.month, start.day, tzinfo=WIB), datetime(end.year, end.month, end.day, tzinfo=WIB) + timedelta(days=1)


async def _spent_by_cat(start: date, end: date) -> dict[str, float]:
    t0, t1 = _span(start, end)
    rows = await db.pool().fetch("SELECT category, sum(amount)::float AS t FROM money_tx WHERE direction = 'out' AND at >= $1 AND at < $2 GROUP BY category", t0, t1)
    return {r["category"]: r["t"] for r in rows}


async def _emergency(s: dict, start: date) -> dict:
    """Saved = what he said he had (on emergency_at) plus what went to savings since; the monthly need = the last three periods' spending
    (not counting savings and investing)."""
    since = s["emergency_at"][:10] if s["emergency_at"] else "1970-01-01"
    added = await db.pool().fetchval("SELECT coalesce(sum(amount), 0)::float FROM money_tx WHERE direction = 'out' AND category = 'tabungan' AND at >= ($1::date::timestamp AT TIME ZONE 'Asia/Jakarta')",
                                     date.fromisoformat(since))
    totals = []
    ps = start
    for _ in range(3):
        ps, pe = period_of(ps - timedelta(days=1), int(s["payday"]))
        by = await _spent_by_cat(ps, pe)
        if by:
            totals.append(sum(v for k, v in by.items() if k not in ("tabungan", "investasi")))
    monthly = sum(totals) / len(totals) if totals else float(s["salary"] or 0) * 0.7
    return emergency_status(float(s["emergency_saved"] or 0) + added, int(s["emergency_months"]), monthly)


async def summary(today: date | None = None) -> dict:
    s = await appsettings.get("money")
    today = today or datetime.now(WIB).date()
    start, end = period_of(today, int(s["payday"]))
    t0, t1 = _span(start, end)
    rows = await db.pool().fetch("SELECT category, direction, sum(amount)::float AS total, count(*) AS n FROM money_tx WHERE at >= $1 AND at < $2 GROUP BY category, direction", t0, t1)
    spent = {r["category"]: r["total"] for r in rows if r["direction"] == "out"}
    income = sum(r["total"] for r in rows if r["direction"] == "in")
    total = sum(spent.values())
    days, gone = (end - start).days + 1, (today - start).days + 1
    salary = float(s["salary"] or 0)
    recent = [dict(r) for r in await db.pool().fetch("SELECT id, at, amount::float AS amount, direction, merchant, category, source, app, labeled_by FROM money_tx WHERE at >= $1 AND at < $2 ORDER BY at DESC LIMIT 40", t0, t1)]
    plan = await db.pool().fetchrow("SELECT id, period_start, data, status, created_at FROM money_plans WHERE status = 'proposed' ORDER BY id DESC LIMIT 1")
    ls, le = period_of(start - timedelta(days=1), int(s["payday"]))
    last = await _spent_by_cat(ls, le)
    plan_data = {**plan["data"], "pos": with_last(plan["data"].get("pos") or [], last)} if plan else None
    return {"period": {"start": start, "end": end, "days": days, "day": gone, "left_days": days - gone, "next_payday": end + timedelta(days=1)},
            "salary": salary, "spent": total, "income": income, "left": salary - total if salary else None,
            "pace": round(total / gone * days) if gone else 0, "by_category": dict(sorted(spent.items(), key=lambda x: -x[1])),
            "pots": with_last(pot_status(s["pots"], spent, int(s["alert_pct"])), last), "recent": recent, "settings": s,
            "last_period": {"start": ls, "end": le, "spent": sum(last.values())}, "emergency": await _emergency(s, start),
            "plan": {"id": plan["id"], "period_start": plan["period_start"], "created_at": plan["created_at"], **plan_data} if plan else None,
            "categories": list(CATEGORIES) + ["lainnya"]}


async def check_pots(today: date | None = None) -> list[dict]:
    """Tell once per period when a pot reaches the alert line (and again when it goes over)."""
    s = await summary(today)
    told = []
    for p in s["pots"]:
        if p.get("unplanned") or p["level"] == "ok":
            continue
        key = f"money:alert:{s['period']['start']}:{p['name']}:{p['level']}"
        if await db.pool().fetchval("INSERT INTO settings_kv (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING RETURNING key", key, {"pct": p["pct"]}):
            title = f"Pos {p['name']} " + ("terlewati" if p["level"] == "over" else f"sudah {p['pct']}%")
            await hub.broadcast({"type": "notify", "title": title, "text": f"Terpakai {rp_short(p['spent'])} dari {rp_short(p['amount'])}; {s['period']['left_days']} hari lagi ke gajian.",
                                 "kind": "info", "route": "#/gaji"})
            told.append({"pot": p["name"], "level": p["level"]})
    return told


async def propose(trigger: str = "owner") -> dict:
    """Next period's allocation from the last three periods' real spending (the heavy brain plans; his numbers never go to a free endpoint)."""
    s = await appsettings.get("money")
    if not s["salary"]:
        raise MoneyError("isi dulu gaji bulananmu")
    today = datetime.now(WIB).date()
    start, _ = period_of(today, int(s["payday"]))
    hist = []
    for i in range(1, 4):
        ps, pe = period_of(start - timedelta(days=1 + 31 * (i - 1)), int(s["payday"]))
        rows = await db.pool().fetch("SELECT category, sum(amount)::float AS t FROM money_tx WHERE direction = 'out' AND at >= $1 AND at < $2 GROUP BY category",
                                     datetime(ps.year, ps.month, ps.day, tzinfo=WIB), datetime(pe.year, pe.month, pe.day, tzinfo=WIB) + timedelta(days=1))
        if rows:
            hist.append(f"{ps}–{pe}: " + ", ".join(f"{r['category']} {rp_short(r['t'])}" for r in rows))
    cur = await summary(today)
    msgs = [{"role": "system", "content": (
        "Kamu perencana keuangan keluarga Muslim di Indonesia. Susun ALOKASI GAJI periode berikutnya dari pengeluaran nyata pemilik. Prinsip: "
        "kewajiban & tagihan dulu, zakat/sedekah, dana darurat & tabungan (target " + str(s["savings_pct"]) + "% bila mungkin), investasi, lalu kebutuhan "
        "harian; realistis terhadap kebiasaan (jangan memangkas drastis), hemat di kategori yang membengkak. Jumlah semua pos = gaji. JSON: "
        "{\"ringkasan\": \"2 kalimat\", \"pos\": [{\"name\": \"…\", \"amount\": 0, \"categories\": [\"kategori yang masuk pos ini\"], \"alasan\": \"…\"}], "
        "\"hemat\": [\"saran konkret\"], \"catatan\": \"…\"}. Kategori yang ada: " + ", ".join(list(CATEGORIES) + ["lainnya"]))},
        {"role": "user", "content": (f"Gaji: Rp{int(s['salary']):,}".replace(",", ".") + f"; gajian tanggal {s['payday']}. Tujuan pemilik: {s['goals'] or '-'}.\n"
                                     f"Periode berjalan: terpakai {rp_short(cur['spent'])} dalam {cur['period']['day']} hari (proyeksi {rp_short(cur['pace'])}); per kategori: "
                                     + ", ".join(f"{k} {rp_short(v)}" for k, v in cur["by_category"].items()) + "\n3 periode sebelumnya:\n" + ("\n".join(hist) or "belum ada data")
                                     + f"\nPos sekarang: {[{'name': p['name'], 'amount': p['amount'], 'bulan_lalu': round(p['last'])} for p in cur['pots'] if not p.get('unplanned')]}"
                                     + f"\nDana darurat: {rp_short(cur['emergency']['saved'])} dari target {rp_short(cur['emergency']['target'])} "
                                     f"({cur['emergency']['months']}× pengeluaran bulanan ≈ {rp_short(cur['emergency']['monthly'])}); bila belum penuh, sisihkan pos 'Dana darurat' (kategori tabungan).")}]
    r = await master.run(master.Job("uang", "alokasi", "susun alokasi gaji periode berikutnya", trigger=trigger, messages=msgs, heavy=True, json_out=True, no_free=True, max_tokens=1600))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise MoneyError(r.get("error") or "alokasi gagal disusun")
    pots = clean_pots(r["result"].get("pos"))
    if not pots:
        raise MoneyError("alokasi tidak berisi pos")
    data = {"ringkasan": str(r["result"].get("ringkasan") or "")[:400], "pos": pots, "hemat": [str(x)[:200] for x in r["result"].get("hemat") or []][:5],
            "catatan": str(r["result"].get("catatan") or "")[:300], "total": sum(p["amount"] for p in pots), "salary": s["salary"], "lane": r.get("lane")}
    await db.pool().execute("UPDATE money_plans SET status = 'dismissed' WHERE status = 'proposed'")
    pid = await db.pool().fetchval("INSERT INTO money_plans (period_start, data, run_id) VALUES ($1, $2, $3) RETURNING id", cur["period"]["next_payday"], data, r["run_id"])
    if trigger != "owner":
        await hub.broadcast({"type": "notify", "title": "Alokasi gaji bulan depan siap", "text": data["ringkasan"][:160], "kind": "info", "route": "#/gaji"})
    return {"id": pid, **data}


def clean_pots(pots) -> list[dict]:
    out = []
    for p in pots or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        amt = to_number(p.get("amount"))
        if amt is None or amt < 0:
            continue
        out.append({"name": str(p["name"])[:40], "amount": round(amt), "categories": [str(c)[:40] for c in p.get("categories") or [] if c][:8],
                    "alasan": str(p.get("alasan") or "")[:200]})
    return out[:15]


async def apply_plan(plan_id: int, pots: list[dict] | None, who: str) -> dict:
    row = await db.pool().fetchrow("SELECT data FROM money_plans WHERE id = $1 AND status = 'proposed'", plan_id)
    if not row:
        raise MoneyError("usulan tidak ada atau sudah dipakai")
    final = clean_pots(pots) if pots else row["data"]["pos"]
    await appsettings.put("money", {"pots": [{"name": p["name"], "amount": p["amount"], "categories": p["categories"]} for p in final]}, who)
    await db.pool().execute("UPDATE money_plans SET status = 'applied' WHERE id = $1", plan_id)
    await audit.record(who, "money.plan_applied", f"money_plan:{plan_id}", pots=len(final))
    return await summary()


async def _plan_due() -> str:
    s = await appsettings.get("money")
    if not s["salary"]:
        return ""
    today = datetime.now(WIB).date()
    _, end = period_of(today, int(s["payday"]))
    return "08:00" if (end - today).days == 1 else ""   # two days before payday


@appclock.daily(_plan_due, "money.plan")
async def _auto_plan() -> None:
    try:
        await propose("schedule")
    except MoneyError as e:
        log.info("allocation not proposed: %s", e)


# ---------- other screens ----------

@home.provider("money")
async def _home(m: home.Moment) -> list[dict]:
    s = await summary(m.now.astimezone(WIB).date())
    cards = []
    if s["plan"]:
        cards.append({"id": "money:plan", "title": "Alokasi gaji bulan depan", "sub": s["plan"]["ringkasan"][:100], "route": "#/gaji", "icon": "wallet", "tone": "violet", "score": 58, "cta": "Tinjau"})
    warn = [p for p in s["pots"] if p["level"] != "ok" and not p.get("unplanned")]
    if warn:
        p = warn[0]
        cards.append({"id": "money:pot", "title": f"Pos {p['name']} {p['pct']}%", "sub": f"sisa {rp_short(max(0, p['left']))} · {s['period']['left_days']} hari ke gajian",
                      "route": "#/gaji", "icon": "wallet", "tone": "amber", "score": 52})
    elif "gajian" in m.tags and s["salary"]:
        cards.append({"id": "money", "title": "Gajian", "sub": "Waktunya alokasi gaji", "route": "#/gaji", "icon": "wallet", "tone": "green", "score": 55})
    return cards


@recap.context("pengeluaran")
async def _recap(day: date) -> str:
    t0 = datetime(day.year, day.month, day.day, tzinfo=WIB)
    r = await db.pool().fetchrow("SELECT count(*) AS n, coalesce(sum(amount), 0)::float AS t FROM money_tx WHERE direction = 'out' AND at >= $1 AND at < $2", t0, t0 + timedelta(days=1))
    return f"{r['n']} transaksi keluar, total {rp_short(r['t'])}" if r and r["n"] else ""


@brief.context("keuangan")
async def _brief() -> str:
    s = await summary()
    warn = [p for p in s["pots"] if p["level"] != "ok" and not p.get("unplanned")]
    parts = [f"{s['period']['left_days']} hari ke gajian"] if s["salary"] else []
    if warn:
        parts.append("pos hampir habis: " + ", ".join(f"{p['name']} {p['pct']}%" for p in warn))
    return "; ".join(parts)


@setup_status.check("gaji")
async def _ready() -> dict:
    s = await appsettings.get("money")
    if not s["salary"]:
        return setup_status.needs("Isi gaji & tanggal gajian", "#/gaji")
    return setup_status.ready()


# ---------- API ----------

class TxIn(BaseModel):
    amount: float = Field(gt=0, le=1e11)
    merchant: str = Field(min_length=1, max_length=60)
    direction: str = Field(default="out", pattern="^(in|out)$")
    category: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=300)


class CatIn(BaseModel):
    category: str = Field(min_length=1, max_length=40)


class ApplyIn(BaseModel):
    pots: list[dict] | None = None


@router.get(API)
async def api_summary(device: dict = Depends(owner)):
    return await summary()


@router.post(API + "/tx")
async def api_add(body: TxIn, device: dict = Depends(owner)):
    tid = await _insert(datetime.now(WIB), body.amount, body.direction, body.merchant, "manual", "", None, body.note, body.category or None,
                        "pemilik" if body.category else "aturan")
    await check_pots()
    return {"id": tid}


def clean_receipt(d: dict) -> dict | None:
    """The eyes' reading of a receipt → {merchant, total, at (date/time text), items}; None when no total was read. Pure."""
    total = to_number((d or {}).get("total"))
    if not total or total <= 0 or total > 100_000_000:
        return None
    day = str((d or {}).get("tanggal") or "")[:10]
    hm = str((d or {}).get("jam") or "")[:5]
    return {"merchant": str((d or {}).get("toko") or "Struk")[:60], "total": total,
            "day": day if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else "", "time": hm if re.fullmatch(r"\d{2}:\d{2}", hm) else "",
            "items": [str(x)[:60] for x in (d or {}).get("item") or []][:12], "method": str((d or {}).get("bayar") or "")[:30]}


async def from_receipt(attachment_id: str) -> dict:
    """A photo of a receipt (camera or the gallery): read by the brain's eyes, recorded as spending — unless the same amount was already
    recorded around that time (a GoPay/bank notification or an email receipt), then only matched."""
    import base64
    from . import attachments
    m = attachments.meta(attachment_id)
    if not m or m["kind"] != "image":
        raise MoneyError("kirim foto struknya (gambar)")
    b64 = attachments.image_b64(attachment_id, 1600)
    msgs = [{"role": "system", "content": ("Baca struk/nota belanja di foto. Jangan mengarang; null bila tidak terbaca. JSON: {\"toko\": \"\", \"total\": angka rupiah yang dibayar, "
                                           "\"tanggal\": \"YYYY-MM-DD\", \"jam\": \"HH:MM\", \"item\": [\"nama barang\"], \"bayar\": \"tunai/GoPay/kartu/QRIS\"}")},
            {"role": "user", "content": [{"type": "text", "text": "Struk ini."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    r = await master.run(master.Job("uang", "struk", "baca struk belanja dari foto", messages=msgs, vision=True, json_out=True, no_free=True, max_tokens=600))
    if r["status"] != "done" or not isinstance(r["result"], dict):
        raise MoneyError(r.get("error") or "struknya tidak terbaca")
    rc = clean_receipt(r["result"])
    if not rc:
        raise MoneyError("total di struk tidak terbaca — foto lebih dekat & terang")
    try:
        at = datetime.fromisoformat(f"{rc['day']}T{rc['time'] or '12:00'}").replace(tzinfo=WIB) if rc["day"] else datetime.now(WIB)
    except ValueError:
        at = datetime.now(WIB)
    twin = await db.pool().fetchrow("""SELECT id, merchant, source FROM money_tx WHERE direction = 'out' AND amount = $1
                                        AND at BETWEEN $2::timestamptz - interval '1 day' AND $2::timestamptz + interval '1 day' LIMIT 1""", rc["total"], at)
    if twin:
        return {**rc, "duplicate": dict(twin), "lane": r.get("lane")}
    tid = await _insert(at, rc["total"], "out", rc["merchant"], "struk", "Foto struk", f"struk:{attachment_id}", "; ".join(rc["items"])[:300])
    if tid:
        await check_pots()
    return {**rc, "id": tid, "lane": r.get("lane")}


class ReceiptIn(BaseModel):
    attachment_ids: list[str] = Field(min_length=1, max_length=10)


@router.post(API + "/receipts")
async def api_receipts(body: ReceiptIn, device: dict = Depends(owner)):
    out = []
    for aid in body.attachment_ids:
        try:
            out.append({"attachment_id": aid, **await from_receipt(aid)})
        except MoneyError as e:
            out.append({"attachment_id": aid, "error": str(e)})
    return {"receipts": out}


@router.put(API + "/tx/{tx_id}")
async def api_cat(tx_id: int, body: CatIn, device: dict = Depends(owner)):
    if body.category not in list(CATEGORIES) + ["lainnya"]:
        raise HTTPException(422, "kategori tidak dikenal")
    await db.pool().execute("UPDATE money_tx SET category = $2, labeled_by = 'pemilik' WHERE id = $1", tx_id, body.category)
    return {"ok": True}


@router.delete(API + "/tx/{tx_id}")
async def api_del(tx_id: int, device: dict = Depends(owner)):
    await db.pool().execute("DELETE FROM money_tx WHERE id = $1", tx_id)
    return {"ok": True}


@router.post(API + "/plan")
async def api_plan(device: dict = Depends(owner)):
    try:
        return await propose("owner")
    except MoneyError as e:
        raise HTTPException(409, str(e))


class PotsIn(BaseModel):
    pots: list[dict] = Field(max_length=15)


async def save_pots(pots: list[dict], who: str) -> dict:
    """His own allocation, edited by hand (owner 2026-10-31: "fitur alokasi saat ini tidak bisa diedit"): names, amounts, categories."""
    final = clean_pots(pots)
    names = [p["name"].strip().lower() for p in final]
    if len(set(names)) != len(names):
        raise MoneyError("nama pos tidak boleh kembar")
    await appsettings.put("money", {"pots": [{"name": p["name"].strip(), "amount": p["amount"], "categories": p["categories"]} for p in final]}, who)
    await audit.record(who, "money.pots_edited", "money:pots", pots=len(final), total=sum(p["amount"] for p in final))
    return await summary()


@router.put(API + "/pots")
async def api_pots(body: PotsIn, device: dict = Depends(owner)):
    try:
        return await save_pots(body.pots, actor(device))
    except MoneyError as e:
        raise HTTPException(409, str(e))


@router.post(API + "/plan/{plan_id}/apply")
async def api_apply(plan_id: int, body: ApplyIn, device: dict = Depends(owner)):
    try:
        return await apply_plan(plan_id, body.pots, actor(device))
    except MoneyError as e:
        raise HTTPException(409, str(e))
