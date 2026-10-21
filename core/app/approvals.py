"""Action Approval Queue (FS-105): proposals wait for the owner; approved ones run their executor once."""

from collections.abc import Awaitable, Callable
from typing import Any

from . import audit, db, n8n

TERMINAL = {"rejected", "completed", "failed", "cancelled", "expired"}
# allowed status transitions
TRANSITIONS = {
    "awaiting_approval": {"approved", "rejected", "cancelled", "expired"},
    "approved": {"executing"},
    "executing": {"completed", "failed"},
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, set())


Executor = Callable[[dict], Awaitable[dict]]


async def _exec_manual(detail: dict) -> dict:
    # Nothing to run: the approval itself is the outcome (Hermes polls get_approval).
    return {"note": "approved; no automatic action"}


async def _exec_n8n_activate(detail: dict) -> dict:
    return await n8n.activate(str(detail["workflow_id"]))


async def _exec_setting_change(detail: dict) -> dict:
    from . import overrides
    await overrides.set_override(detail["key"], str(detail["value"]))
    if detail.get("improvement_id"):
        await db.pool().execute("UPDATE improvements SET status = 'applied', applied_at = now() WHERE id = $1",
                                int(detail["improvement_id"]))
    return {"applied": {detail["key"]: detail["value"]}}


EXECUTORS: dict[str, Executor] = {
    "manual": _exec_manual,
    "n8n_activate_workflow": _exec_n8n_activate,
    "setting_change": _exec_setting_change,
}


class ApprovalError(RuntimeError):
    pass


async def create(kind: str, title: str, detail: dict[str, Any], requested_by: str,
                 risk: str = "medium", idempotency_key: str | None = None) -> dict:
    if kind not in EXECUTORS:
        raise ApprovalError(f"unknown approval kind: {kind}")
    row = await db.pool().fetchrow(
        """INSERT INTO approvals (kind, title, detail, risk, requested_by, idempotency_key)
           VALUES ($1, $2, $3, $4, $5, $6)
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING *""",
        kind, title, detail, risk, requested_by, idempotency_key)
    if row is None:  # duplicate request: return the original instead of queueing twice
        row = await db.pool().fetchrow("SELECT * FROM approvals WHERE idempotency_key = $1", idempotency_key)
        return dict(row)
    await audit.record(requested_by, "approval.requested", f"approval:{row['id']}", kind=kind, title=title)
    return dict(row)


async def expire_old() -> int:
    result = await db.pool().execute(
        "UPDATE approvals SET status = 'expired' WHERE status = 'awaiting_approval' AND expires_at < now()")
    return int(result.split()[-1])


async def get(approval_id: int) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM approvals WHERE id = $1", approval_id)
    return dict(row) if row else None


async def list_(status: str | None = None, limit: int = 50) -> list[dict]:
    await expire_old()
    if status:
        rows = await db.pool().fetch(
            "SELECT * FROM approvals WHERE status = $1 ORDER BY id DESC LIMIT $2", status, limit)
    else:
        rows = await db.pool().fetch("SELECT * FROM approvals ORDER BY id DESC LIMIT $1", limit)
    return [dict(r) for r in rows]


async def _set_status(conn, approval_id: int, current: str, new: str, **cols) -> None:
    if not can_transition(current, new):
        raise ApprovalError(f"tidak bisa mengubah status {current} → {new}")
    sets = ", ".join(f"{k} = ${i}" for i, k in enumerate(cols, start=3))
    sql = f"UPDATE approvals SET status = $2{', ' + sets if sets else ''} WHERE id = $1"
    await conn.execute(sql, approval_id, new, *cols.values())


async def decide(approval_id: int, approve: bool, actor: str) -> dict:
    """Approve (and execute) or reject. Row lock makes double-clicks / concurrent decisions safe."""
    await expire_old()
    async with db.pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT * FROM approvals WHERE id = $1 FOR UPDATE", approval_id)
            if row is None:
                raise ApprovalError(f"persetujuan #{approval_id} tidak ditemukan")
            if row["status"] != "awaiting_approval":
                raise ApprovalError(f"persetujuan #{approval_id} sudah berstatus {row['status']}")
            new = "approved" if approve else "rejected"
            await _set_status(conn, approval_id, row["status"], new, decided_by=actor)
            await conn.execute("UPDATE approvals SET decided_at = now() WHERE id = $1", approval_id)
            if approve:
                await _set_status(conn, approval_id, "approved", "executing")
    await audit.record(actor, f"approval.{new}", f"approval:{approval_id}", kind=row["kind"])
    if not approve:
        return await get(approval_id)

    try:
        result = await EXECUTORS[row["kind"]](row["detail"])
        status, error = "completed", None
    except Exception as e:  # executor failures are recorded, never raised to the approver as a 500
        result, status, error = None, "failed", str(e)[:1000]
    async with db.pool().acquire() as conn:
        await _set_status(conn, approval_id, "executing", status, result=result, error=error)
        await conn.execute("UPDATE approvals SET executed_at = now() WHERE id = $1", approval_id)
    await audit.record("jarvis-core", f"approval.{status}", f"approval:{approval_id}", error=error)
    return await get(approval_id)
