"""Errors raised inside JARVIS' own services, kept for diagnosis (error_log): the owner sees them in the
console, and the daily self-check reads them to find recurring problems. Secrets are never logged here:
messages go through the same redaction as chat logs."""

import asyncio
import hashlib
import logging
import re
import traceback

from . import db, sensitive

_queue: asyncio.Queue | None = None
_source = "core"


class _Handler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR or _queue is None or record.name.startswith("asyncpg"):
            return
        try:
            message = record.getMessage()
            tb = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else ""
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(_queue.put_nowait, (record.name, message, tb))
        except RuntimeError:
            pass  # no running loop (startup/shutdown): skip


def _clean(text: str) -> str:
    """Strip anything token-shaped (API keys, device tokens, bearer headers) before storing."""
    if sensitive.scan(text):
        text = re.sub(r"(password|passwd|pwd|kata ?sandi|pin|token|secret|api[_ -]?key)\s*[:=]\s*\S+", r"\1=…", text, flags=re.I)
    return re.sub(r"(sk-[A-Za-z0-9_-]{8})[A-Za-z0-9_-]+|(jdv_[A-Za-z0-9_-]{4})[A-Za-z0-9_-]+|(Bearer )\S+",
                  lambda m: (m.group(1) or m.group(2) or m.group(3)) + "…", text)


def signature(logger: str, message: str, tb: str) -> str:
    """Same error, same signature: logger + exception type + last frame location (no values)."""
    last = re.findall(r'File "([^"]+)", line (\d+)', tb)[-1:] if tb else []
    exc = tb.strip().splitlines()[-1].split(":")[0] if tb else re.sub(r"\d+", "N", message)[:80]
    return hashlib.sha1(f"{logger}|{exc}|{last}".encode()).hexdigest()[:16]


async def _writer() -> None:
    while True:
        logger, message, tb = await _queue.get()
        try:
            await db.pool().execute(
                "INSERT INTO error_log (source, logger, message, traceback, signature) VALUES ($1, $2, $3, $4, $5)",
                _source, logger[:100], _clean(message)[:2000], _clean(tb)[-6000:] or None, signature(logger, message, tb))
            await db.pool().execute("DELETE FROM error_log WHERE at < now() - interval '30 days'")
        except Exception:
            pass


def install(source: str) -> asyncio.Task:
    global _queue, _source
    _source = source
    _queue = asyncio.Queue(maxsize=1000)
    logging.getLogger().addHandler(_Handler())
    return asyncio.get_running_loop().create_task(_writer())


async def recent(limit: int = 50) -> list[dict]:
    rows = await db.pool().fetch(
        """SELECT signature, max(at) AS last_at, count(*) AS n, min(source) AS source, min(logger) AS logger,
                  (array_agg(message ORDER BY id DESC))[1] AS message, (array_agg(left(traceback, 1500) ORDER BY id DESC))[1] AS traceback
           FROM error_log WHERE at > now() - interval '7 days' GROUP BY signature ORDER BY max(at) DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]
