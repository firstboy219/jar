"""Runtime settings, all from environment (populated by docker compose from infra/.env)."""

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    hermes_url: str = field(default_factory=lambda: _env("HERMES_URL", "http://jarvis-brain:8642"))
    hermes_api_key: str = field(default_factory=lambda: _env("HERMES_API_KEY"))
    n8n_url: str = field(default_factory=lambda: _env("N8N_URL", "http://jarvis-executor:5678"))
    n8n_api_key: str = field(default_factory=lambda: _env("N8N_API_KEY"))
    qdrant_url: str = field(default_factory=lambda: _env("QDRANT_URL", "http://jarvis-memory:6333"))
    qdrant_api_key: str = field(default_factory=lambda: _env("QDRANT_API_KEY"))
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    coder_model: str = field(default_factory=lambda: _env("JARVIS_CODER_MODEL", "qwen/qwen3-coder-next"))
    # Main agent ("agen utama"): fast conversational model; benchmarked ~0.7 s to first token (ADR-012).
    chat_model: str = field(default_factory=lambda: _env("JARVIS_CHAT_MODEL", "anthropic/claude-haiku-5.5"))
    # Workers run on Hermes. Tasks are unlimited (queued); this caps how many run at the same time.
    worker_concurrency: int = field(default_factory=lambda: int(_env("WORKER_CONCURRENCY", "6") or 6))
    # Re-deliver a spoken report if the owner has not confirmed hearing it within this many seconds.
    report_ack_timeout_s: int = field(default_factory=lambda: int(_env("REPORT_ACK_TIMEOUT_S", "90") or 90))
    report_max_attempts: int = 3
    deepgram_api_key: str = field(default_factory=lambda: _env("DEEPGRAM_API_KEY"))
    # Benchmarked 2026-10-17 on Indonesian commands: nova-2 WER 12-15% vs nova-3 19-22% (docs/decisions.md).
    deepgram_model: str = field(default_factory=lambda: _env("DEEPGRAM_MODEL", "nova-2"))
    deepgram_language: str = field(default_factory=lambda: _env("DEEPGRAM_LANGUAGE", "id"))
    deepgram_keywords: str = field(default_factory=lambda: _env(
        "DEEPGRAM_KEYWORDS", "JARVIS,Autotoko,n8n,UAT,BRD,FSD,workflow,Shopee,Tokopedia"))
    # web admin -> core (internal network only)
    admin_token: str = field(default_factory=lambda: _env("CORE_ADMIN_TOKEN"))
    # hermes -> jarvis-tools MCP server
    mcp_token: str = field(default_factory=lambda: _env("MCP_TOKEN"))
    embed_model: str = field(default_factory=lambda: _env(
        "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"))
    memory_collection: str = "jarvis_memory"
    hermes_timeout: float = 180.0


settings = Settings()
