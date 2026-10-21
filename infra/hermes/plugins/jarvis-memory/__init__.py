"""jarvis-memory — Hermes MemoryProvider backed by JARVIS' own long-term memory (ADR-018).

JARVIS keeps ONE memory: Postgres is the source of truth, Qdrant the semantic index, embeddings are
computed locally in jarvis-core (nothing leaves the server). The main agent, Hermes and the owner
(web admin / APK, where every memory can be edited or deleted) all see the same facts.

This provider:
  * prefetch: before each turn, recalls the memories most relevant to the request (core search, ~50 ms);
  * on_memory_write: mirrors what Hermes writes with its built-in memory tool (MEMORY.md / USER.md)
    into JARVIS' memory, so nothing Hermes learns stays in a second, unmanaged store;
  * no automatic per-turn extraction (that costs an LLM call per turn and pollutes memory); Hermes saves
    deliberately with its memory tool or the jarvis memory_save tool.
It also keeps Hermes' browser vault in sync with JARVIS' password manager: logins the owner marked
"boleh dipakai JARVIS" are added (and removed again) so `browser_vault fill` can sign in on the owner's
behalf — the password is resolved server-side at fill time and never reaches the model.
Talks to jarvis-core on the internal network with the MCP token (same trust as the jarvis MCP tools).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.request
from typing import Any, Optional

from agent.memory_provider import MemoryProvider, RecallStatus, is_trivial_prompt

logger = logging.getLogger(__name__)
CORE = os.getenv("JARVIS_CORE_URL", "http://jarvis-core:8000")
TIMEOUT = 4


def _get(path: str) -> Optional[dict]:
    req = urllib.request.Request(CORE + path, headers={"X-Internal-Token": os.getenv("MCP_TOKEN", "")})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.debug("jarvis-memory GET %s failed: %s", path, e)
        return None


_TAG = re.compile(r"^JARVIS .* \[([0-9a-f]{8})\]$")
_synced: dict[str, str] = {}   # entry id prefix -> fingerprint of (origin, username, password)
_sync_started = False


def sync_vault_once() -> None:
    """Make Hermes' vault hold exactly the owner-allowed JARVIS logins (others are left alone)."""
    data = _get("/internal/vault/agent")
    if data is None:
        return
    from agent.vault_store import get_vault_store
    store = get_vault_store()
    wanted = {e["id"][:8]: e for e in data.get("entries", [])}
    have: dict[str, list] = {}
    for meta in store.list_items():
        m = _TAG.match(meta.label or "")
        if m:
            have.setdefault(m.group(1), []).append(meta.id)
    for key, ids in have.items():
        e = wanted.get(key)
        fp = hashlib.sha256(json.dumps([e["origin"], e["username"], e["password"]]).encode()).hexdigest() if e else None
        if e is None or _synced.get(key) != fp:
            for item_id in ids:
                store.remove_item(item_id)
            _synced.pop(key, None)
    current = {m.group(1) for meta in store.list_items() if (m := _TAG.match(meta.label or ""))}
    for key, e in wanted.items():
        if key in current:
            continue
        try:
            store.add_item("login", f"JARVIS {e['label'][:60]} [{key}]", {
                "identifier_type": "email" if "@" in e["username"] else "username",
                "identifier": e["username"], "password": e["password"]}, origin=e["origin"])
            _synced[key] = hashlib.sha256(json.dumps([e["origin"], e["username"], e["password"]]).encode()).hexdigest()
        except Exception as ex:  # never log the secret
            logger.warning("vault sync skipped %s: %s", e.get("origin"), type(ex).__name__)


def _start_vault_sync() -> None:
    global _sync_started
    if _sync_started:
        return
    _sync_started = True

    def loop():
        while True:
            try:
                sync_vault_once()
            except Exception as e:
                logger.debug("vault sync failed: %s", type(e).__name__)
            time.sleep(60)
    threading.Thread(target=loop, name="jarvis-vault-sync", daemon=True).start()


def _post(path: str, body: dict) -> Optional[dict]:
    token = os.getenv("MCP_TOKEN", "")
    req = urllib.request.Request(CORE + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "X-Internal-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except Exception as e:  # memory must never break a turn
        logger.debug("jarvis-memory %s failed: %s", path, e)
        return None


class JarvisMemoryProvider(MemoryProvider):
    def __init__(self) -> None:
        self._last_count = 0

    @property
    def name(self) -> str:
        return "jarvis-memory"

    def is_available(self) -> bool:
        return bool(os.getenv("MCP_TOKEN"))

    def unavailable_reason(self) -> str:
        return "MCP_TOKEN is not set"

    def initialize(self, session_id: str, **kwargs) -> None:
        self._context = kwargs.get("agent_context") or "primary"
        _start_vault_sync()

    def system_prompt_block(self) -> str:
        return ("Long-term memory is JARVIS' shared memory (also used by the main agent and shown to the owner, "
                "who can edit or delete anything). Relevant memories are recalled for you before each turn. "
                "Save durable facts, preferences and lessons about the owner with your memory tool or "
                "memory_save — never secrets, passwords or one-off chit-chat.")

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        self._last_count = 0
        if is_trivial_prompt(query):
            return ""
        res = _post("/internal/memory/search", {"query": query[:2000], "limit": 6})
        hits = [h for h in (res or {}).get("hits", []) if h.get("score", 0) >= 0.35]
        self._last_count = len(hits)
        if not hits:
            return ""
        lines = [f"- [{h['category']}/{h['kind']}] {h['text']}" for h in hits]
        return "JARVIS memory (may be outdated; confirm when it matters):\n" + "\n".join(lines)

    def recall_status(self) -> Optional[RecallStatus]:
        return RecallStatus("JARVIS", self._last_count) if self._last_count else None

    def on_memory_write(self, action: str, target: str, content: str,
                        metadata: Optional[dict[str, Any]] = None) -> None:
        if getattr(self, "_context", "primary") != "primary" or action not in ("add", "replace") or not content.strip():
            return
        category = "personal" if target == "user" else "experience"
        _post("/internal/memory/save", {"text": content.strip()[:2000], "category": category,
                                        "kind": "preference" if target == "user" else "fact"})

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return []  # memory_search / memory_save come from the jarvis MCP server


def register(ctx) -> None:
    ctx.register_memory_provider(JarvisMemoryProvider())
