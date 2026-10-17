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


async def save(text: str, category: str, source: str, kind: str = "fact") -> dict:
    text = text.strip()
    if not text:
        raise MemoryError_("teks memori kosong")
    if category not in CATEGORIES:
        raise MemoryError_(f"kategori harus salah satu dari {', '.join(CATEGORIES)}")
    if kind not in KINDS:
        raise MemoryError_(f"jenis harus salah satu dari {', '.join(KINDS)}")
    if found := sensitive.scan(text):
        raise MemoryError_(f"tidak disimpan: terdeteksi data sensitif ({', '.join(found)})")
    row = await db.pool().fetchrow(
        "INSERT INTO memories (text, category, kind, source) VALUES ($1, $2, $3, $4) RETURNING *",
        text, category, kind, source)
    await _index(str(row["id"]), text, category, False)
    await audit.record(source, "memory.saved", f"memory:{row['id']}", category=category)
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
    found = [dict(r) | {"score": round(scores[str(r["id"])], 3)} for r in rows]
    return sorted(found, key=lambda m: m["score"], reverse=True)
