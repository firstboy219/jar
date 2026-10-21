"""Runtime setting overrides approved by the owner (self-improvement 'setting' proposals).

Stored in settings_kv as 'override:<key>' and applied onto the in-memory settings object, at startup
and right after approval. Reverting an improvement deletes the override (takes effect on restart).
"""

from . import db
from .config import settings

ATTRS = {"deepgram_model": str, "endpointing_ms": int, "utterance_end_ms": int, "quiet_hours": str}


async def load_all() -> dict:
    rows = await db.pool().fetch("SELECT key, value FROM settings_kv WHERE key LIKE 'override:%'")
    applied = {}
    for r in rows:
        key = r["key"].removeprefix("override:")
        if key in ATTRS:
            setattr(settings, key, ATTRS[key](r["value"]))
            applied[key] = r["value"]
    return applied


async def set_override(key: str, value: str) -> None:
    if key not in ATTRS:
        raise ValueError(f"setelan {key} tidak boleh diubah")
    await db.pool().execute(
        """INSERT INTO settings_kv (key, value) VALUES ($1, to_jsonb($2::text))
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", f"override:{key}", value)
    setattr(settings, key, ATTRS[key](value))
