"""JARVIS' 3D "brain" for the phone's idle screen: memories as glowing nodes, related ones linked.

Layout is computed here, not on the phone: each memory's 384-d embedding (Qdrant) is projected to 3D
with PCA (deterministic signs, so the shape is stable between calls), then folded into two hemispheres
by the first component. Edges link each node to its nearest neighbours (cosine ≥ 0.55). Nodes the
agents touched recently are marked active; live `brain_pulse` events (memory.py) make them flash.
"""

import time

import numpy as np

from . import db, memory
from .config import settings

MAX_NODES = 150
_cache: dict = {"at": 0.0, "value": None}


async def _points(limit: int) -> list[dict]:
    async with memory._qdrant() as q:
        r = await q.post(f"/collections/{settings.memory_collection}/points/scroll",
                         json={"limit": limit, "with_vector": True, "with_payload": True,
                               "filter": {"must": [{"key": "stale", "match": {"value": False}}]}})
        r.raise_for_status()
    return r.json()["result"]["points"]


def layout(vectors: np.ndarray) -> np.ndarray:
    """N×384 → N×3 in roughly [-1, 1], two hemispheres along x. Pure; unit-tested."""
    n = len(vectors)
    if n == 0:
        return np.zeros((0, 3))
    if n < 4:
        return np.array([[(-1) ** i * 0.4, 0.0, 0.1 * i] for i in range(n)])
    x = vectors - vectors.mean(axis=0)
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    comps = vt[:3]
    for i in range(len(comps)):  # deterministic orientation: largest loading positive
        if comps[i][np.argmax(np.abs(comps[i]))] < 0:
            comps[i] = -comps[i]
    p = x @ comps.T
    if p.shape[1] < 3:
        p = np.hstack([p, np.zeros((n, 3 - p.shape[1]))])
    p = p / (np.abs(p).max(axis=0) + 1e-9)
    # brain shape: hemispheres split on x with a gap, ellipsoid proportions (wider front-back)
    p[:, 0] = np.sign(p[:, 0] + 1e-9) * (0.15 + 0.55 * np.abs(p[:, 0]))
    p[:, 1] *= 0.6
    p[:, 2] *= 0.85
    return p.round(4)


def edges(vectors: np.ndarray, k: int = 2, min_sim: float = 0.55) -> list[list[int]]:
    if len(vectors) < 2:
        return []
    v = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
    sim = v @ v.T
    np.fill_diagonal(sim, -1)
    out = set()
    for i in range(len(v)):
        for j in np.argsort(-sim[i])[:k]:
            if sim[i, j] >= min_sim:
                out.add((min(i, int(j)), max(i, int(j))))
    return sorted([list(e) for e in out])


async def graph(limit: int = MAX_NODES) -> dict:
    if _cache["value"] and time.monotonic() - _cache["at"] < 60:
        value = _cache["value"]
    else:
        pts = await _points(min(limit, MAX_NODES))
        ids = [str(p["id"]) for p in pts]
        rows = {str(r["id"]): r for r in await db.pool().fetch(
            "SELECT id, text, category, kind, updated_at FROM memories WHERE id = ANY($1::uuid[])", ids)}
        pts = [p for p in pts if str(p["id"]) in rows]
        vecs = np.array([p["vector"] for p in pts], dtype=np.float32) if pts else np.zeros((0, 384))
        pos = layout(vecs)
        nodes = [{"id": str(p["id"]), "x": float(pos[i][0]), "y": float(pos[i][1]), "z": float(pos[i][2]),
                  "category": rows[str(p["id"])]["category"], "kind": rows[str(p["id"])]["kind"],
                  "label": rows[str(p["id"])]["text"][:80]} for i, p in enumerate(pts)]
        value = {"nodes": nodes, "edges": edges(vecs), "total": await db.pool().fetchval("SELECT count(*) FROM memories")}
        _cache.update(at=time.monotonic(), value=value)
    active = set(memory.recently_touched())
    return {**value, "active": [n["id"] for n in value["nodes"] if n["id"] in active],
            "categories": {"personal": "#4FC3F7", "project": "#FFB74D", "knowledge": "#81C784",
                           "experience": "#BA68C8", "operational": "#E57373"}}


async def memory_card(mem_id: str) -> dict | None:
    m = await memory.get(mem_id)
    if not m:
        return None
    return {"id": str(m["id"]), "text": m["text"], "category": m["category"], "kind": m["kind"],
            "source": m["source"], "updated_at": m["updated_at"].isoformat()}
