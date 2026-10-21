"""asyncpg pool + forward-only SQL migrations (app/migrations/NNN_*.sql, applied in order once)."""

import json
from pathlib import Path

import asyncpg

MIGRATIONS = Path(__file__).parent / "migrations"
_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def connect(dsn: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10, init=_init_conn)
    await migrate(_pool)
    return _pool


async def close() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    assert _pool is not None, "database not connected"
    return _pool


async def migrate(p: asyncpg.Pool) -> list[str]:
    applied = []
    async with p.acquire() as conn:
        # Serialize concurrent starters (jarvis-core and jarvis-tools share the database).
        await conn.execute("SELECT pg_advisory_lock(4242)")
        try:
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
            done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
            for f in sorted(MIGRATIONS.glob("*.sql")):
                if f.name in done:
                    continue
                async with conn.transaction():
                    await conn.execute(f.read_text())
                    await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", f.name)
                applied.append(f.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(4242)")
    return applied


READONLY_TABLES = ("messages", "tasks", "reports", "approvals", "memories", "audit_events", "llm_usage",
                   "notifications", "context_log", "improvements", "documents", "owner_questions",
                   "llm_categories", "llm_providers", "meetings", "error_log", "dev_changes")


async def grant_readonly(p: asyncpg.Pool) -> bool:
    """Hermes' db_query_ro connects as jarvis_ro (made by infra/postgres/init-core-db.sh): SELECT only,
    never device tokens or settings. Re-granted at every start, so new tables can join the list."""
    async with p.acquire() as conn:
        if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_ro'"):
            return False
        await conn.execute("GRANT USAGE ON SCHEMA public TO jarvis_ro")
        await conn.execute(f"GRANT SELECT ON {', '.join(READONLY_TABLES)} TO jarvis_ro")
    return True
