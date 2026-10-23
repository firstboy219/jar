"""Capability Registry (Blueprint v2 §7, ADR-040): what JARVIS can do, found by meaning, with how well it has worked.

Filled automatically — never from a hand-kept list that needs a code change per new skill:
  skills   every SKILL.md under Hermes' skills folder (JARVIS' own and the ones Hermes wrote itself)
  tools    the main agent's tool schemas (assistant.TOOLS)
  workers  the built-in workers (quick research, drafts, meetings, documents)
`search()` finds capabilities by meaning (the local embedding model) and keywords; `brief_for()` puts the relevant ones,
with their track record, in front of a worker; `record()` keeps the score after each verified task.
"""

import hashlib
import json
import logging
import math
import re
from pathlib import Path

from . import db, memory

log = logging.getLogger("jarvis-core.capabilities")
SKILLS_ROOT = Path("/hermes/skills")
MIN_SCORE = 0.38     # below this one of JARVIS' own capabilities is not "relevant"
MIN_SCORE_FOREIGN = 0.65  # third-party skills that came with Hermes must match clearly (0.61 once matched "putar lagu" to claude-api)
OWN_BONUS = 0.12
WORKERS = {  # the built-in workers: stable pieces of JARVIS itself, described once
    "quick": ("Pencarian cepat", "Cari berita atau fakta singkat di web (Google News, DuckDuckGo) dalam hitungan detik.", "web"),
    "writer": ("Penulis draf", "Menulis draf email, balasan, surat atau pesan dari permintaan, lampiran dan obrolan; hasil bisa disalin dan diunduh sebagai .docx.", "balas-pesan"),
    "meetings": ("Notulen rapat", "Merekam rapat, menyalin ucapan, memisahkan pembicara, menyusun ringkasan, keputusan dan action item.", "rapat"),
    "documents": ("Pembuat dokumen", "Membuat dokumen Word, Excel atau PDF dari konten yang disusun.", "produktivitas"),
}
_vectors: dict[str, tuple[str, list[float]]] = {}


# ---------- pure ----------

def parse_skill(text: str) -> dict | None:
    """name / description / version from a SKILL.md front matter; None when it has none. Pure; unit-tested."""
    m = re.match(r"---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    fields = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            fields[k.strip()] = v.strip().strip('"').strip("'")
    if not fields.get("name"):
        return None
    ver = re.match(r"\d+", fields.get("version", "1"))
    return {"name": fields["name"], "description": fields.get("description", ""), "version": int(ver.group(0)) if ver else 1}


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def rate(success: int, fail: int) -> float | None:
    return round(100 * success / (success + fail), 1) if success + fail else None


def track_record(row: dict) -> str:
    """"teruji, berhasil 8 dari 9" / "belum pernah dipakai" — the honest line a worker sees. Pure."""
    n = row["success_n"] + row["fail_n"]
    state = "teruji" if row["tested"] else "belum teruji"
    return f"{state}, berhasil {row['success_n']} dari {n}" if n else f"{state}, belum pernah dipakai"


def format_brief(found: list[dict]) -> str:
    """The worker's "kemampuan yang sudah ada" paragraph. Pure; unit-tested."""
    if not found:
        return ""
    lines = [f"- {c['id']} — {c['description'][:140]} ({track_record(c)})" for c in found]
    return ("KEMAMPUAN YANG SUDAH ADA (pakai dulu sebelum meriset ulang; skill dibuka dengan skill_view):\n" + "\n".join(lines) + "\n\n")


# ---------- catalog ----------

async def _upsert(cap_id: str, kind: str, name: str, description: str, *, category: str | None = None,
                  version: int = 1, content: str | None = None, own: bool = True) -> None:
    digest = hashlib.sha256((description + (content or "")).encode()).hexdigest()[:16]
    row = await db.pool().fetchrow("SELECT version, content_hash FROM capabilities WHERE id = $1", cap_id)
    if row is None:
        await db.pool().execute(
            """INSERT INTO capabilities (id, kind, name, description, category, version, content_hash)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""", cap_id, kind, name, description[:500], category, version, digest)
    elif row["content_hash"] != digest:  # the skill changed: a new version (the old text stays in capability_versions)
        version = max(version, row["version"] + 1)
        await db.pool().execute(
            """UPDATE capabilities SET name = $2, description = $3, category = coalesce($4, category), version = $5,
                      content_hash = $6, tested = false, updated_at = now() WHERE id = $1""",
            cap_id, name, description[:500], category, version, digest)
    else:
        await db.pool().execute("UPDATE capabilities SET own = $2 WHERE id = $1 AND own IS DISTINCT FROM $2", cap_id, own)
        return
    await db.pool().execute("UPDATE capabilities SET own = $2 WHERE id = $1", cap_id, own)
    if content is not None:
        await db.pool().execute(
            """INSERT INTO capability_versions (capability_id, version, content, changelog) VALUES ($1, $2, $3, $4)
               ON CONFLICT DO NOTHING""", cap_id, version, content[:60_000], "diimpor otomatis dari berkas skill")
    _vectors.pop(cap_id, None)


async def sync(tools: list[dict] | None = None, root: Path = SKILLS_ROOT) -> dict:
    """Read every skill on disk, the tool schemas and the built-in workers into the registry. Idempotent."""
    skills = 0
    if root.is_dir():
        for f in sorted(root.glob("**/SKILL.md")):
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            meta = parse_skill(text)
            if meta and "bundled" not in f.parts:
                await _upsert(f"skill:{meta['name']}", "skill", meta["name"], meta["description"], version=meta["version"], content=text,
                              own=any(part.startswith("jarvis") for part in f.parts))  # skills/jarvis (ours) and skills/jarvis-learned (Sprint 4)
                skills += 1
    for t in tools or []:
        fn = t.get("function") or {}
        if fn.get("name"):
            await _upsert(f"tool:{fn['name']}", "tool", fn["name"], fn.get("description", ""))
    for key, (name, description, category) in WORKERS.items():
        await _upsert(f"worker:{key}", "worker", name, description, category=category)
    return {"skills": skills, "total": await db.pool().fetchval("SELECT count(*) FROM capabilities")}


async def _vector(row: dict) -> list[float]:
    digest = row["content_hash"] or ""
    hit = _vectors.get(row["id"])
    if hit and hit[0] == digest:
        return hit[1]
    vec = (await memory.embed([f"{row['name']}. {row['description']}"]))[0]
    _vectors[row["id"]] = (digest, vec)
    return vec


async def search(query: str, limit: int = 5, kinds: tuple[str, ...] = ("skill", "worker", "tool")) -> list[dict]:
    """Capabilities relevant to `query`, best first (meaning + a small keyword bonus); deprecated ones are left out."""
    rows = [dict(r) for r in await db.pool().fetch(
        "SELECT * FROM capabilities WHERE status <> 'deprecated' AND kind = ANY($1)", list(kinds))]
    if not rows or not query.strip():
        return []
    qv = (await memory.embed([query]))[0]
    words = {w for w in re.findall(r"\w{4,}", query.lower())}
    scored = []
    for r in rows:
        s = cosine(qv, await _vector(r))
        if words & set(re.findall(r"\w{4,}", f"{r['name']} {r['description']}".lower())):
            s += 0.08
        if r["own"]:
            s += OWN_BONUS
        if s >= (MIN_SCORE if r["own"] else MIN_SCORE_FOREIGN):
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    return [{**r, "score": round(s, 3), "success_pct": rate(r["success_n"], r["fail_n"])} for s, r in scored[:limit]]


async def brief_for(instruction: str) -> str:
    """For a worker about to start: the relevant skills/workers and how well they have worked (empty when none)."""
    try:
        return format_brief(await search(instruction, limit=3, kinds=("skill", "worker")))
    except Exception as e:  # the registry must never stop a task from starting
        log.warning("capability brief failed: %s", e)
        return ""


async def record(cap_id: str, ok: bool, cost_usd: float = 0.0, verified: bool = False) -> bool:
    """One use of a capability: success/failure, its cost; a verified success marks it tested."""
    done = await db.pool().execute(
        """UPDATE capabilities SET runs = runs + 1, success_n = success_n + $2, fail_n = fail_n + $3,
                  cost_usd = cost_usd + $4, tested = CASE WHEN $2 = 0 THEN false ELSE tested OR $5 END,  -- a failure: validate again
                  updated_at = now() WHERE id = $1""",
        cap_id, 1 if ok else 0, 0 if ok else 1, cost_usd, bool(ok and verified))
    return done.endswith(" 1")


async def listing(kind: str = "", query: str = "") -> list[dict]:
    if query.strip():
        return await search(query, limit=30, kinds=(kind,) if kind else ("skill", "worker", "tool"))
    rows = await db.pool().fetch(
        "SELECT * FROM capabilities WHERE ($1 = '' OR kind = $1) ORDER BY kind, runs DESC, name", kind)
    return [{**dict(r), "success_pct": rate(r["success_n"], r["fail_n"])} for r in rows]
