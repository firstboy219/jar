"""Hermes asks the owner (ask_owner): the question is spoken like a report, the main agent recognises
the owner's answer and relays it with answer_question, and the waiting worker continues.

A worker never blocks the conversation: it waits for the answer in its own run; the owner keeps
talking to the main agent as usual.
"""

from . import audit, db, reports


async def ask(question: str, task_id: int | None) -> dict:
    question = question.strip()[:1000]
    title = await db.pool().fetchval("SELECT title FROM tasks WHERE id = $1", task_id) if task_id else None
    row = await db.pool().fetchrow(
        "INSERT INTO owner_questions (task_id, question) VALUES ($1, $2) RETURNING *", task_id, question)
    spoken = f"Pertanyaan untuk tugas {title}: {question}" if title else f"Aku perlu tanya: {question}"
    r = await reports._create(task_id, "system", spoken)
    await db.pool().execute("UPDATE owner_questions SET report_id = $2 WHERE id = $1", row["id"], r["id"])
    await audit.record("hermes", "question.asked", f"question:{row['id']}", task_id=task_id)
    return dict(row) | {"report_id": r["id"]}


async def answer(question_id: int, text: str, actor: str) -> bool:
    row = await db.pool().fetchrow(
        """UPDATE owner_questions SET answer = $2, status = 'answered', answered_at = now()
           WHERE id = $1 AND status = 'open' RETURNING report_id""", question_id, text.strip()[:2000])
    if not row:
        return False
    if row["report_id"]:
        await reports.acknowledge([row["report_id"]], "voice")
    await audit.record(actor, "question.answered", f"question:{question_id}")
    return True


async def get(question_id: int) -> dict | None:
    row = await db.pool().fetchrow("SELECT * FROM owner_questions WHERE id = $1", question_id)
    return dict(row) if row else None


async def open_questions() -> list[dict]:
    await db.pool().execute(
        "UPDATE owner_questions SET status = 'expired' WHERE status = 'open' AND created_at < now() - interval '1 day'")
    rows = await db.pool().fetch(
        """SELECT q.id, q.question, q.task_id, t.title FROM owner_questions q LEFT JOIN tasks t ON t.id = q.task_id
           WHERE q.status = 'open' ORDER BY q.id""")
    return [dict(r) for r in rows]
