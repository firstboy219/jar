"""Long-term memory: Postgres is the source of truth, Qdrant is the semantic index.

Embeddings are computed locally on CPU (fastembed, multilingual MiniLM, 384-d), so memory text is
never sent to a cloud provider just to be indexed.
"""

import asyncio
import os
import uuid
from functools import lru_cache

import httpx

from . import audit, db, sensitive
from .config import settings

CATEGORIES = ("personal", "project", "knowledge", "experience", "operational")
KINDS = ("fact", "assumption", "preference")
DEFAULT_CONFIDENCE = {"fact": 0.7, "assumption": 0.4, "preference": 0.8}  # how far a statement of that kind is trusted
DUP_SCORE = 0.95       # near-identical text is merged instead of stored twice
UNUSED_ASSUMPTION_DAYS = 60
STALE_KEPT_DAYS = 90   # a superseded memory is kept this long (corrections are reversible), then deleted


class MemoryError_(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(settings.embed_model, cache_dir=os.getenv("FASTEMBED_CACHE_PATH"))


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _embedder().embed(texts)]


async def embed(texts: list[str]) -> list[list[float]]:
    return await asyncio.to_thread(_embed_sync, texts)


def _qdrant() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.qdrant_url, timeout=15,
                             headers={"api-key": settings.qdrant_api_key})


async def ensure_collection() -> None:
    dim = len((await embed(["dimensi"]))[0])
    async with _qdrant() as q:
        r = await q.get(f"/collections/{settings.memory_collection}")
        if r.status_code == 404:
            r = await q.put(f"/collections/{settings.memory_collection}",
                            json={"vectors": {"size": dim, "distance": "Cosine"}})
            r.raise_for_status()


async def _index(mem_id: str, text: str, category: str, stale: bool) -> None:
    [vector] = await embed([text])
    async with _qdrant() as q:
        r = await q.put(f"/collections/{settings.memory_collection}/points?wait=true", json={"points": [
            {"id": mem_id, "vector": vector, "payload": {"category": category, "stale": stale}}]})
        r.raise_for_status()


def rank_of(m: dict) -> float:
    """Search order: the match first, then what is verified and trusted a little higher. Pure; unit-tested."""
    return m["score"] + (0.05 if m.get("verified") else 0.0) + 0.04 * (float(m.get("confidence", 0.7)) - 0.5)


def label(m: dict) -> str:
    """How a memory reads inside a prompt: assumptions and unverified inferences say so. Pure."""
    note = {"assumption": "asumsi, belum tentu benar", "preference": "preferensi"}.get(m.get("kind"), "")
    if m.get("kind") == "fact" and not m.get("verified") and float(m.get("confidence", 0.7)) < 0.6:
        note = "belum terverifikasi"
    return f"{m['text']}" + (f" ({note})" if note else "")


async def _near_duplicate(text: str) -> dict | None:
    """The existing (live) memory this text repeats almost word for word, if any."""
    try:
        [vector] = await embed([text])
        async with _qdrant() as q:
            r = await q.post(f"/collections/{settings.memory_collection}/points/search", json={
                "vector": vector, "limit": 1, "with_payload": False,
                "filter": {"must": [{"key": "stale", "match": {"value": False}}]}})
            r.raise_for_status()
            hits = r.json()["result"]
    except (httpx.HTTPError, ValueError):
        return None
    if hits and hits[0]["score"] >= DUP_SCORE:
        return await get(str(hits[0]["id"]))
    return None


async def save(text: str, category: str, source: str, kind: str = "fact", *, confidence: float | None = None,
               verified: bool = False, evidence: str | None = None) -> dict:
    text = text.strip()
    if not text:
        raise MemoryError_("teks memori kosong")
    if category not in CATEGORIES:
        raise MemoryError_(f"kategori harus salah satu dari {', '.join(CATEGORIES)}")
    if kind not in KINDS:
        raise MemoryError_(f"jenis harus salah satu dari {', '.join(KINDS)}")
    if found := sensitive.scan(text):
        raise MemoryError_(f"tidak disimpan: terdeteksi data sensitif ({', '.join(found)})")
    conf = DEFAULT_CONFIDENCE[kind] if confidence is None else max(0.0, min(1.0, float(confidence)))
    if dup := await _near_duplicate(text):  # the same thing again: keep one, with the stronger provenance
        row = await db.pool().fetchrow(
            """UPDATE memories SET confidence = greatest(confidence, $2), verified = verified OR $3,
                      evidence = coalesce($4, evidence), updated_at = now(),
                      text = CASE WHEN length($5) > length(text) * 1.2 THEN $5 ELSE text END WHERE id = $1 RETURNING *""",
            dup["id"], conf, verified, evidence, text)
        if row["text"] != dup["text"]:
            await _index(str(row["id"]), row["text"], row["category"], False)
        return dict(row) | {"deduped": True}
    row = await db.pool().fetchrow(
        """INSERT INTO memories (text, category, kind, source, confidence, verified, evidence)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""", text, category, kind, source, conf, verified, evidence)
    await _index(str(row["id"]), text, category, False)
    await audit.record(source, "memory.saved", f"memory:{row['id']}", category=category)
    _touch([row["id"]], "write", [row["text"]])
    return dict(row)


async def update(mem_id: str, actor: str, text: str | None = None, category: str | None = None,
                 kind: str | None = None, stale: bool | None = None) -> dict:
    current = await get(mem_id)
    if current is None:
        raise MemoryError_("memori tidak ditemukan")
    new = {"text": text if text is not None else current["text"],
           "category": category or current["category"],
           "kind": kind or current["kind"],
           "stale": current["stale"] if stale is None else stale}
    if new["category"] not in CATEGORIES or new["kind"] not in KINDS:
        raise MemoryError_("kategori/jenis tidak valid")
    if found := sensitive.scan(new["text"]):
        raise MemoryError_(f"tidak disimpan: terdeteksi data sensitif ({', '.join(found)})")
    row = await db.pool().fetchrow(
        """UPDATE memories SET text = $2, category = $3, kind = $4, stale = $5, updated_at = now()
           WHERE id = $1 RETURNING *""",
        uuid.UUID(mem_id), new["text"], new["category"], new["kind"], new["stale"])
    await _index(mem_id, new["text"], new["category"], new["stale"])
    await audit.record(actor, "memory.updated", f"memory:{mem_id}")
    return dict(row)


async def correct(mem_id: str, new_text: str, actor: str, *, evidence: str | None = None, verified: bool = True) -> dict:
    """The owner (or Hermes, with a source) says a memory is wrong: the corrected one is saved and the old one is marked
    stale, pointing at its replacement — kept for a while, so a correction can itself be undone."""
    old = await get(mem_id)
    if old is None:
        raise MemoryError_("memori tidak ditemukan")
    new = await save(new_text, old["category"], actor, "fact", confidence=0.9, verified=verified,
                     evidence=evidence or f"koreksi dari: {old['text'][:120]}")
    if str(new["id"]) != mem_id:
        await db.pool().execute("UPDATE memories SET stale = true, superseded_by = $2, updated_at = now() WHERE id = $1",
                                old["id"], new["id"])
        await _index(mem_id, old["text"], old["category"], True)
    await audit.record(actor, "memory.corrected", f"memory:{mem_id}", replaced_by=str(new["id"]))
    return {"old": old, "new": new}


async def best_match(query: str, min_score: float = 0.5) -> dict | None:
    hits = await search(query, limit=1)
    return hits[0] if hits and hits[0]["score"] >= min_score else None


async def delete(mem_id: str, actor: str) -> bool:
    result = await db.pool().execute("DELETE FROM memories WHERE id = $1", uuid.UUID(mem_id))
    async with _qdrant() as q:
        await q.post(f"/collections/{settings.memory_collection}/points/delete?wait=true",
                     json={"points": [mem_id]})
    deleted = result.endswith("1")
    if deleted:
        await audit.record(actor, "memory.deleted", f"memory:{mem_id}")
    return deleted


async def get(mem_id: str) -> dict | None:
    try:
        key = uuid.UUID(mem_id)
    except ValueError:
        return None
    row = await db.pool().fetchrow("SELECT * FROM memories WHERE id = $1", key)
    return dict(row) if row else None


async def list_(category: str | None = None, limit: int = 200) -> list[dict]:
    if category:
        rows = await db.pool().fetch(
            "SELECT * FROM memories WHERE category = $1 ORDER BY updated_at DESC LIMIT $2", category, limit)
    else:
        rows = await db.pool().fetch("SELECT * FROM memories ORDER BY updated_at DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


# Memories touched recently (read or written) — the 3D brain lights them up.
_recent: list[tuple[str, str]] = []


def _touch(ids: list[str], kind: str, texts: list[str] | None = None) -> None:
    for i in ids:
        _recent.append((str(i), kind))
    del _recent[:-60]
    try:
        from . import hub
        if hub.online() and ids:
            # labels: the phone lists WHICH memories were just used next to the 3D brain
            labels = [" ".join(str(t).split())[:80] for t in (texts or [])][:12]
            asyncio.get_running_loop().create_task(
                hub.broadcast({"type": "brain_pulse", "ids": [str(i) for i in ids][:12], "kind": kind, "labels": labels}))
    except RuntimeError:
        pass


def recently_touched() -> list[str]:
    return list(dict.fromkeys(i for i, _ in reversed(_recent)))[:20]


async def search(query: str, limit: int = 5, include_stale: bool = False) -> list[dict]:
    [vector] = await embed([query])
    body = {"vector": vector, "limit": limit, "with_payload": False}
    if not include_stale:
        body["filter"] = {"must": [{"key": "stale", "match": {"value": False}}]}
    async with _qdrant() as q:
        r = await q.post(f"/collections/{settings.memory_collection}/points/search", json=body)
        r.raise_for_status()
        hits = r.json()["result"]
    if not hits:
        return []
    scores = {h["id"]: h["score"] for h in hits}
    rows = await db.pool().fetch("SELECT * FROM memories WHERE id = ANY($1::uuid[])", list(scores))
    found = sorted([dict(r) | {"score": round(scores[str(r["id"])], 3)} for r in rows], key=rank_of, reverse=True)
    used = [m for m in found if m["score"] >= 0.35]
    if used:
        await db.pool().execute("UPDATE memories SET last_used = now() WHERE id = ANY($1::uuid[])", [m["id"] for m in used])
    _touch([m["id"] for m in used], "read", [m["text"] for m in used])
    return found


async def context_event(query: str) -> dict:
    """What an agent is looking at: re-run its memory query locally (CPU embeddings, cheap) for the UI."""
    try:
        hits = await search(query, limit=4)
    except Exception:
        hits = []
    return {"type": "context", "source": "memory", "query": query,
            "items": [{"text": m["text"][:240], "category": m["category"], "score": m["score"]} for m in hits]}


# ---------- upkeep ----------

def cosine(a: list[float], b: list[float]) -> float:
    import math
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def duplicate_pairs(texts: list[str], vectors: list[list[float]], threshold: float = DUP_SCORE) -> list[tuple[int, int]]:
    """(keep, drop) index pairs among near-identical texts: the earlier index (the stronger memory) is kept. Pure."""
    dropped: set[int] = set()
    pairs = []
    for i in range(len(vectors)):
        if i in dropped:
            continue
        for j in range(i + 1, len(vectors)):
            if j not in dropped and cosine(vectors[i], vectors[j]) >= threshold:
                pairs.append((i, j))
                dropped.add(j)
    return pairs


async def maintain() -> dict:
    """Nightly: merge near-duplicates, retire assumptions nobody ever used, delete corrections' old versions after a
    while. Nothing the owner verified or stated as a preference is ever retired automatically (blueprint §8)."""
    live = await db.pool().fetch(
        "SELECT * FROM memories WHERE NOT stale ORDER BY verified DESC, confidence DESC, created_at ASC")
    merged = 0
    if len(live) > 1:
        vectors = await embed([r["text"] for r in live])
        for keep, drop in duplicate_pairs([r["text"] for r in live], vectors):
            if live[drop]["verified"] and not live[keep]["verified"]:
                continue
            await db.pool().execute("UPDATE memories SET stale = true, superseded_by = $2, updated_at = now() WHERE id = $1",
                                    live[drop]["id"], live[keep]["id"])
            await _index(str(live[drop]["id"]), live[drop]["text"], live[drop]["category"], True)
            merged += 1
    retired = (await db.pool().execute(
        """UPDATE memories SET stale = true, updated_at = now()
           WHERE kind = 'assumption' AND NOT verified AND NOT stale AND last_used IS NULL
             AND created_at < now() - make_interval(days => $1)""", UNUSED_ASSUMPTION_DAYS))
    old = await db.pool().fetch(
        """SELECT id FROM memories WHERE stale AND superseded_by IS NOT NULL AND NOT verified
             AND updated_at < now() - make_interval(days => $1)""", STALE_KEPT_DAYS)
    if old:
        ids = [str(r["id"]) for r in old]
        await db.pool().execute("DELETE FROM memories WHERE id = ANY($1::uuid[])", [r["id"] for r in old])
        async with _qdrant() as q:
            await q.post(f"/collections/{settings.memory_collection}/points/delete?wait=true", json={"points": ids})
    await audit.record("jarvis-core", "memory.maintained", None, merged=merged, deleted=len(old))
    return {"merged": merged, "assumptions_retired": int(retired.split()[-1]), "deleted": len(old)}
