"""Which lane a task takes: ringan, Hermes or OpenJarvis (ADR-081).

  ringan      a simple look-up (news, a price, a fact, a schedule): search + a small, cheap cloud model, in seconds, without a
              Hermes session and WITHOUT waiting for a worker slot. When it finds nothing, Hermes does the task as usual.
  hermes      everything else — the default worker with all of JARVIS' tools (browser, memory, documents, n8n …).
  openjarvis  a task the main agent marked heavy (a lot of thinking, computing, reading code) while the owner has OpenJarvis on.

The choice is made when the task is created, from what the task is AND from the load right now: a heavy task goes to Hermes when
OpenJarvis is not answering or is already busy with two and Hermes has a free slot; a task that has to queue says so. The reason is kept in
`tasks.runtime_note` and the load is shown on the desk's worker card. Pure rules (`choose`) are unit-tested; `load` / `light_enabled` read the world.
"""

from . import db, openjarvis, quick
from .config import settings

LANES = ("ringan", "hermes", "openjarvis")
LIGHT_SETTING = "worker:ringan"
OJ_SLOTS = 2             # OpenJarvis is one small container: beyond this many heavy tasks at once, Hermes takes the next if it has room


def choose(*, kind: str, category: str, instruction: str, image, private: bool, company_id, heavy: bool,
           light_on: bool, oj_on: bool, oj_ok: bool, load: dict, hint: dict | None = None) -> tuple[str, str]:
    """(lane, why) for a new task. Pure; unit-tested. Only the owner's ordinary tasks are ever moved off Hermes: no private ones, none with a
    picture, none for a company (they need Hermes' tools, isolation and rules)."""
    if kind not in ("owner", "feature") or private or image or company_id:
        return "hermes", ""
    free_slots = load["slots"] - load["hermes_running"]
    hint = hint or {}
    avoid, prefer = hint.get("avoid") or set(), hint.get("prefer")
    if heavy and oj_on and "openjarvis" in avoid:   # Hermes has seen this kind of work fail in OpenJarvis
        return "hermes", "pola serupa pernah gagal di OpenJarvis — Hermes mengerjakannya"
    if heavy and oj_on:
        if not oj_ok:
            return "hermes", "OpenJarvis tidak menjawab saat ini — Hermes mengerjakan tugas berat ini"
        if load["openjarvis_running"] >= OJ_SLOTS and free_slots > 0:
            return "hermes", f"OpenJarvis sedang penuh ({load['openjarvis_running']} tugas berat) — Hermes mengerjakannya"
        return "openjarvis", "tugas berat" + (f" (antre: {load['openjarvis_running']} berjalan)" if load["openjarvis_running"] >= OJ_SLOTS else "")
    if prefer == "openjarvis" and oj_ok and not heavy and oj_on and "openjarvis" not in avoid and load["openjarvis_running"] < OJ_SLOTS:
        return "openjarvis", "pola serupa berhasil di OpenJarvis"
    if light_on and not heavy and category == "web" and "ringan" not in avoid and (quick.suitable(instruction) or prefer == "ringan"):
        return "ringan", "pencarian sederhana" if quick.suitable(instruction) else "pola serupa berhasil di jalur ringan"
    if free_slots <= 0:
        return "hermes", f"antre: semua {load['slots']} slot Hermes terpakai"
    return "hermes", ""


async def load() -> dict:
    """What the lanes are doing right now."""
    rows = await db.pool().fetch("SELECT runtime, status, count(*) AS n FROM tasks WHERE status IN ('queued', 'running') GROUP BY 1, 2")
    n = {(r["runtime"], r["status"]): r["n"] for r in rows}
    return {"slots": settings.worker_concurrency,
            "hermes_running": n.get(("hermes", "running"), 0), "hermes_queued": n.get(("hermes", "queued"), 0),
            "openjarvis_running": n.get(("openjarvis", "running"), 0), "openjarvis_queued": n.get(("openjarvis", "queued"), 0),
            "light_running": n.get(("ringan", "running"), 0) + n.get(("ringan", "queued"), 0)}


async def light_enabled() -> bool:
    """The owner can switch the light lane off (setting worker:ringan = false); on by default."""
    v = await db.pool().fetchval("SELECT value FROM settings_kv WHERE key = $1", LIGHT_SETTING)
    return v is not False


async def set_light(on: bool) -> bool:
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ($1, $2::jsonb) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        LIGHT_SETTING, bool(on))
    return on


_oj = {"at": 0.0, "ok": True}


async def _oj_ok() -> bool:
    """Is OpenJarvis answering? (a health call at most every 20 s — every owner task asks)"""
    import time
    if time.monotonic() - _oj["at"] > 20:
        _oj.update(at=time.monotonic(), ok=await openjarvis.healthy())
    return _oj["ok"]


async def advice(instruction: str) -> dict:
    """What Hermes has learned from similar earlier tasks (ADR-074 episodes) about where this kind of work goes."""
    from . import episodes
    try:
        return episodes.lane_hint(await episodes.similar(instruction.split(quick.CONTEXT_MARK)[0], limit=3))
    except Exception:   # no embeddings or no history: the plain rules decide
        return {"prefer": None, "avoid": set()}


async def pick(*, kind: str, category: str, instruction: str, image, private: bool, company_id, heavy: bool) -> tuple[str, str]:
    """`choose` with the world filled in — and Hermes' memory of similar work."""
    oj_on = await openjarvis.enabled()
    return choose(kind=kind, category=category, instruction=instruction, image=image, private=private, company_id=company_id, heavy=heavy,
                  light_on=await light_enabled(), oj_on=oj_on, oj_ok=(await _oj_ok()) if oj_on else True, load=await load(),
                  hint=await advice(instruction) if kind in ("owner", "feature") and not (private or image or company_id) else None)


async def view() -> dict:
    """For the desk's worker card: the load of each lane and whether the light lane is on."""
    ld = await load()
    return {**ld, "light_on": await light_enabled(), "openjarvis_on": await openjarvis.enabled()}
