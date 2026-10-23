"""Goals and state (Blueprint v2 §8): what the owner wants done over time, apart from one-off tasks.
The few most important active goals are in front of the main agent every turn (assistant._situation)."""

from datetime import date

from . import audit, db

STATUSES = ("active", "paused", "done")


class GoalError(ValueError):
    pass


async def add(text: str, actor: str, priority: int = 3, due: date | None = None) -> dict:
    text = " ".join(text.split())
    if not text:
        raise GoalError("tujuan kosong")
    if not 1 <= priority <= 5:
        raise GoalError("prioritas 1 (terpenting) sampai 5")
    row = await db.pool().fetchrow(
        "INSERT INTO goals (text, priority, due, source) VALUES ($1, $2, $3, $4) RETURNING *", text[:300], priority, due, actor)
    await audit.record(actor, "goal.added", f"goal:{row['id']}")
    return dict(row)


async def update(goal_id: int, actor: str, *, status: str | None = None, priority: int | None = None,
                 due: date | None = None, text: str | None = None) -> dict:
    if status is not None and status not in STATUSES:
        raise GoalError(f"status: {', '.join(STATUSES)}")
    if priority is not None and not 1 <= priority <= 5:
        raise GoalError("prioritas 1 (terpenting) sampai 5")
    row = await db.pool().fetchrow(
        """UPDATE goals SET status = coalesce($2, status), priority = coalesce($3, priority), due = coalesce($4, due),
                  text = coalesce($5, text), updated_at = now() WHERE id = $1 RETURNING *""",
        goal_id, status, priority, due, " ".join(text.split())[:300] if text else None)
    if not row:
        raise GoalError("tujuan tidak ditemukan")
    await audit.record(actor, "goal.updated", f"goal:{goal_id}", status=row["status"])
    return dict(row)


async def list_(status: str = "active", limit: int = 30) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT * FROM goals WHERE ($1 = '' OR status = $1)
           ORDER BY (status <> 'active'), priority, due NULLS LAST, id LIMIT $2""", status, limit)
    return [dict(r) for r in rows]


def line(goal: dict, today: date | None = None) -> str:
    """One goal as the agent reads it. Pure; unit-tested."""
    today = today or date.today()
    due = ""
    if goal.get("due"):
        days = (goal["due"] - today).days
        due = f", tenggat {goal['due']:%d %b}" + (" (LEWAT)" if days < 0 else " (hari ini)" if days == 0 else f" ({days} hari lagi)")
    return f"#{goal['id']} [P{goal['priority']}] {goal['text']}{due}"


async def situation_block(limit: int = 3) -> str:
    goals = await list_("active", limit)
    return ("TUJUAN AKTIF PEMILIK:\n" + "\n".join("- " + line(g) for g in goals)) if goals else ""
