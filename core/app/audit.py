"""Append-only audit trail for proposals, approvals, executions, and sensitive actions."""

from typing import Any

from . import db


async def record(actor: str, action: str, target: str | None = None, **detail: Any) -> None:
    await db.pool().execute(
        "INSERT INTO audit_events (actor, action, target, detail) VALUES ($1, $2, $3, $4)",
        actor, action, target, detail)


async def recent(limit: int = 100) -> list[dict]:
    rows = await db.pool().fetch(
        "SELECT id, at, actor, action, target, detail FROM audit_events ORDER BY id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]
