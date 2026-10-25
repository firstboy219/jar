"""Action Approval Queue (FS-105): proposals wait for the owner; approved ones run their executor once."""

from collections.abc import Awaitable, Callable
from typing import Any

from . import audit, db, n8n

TERMINAL = {"rejected", "completed", "failed", "cancelled", "expired"}
# Changes to JARVIS' own code may only be APPROVED at the admin page (Blueprint v4 §3.3, ADR-047): the app is now
# something JARVIS may change itself, so its buttons cannot be the control point. Rejecting is allowed anywhere.
ADMIN_ONLY = {"code_change", "code_design", "skill_publish"}
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


async def _exec_hermes_command(detail: dict) -> dict:
    # The worker that received Hermes' approval.request watches this row and answers Hermes itself.
    return {"note": "diteruskan ke Hermes", "run_id": detail.get("run_id")}


async def _exec_code_change(detail: dict) -> dict:
    from . import dev
    return await dev.on_approved(detail)


async def _exec_task_budget(detail: dict) -> dict:
    await db.pool().execute(
        "UPDATE tasks SET budget_usd = coalesce(budget_usd, 0) + $2, phase = 'executing' WHERE id = $1",
        int(detail["task_id"]), float(detail["add_usd"]))
    return {"task": detail["task_id"], "added_usd": detail["add_usd"]}


async def _exec_skill_publish(detail: dict) -> dict:
    from . import reports, skills_pipeline
    done = await skills_pipeline.publish(int(detail["draft_id"]), "owner-approval")
    await reports._create(None, "system", f"Skill baru '{done['name']}' (v{done['version']}) sudah terbit setelah kamu setujui. "
                          "Bisa dibatalkan di Lainnya → Skills & Belajar.")
    return done


async def _exec_code_design(detail: dict) -> dict:
    from . import dev
    return await dev.on_design_approved(detail)


async def _exec_company_directive(detail: dict) -> dict:
    from . import gm
    return await gm.on_owner_approved(detail)


async def _exec_company_action(detail: dict) -> dict:
    from . import gm
    return await gm.on_result_decision(detail)


EXECUTORS: dict[str, Executor] = {
    "company_directive": _exec_company_directive,
    "company_action": _exec_company_action,
    "code_design": _exec_code_design,
    "skill_publish": _exec_skill_publish,
    "task_budget": _exec_task_budget,
    "manual": _exec_manual,
    "code_change": _exec_code_change,
    "hermes_command": _exec_hermes_command,
    "n8n_activate_workflow": _exec_n8n_activate,
    "setting_change": _exec_setting_change,
}


class ApprovalError(RuntimeError):
    pass


class AdminOnly(ApprovalError):
    """This kind may only be approved at the admin page (HTTP 403)."""


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


async def decide(approval_id: int, approve: bool, actor: str, channel: str = "device") -> dict:
    """Approve (and execute) or reject. Row lock makes double-clicks / concurrent decisions safe.
    channel: "admin" only for the admin page itself; everything else (app console, chat, voice) is "device"."""
    await expire_old()
    async with db.pool().acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT * FROM approvals WHERE id = $1 FOR UPDATE", approval_id)
            if row is None:
                raise ApprovalError(f"persetujuan #{approval_id} tidak ditemukan")
            if row["status"] != "awaiting_approval":
                raise ApprovalError(f"persetujuan #{approval_id} sudah berstatus {row['status']}")
            if approve and row["kind"] in ADMIN_ONLY and channel != "admin":
                raise AdminOnly(f"persetujuan #{approval_id} ({row['kind']}) hanya bisa disetujui di halaman admin "
                                "(jar1.cosger.online) — perubahan kode JARVIS tidak bisa disetujui dari aplikasi")
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
