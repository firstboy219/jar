"""Company Federation data (Blueprint v4 Fase 1, ADR-042/046): companies, Company Vault, Decision Vault, entity relations.

Isolation in three layers, so a slip in one is caught by the next:
  1. every function here takes `company_id` and refuses an empty/unknown one (CompanyError);
  2. every query runs inside `scope(company_id)`: a transaction with `SET LOCAL jarvis.company`, and Postgres' row-level
     security (migration 022, FORCE'd) shows only that company's rows — a query outside a scope sees nothing;
  3. vector search over company knowledge lives in its own Qdrant collection and every search carries a mandatory
     `company_id` filter (never the owner's personal memory collection).
Credentials (Hermes-DGM token, callback secret) are AES-GCM encrypted with the vault key and only decrypted for the
one company being called.
"""

import contextlib
import logging
import re
import secrets
import uuid

import httpx

from . import audit, db, memory, sensitive, vault

log = logging.getLogger("jarvis-core.companies")
VAULT_KINDS = ("core_constraint", "strategic_pivot", "validated_finding", "kpi", "cashflow", "note")
DECISION_KINDS = ("core_constraint", "correction_pivot", "validated_finding", "tech_preference")
KIND_TITLE = {"core_constraint": "Batasan inti", "strategic_pivot": "Pivot strategis", "validated_finding": "Temuan tervalidasi",
              "kpi": "KPI", "cashflow": "Arus kas", "note": "Catatan", "correction_pivot": "Koreksi & pivot",
              "tech_preference": "Preferensi teknis"}
COLLECTION = "company_knowledge"
_ID = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_cache: dict = {"companies": None}


class CompanyError(ValueError):
    pass


# ---------- scope ----------

def _check_id(company_id: str) -> str:
    if not isinstance(company_id, str) or not _ID.match(company_id or ""):
        raise CompanyError("company_id wajib (huruf kecil/angka/strip) — kueri tanpa perusahaan ditolak")
    return company_id


@contextlib.asynccontextmanager
async def scope(company_id: str):
    """A connection whose transaction sees ONLY this company's rows (row-level security)."""
    _check_id(company_id)
    if company_id not in {c["id"] for c in await all_()}:
        raise CompanyError(f"perusahaan tidak dikenal: {company_id}")
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('jarvis.company', $1, true)", company_id)
        yield conn


# ---------- companies ----------

def slug(name: str) -> str:
    """'PT Renature Indonesia' → 'renature-indonesia'. Pure."""
    s = re.sub(r"\b(pt|cv|tbk|persero|ltd|inc)\b\.?", " ", name.lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return (s if s and s[0].isalpha() else "c-" + s)[:40] or "perusahaan"


def _public(r) -> dict:
    d = dict(r)
    d["has_dgm_token"] = d.pop("dgm_token_enc", None) is not None
    d["has_callback_secret"] = d.pop("callback_secret_enc", None) is not None
    return d


async def all_(include_inactive: bool = False) -> list[dict]:
    if _cache["companies"] is None:
        _cache["companies"] = [_public(r) for r in await db.pool().fetch("SELECT * FROM companies ORDER BY name")]
    return [c for c in _cache["companies"] if include_inactive or c["active"]]


def forget() -> None:
    _cache["companies"] = None


async def get(company_id: str) -> dict:
    c = next((c for c in await all_(True) if c["id"] == _check_id(company_id)), None)
    if not c:
        raise CompanyError(f"perusahaan tidak dikenal: {company_id}")
    return c


async def create(name: str, actor: str, aliases: list[str] | None = None, company_id: str | None = None) -> dict:
    name = " ".join(name.split())
    if len(name) < 2:
        raise CompanyError("nama perusahaan terlalu pendek")
    cid = _check_id(company_id or slug(name))
    names = sorted({a.strip().lower() for a in [name, re.sub(r"^(pt|cv)\.?\s+", "", name, flags=re.I), *(aliases or [])] if a and a.strip()})
    row = await db.pool().fetchrow(
        """INSERT INTO companies (id, name, aliases, callback_secret_enc) VALUES ($1, $2, $3, $4)
           ON CONFLICT (id) DO NOTHING RETURNING *""", cid, name[:120], names, vault.encrypt(secrets.token_urlsafe(32)))
    if not row:
        raise CompanyError(f"perusahaan {cid} sudah ada")
    forget()
    await audit.record(actor, "company.created", f"company:{cid}")
    return _public(row)


async def configure(company_id: str, actor: str, **fields) -> dict:
    """Owner settings (admin page): adapter, URL, token, timeout, retries, monthly budget, aliases, active, contract_verified."""
    await get(company_id)
    allowed = {"adapter", "dgm_url", "callback_timeout_s", "max_retries", "budget_usd_month", "aliases", "active", "contract_verified", "name"}
    sets, args = [], [company_id]
    for k, v in fields.items():
        if v is None:
            continue
        if k == "dgm_token":
            sets.append(f"dgm_token_enc = ${len(args) + 1}")
            args.append(vault.encrypt(str(v)) if v else None)
            continue
        if k not in allowed:
            raise CompanyError(f"pengaturan tidak dikenal: {k}")
        if k == "dgm_url" and v and not str(v).startswith("https://"):
            raise CompanyError("alamat Hermes-DGM harus https://")
        if k == "aliases":
            v = sorted({str(a).strip().lower() for a in v if str(a).strip()})
        sets.append(f"{k} = ${len(args) + 1}")
        args.append(v)
    if sets:
        await db.pool().execute(f"UPDATE companies SET {', '.join(sets)}, updated_at = now() WHERE id = $1", *args)
        forget()
        await audit.record(actor, "company.configured", f"company:{company_id}", fields=sorted(k for k, v in fields.items() if v is not None))
    return await get(company_id)


async def credentials(company_id: str) -> dict:
    """Decrypted token + callback secret of ONE company (for its adapter / its callback check only)."""
    row = await db.pool().fetchrow("SELECT dgm_token_enc, callback_secret_enc FROM companies WHERE id = $1", _check_id(company_id))
    if not row:
        raise CompanyError(f"perusahaan tidak dikenal: {company_id}")
    return {"token": vault.decrypt(row["dgm_token_enc"]) if row["dgm_token_enc"] else None,
            "callback_secret": vault.decrypt(row["callback_secret_enc"]) if row["callback_secret_enc"] else None}


async def rotate_callback_secret(company_id: str, actor: str) -> str:
    """A new HMAC key for Hermes-DGM's callbacks; returned ONCE so the owner can give it to the DGM server."""
    await get(company_id)
    secret = secrets.token_urlsafe(32)
    await db.pool().execute("UPDATE companies SET callback_secret_enc = $2, updated_at = now() WHERE id = $1", company_id, vault.encrypt(secret))
    await audit.record(actor, "company.callback_secret_rotated", f"company:{company_id}")
    return secret


# ---------- recognising a company in what the owner says ----------

def recognise(text: str, companies: list[dict]) -> list[str]:
    """Ids of the companies named in the text (by name or alias, whole words). Pure; unit-tested."""
    low = " " + re.sub(r"[^a-z0-9]+", " ", text.lower()) + " "
    found = []
    for c in companies:
        for name in [c["name"], *c.get("aliases", [])]:
            norm = " " + re.sub(r"[^a-z0-9]+", " ", name.lower()).strip() + " "
            if len(norm.strip()) >= 3 and norm in low:
                found.append(c["id"])
                break
    return found


async def mentioned(text: str) -> list[str]:
    return recognise(text, await all_())


# ---------- Company Vault ----------

async def vault_add(company_id: str, kind: str, title: str, actor: str, body: str = "", data: dict | None = None,
                    verified: bool = False) -> dict:
    if kind not in VAULT_KINDS:
        raise CompanyError(f"jenis isian: {', '.join(VAULT_KINDS)}")
    if found := sensitive.scan(f"{title}\n{body}"):
        raise CompanyError(f"tidak disimpan: terdeteksi data sensitif ({', '.join(found)}) — kredensial disimpan di pengaturan perusahaan")
    async with scope(company_id) as conn:
        row = await conn.fetchrow(
            """INSERT INTO company_vault (company_id, kind, title, body, data, source, verified)
               VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""", company_id, kind, title.strip()[:200], body.strip()[:8000],
            data, actor, verified)
    await _index(company_id, row["id"], f"{KIND_TITLE[kind]}: {row['title']}. {row['body']}")
    await audit.record(actor, "company.vault_added", f"company:{company_id}", kind=kind)
    return dict(row)


async def vault_list(company_id: str, kind: str | None = None, limit: int = 100) -> list[dict]:
    async with scope(company_id) as conn:
        rows = await conn.fetch(
            "SELECT * FROM company_vault WHERE company_id = $3 AND ($1::text IS NULL OR kind = $1) ORDER BY kind, updated_at DESC LIMIT $2",
            kind, limit, company_id)
    return [dict(r) for r in rows]


async def vault_delete(company_id: str, entry_id: int, actor: str) -> bool:
    async with scope(company_id) as conn:
        done = await conn.execute("DELETE FROM company_vault WHERE id = $1 AND company_id = $2", entry_id, company_id)
    ok = done.endswith(" 1")
    if ok:
        await _unindex(company_id, entry_id)
        await audit.record(actor, "company.vault_deleted", f"company:{company_id}", entry=entry_id)
    return ok


def kpi_line(entry: dict) -> str:
    """'Omzet: 120 juta IDR (Okt 2026)' from a KPI/cash-flow entry. Pure."""
    d = entry.get("data") or {}
    value = d.get("value")
    if value is None:
        return entry["title"] + (f": {entry['body'][:120]}" if entry.get("body") else "")
    unit = f" {d['unit']}" if d.get("unit") else ""
    period = f" ({d['period']})" if d.get("period") else ""
    target = f", target {d['target']}{unit}" if d.get("target") is not None else ""
    return f"{d.get('metric') or entry['title']}: {value}{unit}{period}{target}"


async def context_block(company_id: str, limit: int = 12) -> str:
    """What a worker or the main agent gets about ONE company: constraints first, then KPIs, pivots, findings."""
    c = await get(company_id)
    order = {"core_constraint": 0, "kpi": 1, "cashflow": 2, "strategic_pivot": 3, "validated_finding": 4, "note": 5}
    entries = sorted(await vault_list(company_id), key=lambda e: (order.get(e["kind"], 9), -e["updated_at"].timestamp()))[:limit]
    decisions = await decisions_list("company", company_id, limit=6)
    lines = [f"KONTEKS PERUSAHAAN: {c['name']} (company_id={company_id}). Data perusahaan lain TIDAK boleh dipakai."]
    for e in entries:
        text = kpi_line(e) if e["kind"] in ("kpi", "cashflow") else e["title"] + (f" — {e['body'][:200]}" if e["body"] else "")
        lines.append(f"- [{KIND_TITLE[e['kind']]}] {text}" + ("" if e["verified"] else " (belum diverifikasi)"))
    for d in decisions:
        lines.append(f"- [Keputusan · {KIND_TITLE[d['kind']]}] {d['text'][:200]}")
    if len(lines) == 1:
        lines.append("- (Company Vault masih kosong)")
    return "\n".join(lines)


# ---------- Decision Vault ----------

async def decision_add(entity_type: str, entity_id: str, kind: str, text: str, actor: str) -> dict:
    """A decision about a project or company: constraint, correction/pivot, validated finding, technical preference."""
    if entity_type not in ("project", "company"):
        raise CompanyError("entity_type: project | company")
    if kind not in DECISION_KINDS:
        raise CompanyError(f"jenis keputusan: {', '.join(DECISION_KINDS)}")
    entity_id = entity_id.strip().lower()
    if not entity_id:
        raise CompanyError("entity_id wajib")
    if found := sensitive.scan(text):
        raise CompanyError(f"tidak disimpan: terdeteksi data sensitif ({', '.join(found)})")
    company_id = entity_id if entity_type == "company" else None
    if company_id:
        async with scope(company_id) as conn:
            row = await conn.fetchrow(
                """INSERT INTO decision_vault (entity_type, entity_id, company_id, kind, text, source)
                   VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""", entity_type, entity_id, company_id, kind, text.strip()[:2000], actor)
    else:
        row = await db.pool().fetchrow(
            """INSERT INTO decision_vault (entity_type, entity_id, kind, text, source) VALUES ($1, $2, $3, $4, $5) RETURNING *""",
            entity_type, entity_id, kind, text.strip()[:2000], actor)
    await audit.record(actor, "decision.recorded", f"{entity_type}:{entity_id}", kind=kind)
    return dict(row)


async def decisions_list(entity_type: str, entity_id: str, limit: int = 50) -> list[dict]:
    q = """SELECT * FROM decision_vault WHERE entity_type = $1 AND entity_id = $2 AND superseded_by IS NULL
           AND company_id IS NOT DISTINCT FROM $4 ORDER BY created_at DESC LIMIT $3"""
    if entity_type == "company":
        async with scope(entity_id) as conn:
            rows = await conn.fetch(q, entity_type, entity_id, limit, entity_id)
    else:
        rows = await db.pool().fetch(q, entity_type, entity_id.lower(), limit, None)
    return [dict(r) for r in rows]


async def projects() -> list[str]:
    return [r["entity_id"] for r in await db.pool().fetch(
        "SELECT DISTINCT entity_id FROM decision_vault WHERE entity_type = 'project' ORDER BY 1")]


# ---------- entity relations ----------

async def relate(subject: tuple[str, str], relation: str, obj: tuple[str, str], actor: str, company_id: str | None = None) -> dict:
    args = (subject[0], subject[1].lower(), relation.strip().lower(), obj[0], obj[1].lower(), company_id, actor)
    sql = """INSERT INTO entity_relations (subject_type, subject_id, relation, object_type, object_id, company_id, source)
             VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING RETURNING *"""
    if company_id:
        async with scope(company_id) as conn:
            row = await conn.fetchrow(sql, *args)
    else:
        row = await db.pool().fetchrow(sql, *args)
    return dict(row) if row else {"exists": True}


async def related(entity_type: str, entity_id: str, company_id: str | None = None) -> list[dict]:
    sql = """SELECT * FROM entity_relations WHERE ((subject_type = $1 AND subject_id = $2) OR (object_type = $1 AND object_id = $2))
             AND (company_id IS NULL OR company_id IS NOT DISTINCT FROM $3) ORDER BY created_at"""
    if company_id:
        async with scope(company_id) as conn:
            rows = await conn.fetch(sql, entity_type, entity_id.lower(), company_id)
    else:
        rows = await db.pool().fetch(sql, entity_type, entity_id.lower(), None)
    return [dict(r) for r in rows]


# ---------- company knowledge in Qdrant (own collection, company filter mandatory) ----------

def _point_id(company_id: str, entry_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"company:{company_id}:{entry_id}"))


async def _ensure_collection(q: httpx.AsyncClient) -> None:
    r = await q.get(f"/collections/{COLLECTION}")
    if r.status_code == 404:
        dim = len((await memory.embed(["dimensi"]))[0])
        await q.put(f"/collections/{COLLECTION}", json={"vectors": {"size": dim, "distance": "Cosine"}})
        await q.put(f"/collections/{COLLECTION}/index", json={"field_name": "company_id", "field_schema": "keyword"})


async def _index(company_id: str, entry_id: int, text: str) -> None:
    try:
        [vector] = await memory.embed([text])
        async with memory._qdrant() as q:
            await _ensure_collection(q)
            await q.put(f"/collections/{COLLECTION}/points?wait=true", json={"points": [
                {"id": _point_id(company_id, entry_id), "vector": vector, "payload": {"company_id": company_id, "entry_id": entry_id}}]})
    except (httpx.HTTPError, ValueError) as e:  # the Postgres row is the truth; search simply misses it until reindexed
        log.warning("company knowledge not indexed: %s", e)


async def _unindex(company_id: str, entry_id: int) -> None:
    try:
        async with memory._qdrant() as q:
            await q.post(f"/collections/{COLLECTION}/points/delete?wait=true", json={"points": [_point_id(company_id, entry_id)]})
    except httpx.HTTPError:
        pass


def search_filter(company_id: str) -> dict:
    """The Qdrant filter every company search carries. Pure; unit-tested."""
    return {"must": [{"key": "company_id", "match": {"value": _check_id(company_id)}}]}


async def search(company_id: str, query: str, limit: int = 5) -> list[dict]:
    """Company Vault entries of THIS company by meaning; rows are re-read under the company's RLS scope."""
    await get(company_id)
    [vector] = await memory.embed([query])
    async with memory._qdrant() as q:
        await _ensure_collection(q)
        r = await q.post(f"/collections/{COLLECTION}/points/search",
                         json={"vector": vector, "limit": limit, "with_payload": True, "filter": search_filter(company_id)})
        r.raise_for_status()
        hits = r.json()["result"]
    ids = [h["payload"]["entry_id"] for h in hits if h.get("payload", {}).get("company_id") == company_id]
    if not ids:
        return []
    async with scope(company_id) as conn:
        rows = {r["id"]: dict(r) for r in await conn.fetch(
            "SELECT * FROM company_vault WHERE id = ANY($1::bigint[]) AND company_id = $2", ids, company_id)}
    score = {h["payload"]["entry_id"]: h["score"] for h in hits}
    return [rows[i] | {"score": round(score[i], 3)} for i in ids if i in rows]
