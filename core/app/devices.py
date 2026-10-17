"""Device (APK) bearer tokens. Only a SHA-256 of each token is stored."""

import hashlib
import secrets

from . import audit, db


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create(name: str, actor: str) -> tuple[dict, str]:
    token = "jdv_" + secrets.token_urlsafe(32)
    row = await db.pool().fetchrow(
        "INSERT INTO devices (name, token_hash) VALUES ($1, $2) RETURNING id, name, created_at",
        name.strip()[:80] or "perangkat", _hash(token))
    await audit.record(actor, "device.created", f"device:{row['id']}", name=row["name"])
    return dict(row), token


async def authenticate(token: str | None) -> dict | None:
    if not token:
        return None
    row = await db.pool().fetchrow(
        """UPDATE devices SET last_seen_at = now()
           WHERE token_hash = $1 AND revoked_at IS NULL RETURNING id, name""", _hash(token))
    return dict(row) if row else None


async def list_() -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT id, name, created_at, last_seen_at, revoked_at FROM devices ORDER BY created_at DESC")
    return [dict(r) for r in rows]


async def revoke(device_id: str, actor: str) -> bool:
    result = await db.pool().execute(
        "UPDATE devices SET revoked_at = now() WHERE id = $1::uuid AND revoked_at IS NULL", device_id)
    if result.endswith("1"):
        await audit.record(actor, "device.revoked", f"device:{device_id}")
        return True
    return False
