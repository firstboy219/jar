"""Jarvis-GM (Blueprint v4 Fase 1, ADR-042): directs a company's Hermes-DGM with that company's context only.

Lifecycle of a directive (gm_directives, isolated per company by row-level security):
  create → classify (does it spend money, publish, or message someone outside? → the owner approves FIRST)
         → queued → dispatch through the company's adapter, with task_key as idempotency key → sent (deadline set)
         → signed callback(s) from Hermes-DGM: progress | done | failed | needs_approval
           needs_approval → an approval on the owner's phone; the decision is relayed back to Hermes-DGM
         → completed / failed; no callback by the deadline → resend with the SAME task_key (bounded by the company's
           max_retries), then timed_out and the owner is told.
Hermes-DGM's real API is NOT KNOWN yet: `HttpDGM` follows the draft from blueprint v3 and refuses to call out until
the owner marks the company's contract as verified; `MockDGM` simulates a DGM so the whole flow can be tested.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

import httpx

from . import approvals, audit, companies, db, reports

log = logging.getLogger("jarvis-core.gm")
CALLBACK_SKEW_S = 300
UNVERIFIED = "BELUM DIVERIFIKASI"
# Kinds of work, and whether they change something outside (money, publication, messages to other people).
ACTIONS = {
    "laporan": False, "status": False, "analisis": False, "riset": False, "rencana": False, "draf_kampanye": False,
    "rekap_kpi": False, "tinjau": False, "tugaskan_tim_internal": False,
    "keluarkan_anggaran": True, "publikasi": True, "kirim_pesan_eksternal": True, "beli": True, "kontrak": True,
    "rekrut": True, "ubah_harga": True,
}
_EXTERNAL_WORDS = re.compile(
    r"\b(bayar|transfer|beli|belanja|anggaran|budget|iklan|ads|boost|publikasi|publish|posting|unggah|upload|kirim(kan)? "
    r"(ke|email|pesan|surat)|email ke|tanda ?tangan|kontrak|rekrut|pecat|naikkan harga|turunkan harga|ubah harga|refund|pesan(kan)?)\b", re.I)


class GMError(ValueError):
    pass


def external_effect(action: str, instruction: str, constraints: dict) -> bool:
    """Conservative: a known external action, any budget, or words that spend/publish/message → True. Pure; unit-tested."""
    if ACTIONS.get(action):
        return True
    if float((constraints or {}).get("budget_usd") or 0) > 0:
        return True
    return bool(_EXTERNAL_WORDS.search(instruction or ""))


def payload(d: dict, company: dict, context: str, callback_url: str) -> dict:
    """The directive as sent to Hermes-DGM. Field set = draft from blueprint v3 — BELUM DIVERIFIKASI. Pure."""
    return {"company_id": company["id"], "task_id": str(d["task_key"]), "action": d["action"], "instruction": d["instruction"],
            "constraints": d["constraints"] or {}, "requires_owner_approval": d["requires_owner_approval"],
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "callback_url": callback_url,
            "context": context}


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(secret: str | None, timestamp: str, body: bytes, signature: str, now: float | None = None) -> bool:
    """HMAC-SHA256 over "<timestamp>.<body>", timestamp within ±5 minutes (replays of old callbacks fail). Pure."""
    if not secret or not signature or not timestamp.isdigit():
        return False
    if abs((now or time.time()) - int(timestamp)) > CALLBACK_SKEW_S:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


def backoff_s(attempt: int) -> int:
    """30 s, 2 min, 8 min, … capped at 1 h. Pure."""
    return min(3600, 30 * 4 ** max(0, attempt - 1))


# ---------- adapters ----------

class MockDGM:
    """A stand-in Hermes-DGM (BELUM DIVERIFIKASI). It answers through the REAL signed callback path, so everything
    except the network contract is exercised. `behaviour[company_id]`: ok | silent | needs_approval | error."""
    name = "mock"
    behaviour: dict[str, str] = {}
    delay_s = 2.0
    sent: list[dict] = []

    async def send(self, company: dict, body: dict) -> dict:
        mode = self.behaviour.get(company["id"], "ok")
        self.sent.append(body)
        if mode == "error":
            raise GMError("tiruan: Hermes-DGM menolak (simulasi)")
        if mode != "silent":
            asyncio.get_running_loop().create_task(self._answer(company, body, mode))
        return {"accepted": True, "simulated": True}

    async def decide(self, company: dict, task_key: str, approved: bool) -> dict:
        self.sent.append({"decision": approved, "task_id": task_key})
        if approved:
            asyncio.get_running_loop().create_task(self._answer(company, {"task_id": task_key, "action": "lanjut"}, "ok"))
        return {"relayed": True, "simulated": True}

    async def cancel(self, company: dict, task_key: str) -> dict:
        self.sent.append({"cancel": task_key})
        return {"cancelled": True, "simulated": True}

    async def _answer(self, company: dict, body: dict, mode: str) -> None:
        await asyncio.sleep(self.delay_s)
        creds = await companies.credentials(company["id"])
        cb = {"task_id": body["task_id"], "callback_id": uuid.uuid4().hex,
              "status": "needs_approval" if mode == "needs_approval" else "done",
              "result": f"[SIMULASI — bukan Hermes-DGM sungguhan] Arahan '{body.get('action')}' untuk {company['name']} diterima dan dikerjakan tim.",
              "cost_usd": 0}
        if mode == "needs_approval":
            cb["approval_request"] = {"title": "Simulasi: keluarkan anggaran iklan Rp5.000.000", "amount_idr": 5_000_000}
        raw = json.dumps(cb).encode()
        ts = str(int(time.time()))
        try:
            await callback(company["id"], raw, ts, sign(creds["callback_secret"], ts, raw))
        except GMError as e:
            log.warning("mock callback refused: %s", e)


class HttpDGM:
    """REST adapter for a real Hermes-DGM. Endpoints and fields follow blueprint v3's DRAFT — BELUM DIVERIFIKASI.
    It refuses to call out until the owner marks the company's contract as verified at the admin page."""
    name = "http"

    async def _call(self, company: dict, method: str, path: str, body: dict | None = None) -> dict:
        if not company.get("contract_verified"):
            raise GMError(f"kontrak API Hermes-DGM untuk {company['name']} {UNVERIFIED}: konfirmasi dulu di halaman admin")
        if not company.get("dgm_url"):
            raise GMError(f"alamat Hermes-DGM {company['name']} belum diisi")
        token = (await companies.credentials(company["id"]))["token"]
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.request(method, company["dgm_url"].rstrip("/") + path, json=body,
                                headers={"Authorization": f"Bearer {token}"} if token else {})
        if r.status_code >= 400:
            raise GMError(f"Hermes-DGM HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text[:500]}

    async def send(self, company: dict, body: dict) -> dict:
        return await self._call(company, "POST", "/directives", body)

    async def decide(self, company: dict, task_key: str, approved: bool) -> dict:
        return await self._call(company, "POST", f"/directives/{task_key}/decision", {"approved": approved})

    async def cancel(self, company: dict, task_key: str) -> dict:
        return await self._call(company, "POST", f"/directives/{task_key}/cancel", {})


ADAPTERS = {"mock": MockDGM(), "http": HttpDGM()}


def adapter(company: dict):
    return ADAPTERS[company.get("adapter") or "mock"]


# ---------- directives ----------

def callback_url(company_id: str) -> str:
    return f"https://vis1.cosger.online/api/v1/gm/callback/{company_id}"


async def create(company_id: str, action: str, instruction: str, actor: str, *, constraints: dict | None = None,
                 session_id: str | None = None, task_key: str | None = None) -> dict:
    """A directive for a company's Hermes-DGM. Repeating the same task_key returns the existing directive (no double work)."""
    company = await companies.get(company_id)
    if not company["active"]:
        raise GMError(f"{company['name']} sedang nonaktif")
    action = re.sub(r"[^a-z0-9_]+", "_", (action or "tinjau").lower()).strip("_")[:40] or "tinjau"
    instruction = " ".join((instruction or "").split())
    if len(instruction) < 10:
        raise GMError("instruksi terlalu singkat")
    constraints = {k: v for k, v in (constraints or {}).items() if k in ("budget_usd", "deadline_hours", "notes")}
    key = uuid.UUID(task_key) if task_key else uuid.uuid4()
    ext = external_effect(action, instruction, constraints)
    over_budget = await _over_month_budget(company, float(constraints.get("budget_usd") or 0))
    needs_owner = ext or over_budget
    async with companies.scope(company_id) as conn:
        existing = await conn.fetchrow("SELECT * FROM gm_directives WHERE task_key = $1 AND company_id = $2", key, company_id)
        if existing:
            return dict(existing) | {"duplicate": True}
        row = await conn.fetchrow(
            """INSERT INTO gm_directives (company_id, task_key, action, instruction, constraints, external_effect,
                                          requires_owner_approval, status, session_id, next_attempt_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now()) RETURNING *""",
            company_id, key, action, instruction[:4000], constraints, ext, needs_owner,
            "awaiting_owner" if needs_owner else "queued", session_id)
    d = dict(row)
    await audit.record(actor, "gm.directive_created", f"company:{company_id}", directive=d["id"], external=ext)
    if needs_owner:
        why = ("mengubah sesuatu di luar (uang, publikasi, atau pesan ke pihak lain)" if ext else "") + \
              (" dan " if ext and over_budget else "") + ("melewati anggaran bulanan perusahaan" if over_budget else "")
        a = await approvals.create(
            "company_directive", f"{company['name']}: {action.replace('_', ' ')} — {instruction[:80]}",
            {"company_id": company_id, "directive_id": d["id"], "action": action, "instruction": instruction[:1500],
             "constraints": constraints, "alasan_perlu_persetujuan": why},
            actor, "high", idempotency_key=f"gm:{key}")
        async with companies.scope(company_id) as conn:
            await conn.execute("UPDATE gm_directives SET approval_id = $2 WHERE id = $1 AND company_id = $3", d["id"], a["id"], company_id)
        return d | {"approval_id": a["id"], "note": f"menunggu persetujuanmu karena {why}"}
    await dispatch(company_id, d["id"])
    return await get(company_id, d["id"])


async def _over_month_budget(company: dict, adding: float) -> bool:
    cap = company.get("budget_usd_month")
    if cap is None or adding <= 0:
        return False
    async with companies.scope(company["id"]) as conn:
        spent = await conn.fetchval(
            """SELECT coalesce(sum((constraints->>'budget_usd')::numeric), 0) FROM gm_directives
               WHERE company_id = $1 AND created_at >= date_trunc('month', now()) AND status NOT IN ('rejected', 'cancelled', 'failed')""",
            company["id"])
    return float(spent) + adding > float(cap)


async def get(company_id: str, directive_id: int) -> dict:
    async with companies.scope(company_id) as conn:
        row = await conn.fetchrow("SELECT * FROM gm_directives WHERE id = $1 AND company_id = $2", directive_id, company_id)
    if not row:
        raise GMError("arahan tidak ditemukan")
    return dict(row)


async def list_(company_id: str, limit: int = 30) -> list[dict]:
    async with companies.scope(company_id) as conn:
        rows = await conn.fetch("SELECT * FROM gm_directives WHERE company_id = $2 ORDER BY id DESC LIMIT $1", limit, company_id)
    return [dict(r) for r in rows]


async def dispatch(company_id: str, directive_id: int) -> dict:
    """Send (or resend, same task_key) one directive. Failures back off; past max_retries the owner is told."""
    company = await companies.get(company_id)
    d = await get(company_id, directive_id)
    if d["status"] not in ("queued", "sent", "acknowledged"):
        return d
    body = payload(d, company, await companies.context_block(company_id), callback_url(company_id))
    try:
        ack = await adapter(company).send(company, body)
    except (GMError, httpx.HTTPError) as e:
        attempts = d["attempts"] + 1
        final = attempts > company["max_retries"]
        async with companies.scope(company_id) as conn:
            await conn.execute(
                """UPDATE gm_directives SET attempts = $2, error = $3, status = $4, next_attempt_at = now() + make_interval(secs => $5),
                          updated_at = now() WHERE id = $1 AND company_id = $6""",
                directive_id, attempts, str(e)[:500], "failed" if final else "queued", backoff_s(attempts), company_id)
        if final:
            await _tell(d, company, f"Arahan ke {company['name']} ({d['action'].replace('_', ' ')}) gagal dikirim setelah {attempts} kali: {str(e)[:150]}")
        return await get(company_id, directive_id)
    async with companies.scope(company_id) as conn:
        await conn.execute(
            """UPDATE gm_directives SET status = 'sent', attempts = attempts + 1, response = $2, error = NULL,
                      deadline = now() + make_interval(secs => $3), next_attempt_at = NULL, updated_at = now() WHERE id = $1 AND company_id = $4""",
            directive_id, ack, company["callback_timeout_s"], company_id)
    await audit.record("jarvis-gm", "gm.dispatched", f"company:{company_id}", directive=directive_id, adapter=adapter(company).name)
    return await get(company_id, directive_id)


async def on_owner_approved(detail: dict) -> dict:
    """The owner approved a directive that changes something outside: now it may go out."""
    cid, did = detail["company_id"], int(detail["directive_id"])
    async with companies.scope(cid) as conn:
        await conn.execute("UPDATE gm_directives SET status = 'queued', updated_at = now() WHERE id = $1 AND company_id = $2 AND status = 'awaiting_owner'", did, cid)
    d = await dispatch(cid, did)
    return {"directive": did, "status": d["status"]}


async def on_result_decision(detail: dict) -> dict:
    """The owner approved what Hermes-DGM asked to do; relay it."""
    company = await companies.get(detail["company_id"])
    did = int(detail["directive_id"])
    await adapter(company).decide(company, detail["task_key"], True)
    async with companies.scope(company["id"]) as conn:
        await conn.execute("UPDATE gm_directives SET status = 'sent', deadline = now() + make_interval(secs => $2), updated_at = now() WHERE id = $1 AND company_id = $3",
                           did, company["callback_timeout_s"], company["id"])
    return {"relayed": True, "directive": did}


async def cancel(company_id: str, directive_id: int, actor: str) -> dict:
    """Jarvis-GM may cancel on its own (blueprint: no owner needed)."""
    company = await companies.get(company_id)
    d = await get(company_id, directive_id)
    if d["status"] in ("completed", "rejected", "failed", "timed_out", "cancelled"):
        return d
    if d["status"] in ("sent", "acknowledged", "callback_received", "awaiting_owner_result"):
        try:
            await adapter(company).cancel(company, str(d["task_key"]))
        except (GMError, httpx.HTTPError) as e:
            log.warning("cancel not relayed: %s", e)
    async with companies.scope(company_id) as conn:
        await conn.execute("UPDATE gm_directives SET status = 'cancelled', updated_at = now() WHERE id = $1 AND company_id = $2", directive_id, company_id)
    await audit.record(actor, "gm.cancelled", f"company:{company_id}", directive=directive_id)
    return await get(company_id, directive_id)


async def callback(company_id: str, raw: bytes, timestamp: str, signature: str) -> dict:
    """Hermes-DGM reporting back. Signed with the company's secret; replays (same callback_id, old timestamp) ignored."""
    company = await companies.get(company_id)
    if not verify((await companies.credentials(company_id))["callback_secret"], timestamp, raw, signature):
        raise GMError("tanda tangan callback tidak sah")
    try:
        body = json.loads(raw)
        key = uuid.UUID(str(body["task_id"]))
    except (ValueError, KeyError, TypeError) as e:
        raise GMError("isi callback tidak valid") from e
    cb_id = str(body.get("callback_id") or hashlib.sha256(raw).hexdigest()[:32])[:64]
    status = str(body.get("status") or "progress")
    async with companies.scope(company_id) as conn:
        d = await conn.fetchrow("SELECT * FROM gm_directives WHERE task_key = $1 AND company_id = $2 FOR UPDATE", key, company_id)
        if not d:
            raise GMError("arahan tidak dikenal untuk perusahaan ini")
        if cb_id in d["seen_callbacks"]:
            return {"duplicate": True, "directive": d["id"]}
        if d["status"] in ("cancelled", "completed", "failed", "timed_out", "rejected"):
            await conn.execute("UPDATE gm_directives SET seen_callbacks = array_append(seen_callbacks, $2) WHERE id = $1 AND company_id = $3", d["id"], cb_id, company_id)
            return {"ignored": d["status"], "directive": d["id"]}
        new = {"done": "completed", "failed": "failed", "needs_approval": "awaiting_owner_result"}.get(status, "acknowledged")
        await conn.execute(
            """UPDATE gm_directives SET status = $2, callback = $3, seen_callbacks = array_append(seen_callbacks, $4),
                      deadline = CASE WHEN $2 = 'acknowledged' THEN now() + make_interval(secs => $5) ELSE deadline END,
                      updated_at = now() WHERE id = $1 AND company_id = $6""", d["id"], new, body, cb_id, company["callback_timeout_s"], company_id)
    d = dict(d)
    await audit.record("hermes-dgm", f"gm.callback.{status}", f"company:{company_id}", directive=d["id"])
    result = str(body.get("result") or "")[:1500]
    if new == "completed":
        await _tell(d, company, f"Laporan {company['name']} ({d['action'].replace('_', ' ')}): {result or 'selesai tanpa catatan.'}")
    elif new == "failed":
        await _tell(d, company, f"{company['name']} melaporkan arahan '{d['action'].replace('_', ' ')}' gagal: {result or 'tanpa keterangan'}")
    elif new == "awaiting_owner_result":
        req = body.get("approval_request") or {}
        a = await approvals.create(
            "company_action", f"{company['name']} minta persetujuan: {str(req.get('title') or d['action'])[:100]}",
            {"company_id": company_id, "directive_id": d["id"], "task_key": str(key), "permintaan": req, "hasil_sejauh_ini": result},
            "hermes-dgm", "high", idempotency_key=f"gmres:{key}:{cb_id}")
        async with companies.scope(company_id) as conn:
            await conn.execute("UPDATE gm_directives SET approval_id = $2 WHERE id = $1 AND company_id = $3", d["id"], a["id"], company_id)
        await _tell(d, company, f"{company['name']} minta persetujuanmu: {str(req.get('title') or '')[:120]}. Cek Persetujuan #{a['id']}.")
    return {"accepted": True, "directive": d["id"], "status": new}


async def _tell(d: dict, company: dict, text: str) -> None:
    await reports._create(None, d.get("session_id") or "system", text)


async def tick() -> dict:
    """From the background loop: due (re)sends, deadlines passed without a callback, owner rejections to relay."""
    out = {"sent": 0, "retried": 0, "timed_out": 0}
    for company in await companies.all_():
        cid = company["id"]
        async with companies.scope(cid) as conn:
            due = await conn.fetch("SELECT id FROM gm_directives WHERE company_id = $1 AND status = 'queued' AND next_attempt_at <= now()", cid)
            late = await conn.fetch("SELECT * FROM gm_directives WHERE company_id = $1 AND status IN ('sent', 'acknowledged') AND deadline < now()", cid)
            rejected = await conn.fetch(
                """SELECT g.id, g.status, g.task_key FROM gm_directives g JOIN approvals a ON a.id = g.approval_id
                   WHERE g.company_id = $1 AND g.status IN ('awaiting_owner', 'awaiting_owner_result') AND a.status IN ('rejected', 'expired')""", cid)
        for r in due:
            await dispatch(cid, r["id"])
            out["sent"] += 1
        for d in late:
            if d["attempts"] <= company["max_retries"]:
                async with companies.scope(cid) as conn:
                    await conn.execute("UPDATE gm_directives SET status = 'queued', next_attempt_at = now() WHERE id = $1 AND company_id = $2", d["id"], cid)
                await dispatch(cid, d["id"])  # same task_key: Hermes-DGM must treat it as the same directive
                out["retried"] += 1
            else:
                async with companies.scope(cid) as conn:
                    await conn.execute("UPDATE gm_directives SET status = 'timed_out', updated_at = now() WHERE id = $1 AND company_id = $2", d["id"], cid)
                await _tell(dict(d), company, f"{company['name']} tidak membalas arahan '{d['action'].replace('_', ' ')}' setelah "
                                              f"{d['attempts']} kali kirim. Cek server Hermes-DGM-nya.")
                out["timed_out"] += 1
        for r in rejected:
            if r["status"] == "awaiting_owner_result":
                try:
                    await adapter(company).decide(company, str(r["task_key"]), False)
                except (GMError, httpx.HTTPError) as e:
                    log.warning("rejection not relayed: %s", e)
            async with companies.scope(cid) as conn:
                await conn.execute("UPDATE gm_directives SET status = 'rejected', updated_at = now() WHERE id = $1 AND company_id = $2", r["id"], cid)
    return out
