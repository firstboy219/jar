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
    # Workers run on Hermes. Tasks are unlimited (queued); this caps how many run at the same time.
    worker_concurrency: int = field(default_factory=lambda: int(_env("WORKER_CONCURRENCY", "6") or 6))
    # Re-deliver a spoken report if the owner has not confirmed hearing it within this many seconds.
    report_ack_timeout_s: int = field(default_factory=lambda: int(_env("REPORT_ACK_TIMEOUT_S", "90") or 90))
    report_max_attempts: int = 3
    # Notifications: only urgent ones are spoken during these hours (WIB, "HH:MM-HH:MM", empty = never quiet)
    quiet_hours: str = field(default_factory=lambda: _env("QUIET_HOURS", "22:00-06:00"))
    deepgram_api_key: str = field(default_factory=lambda: _env("DEEPGRAM_API_KEY"))
    # Benchmarked 2026-10-17 on Indonesian commands: nova-2 WER 12-15% vs nova-3 19-22% (docs/decisions.md).
    deepgram_model: str = field(default_factory=lambda: _env("DEEPGRAM_MODEL", "nova-2"))
    deepgram_language: str = field(default_factory=lambda: _env("DEEPGRAM_LANGUAGE", "id"))
    # End-of-speech tuning sent to the app (v0.5 used 700/1500 and cut sentences mid-thought).
    endpointing_ms: int = field(default_factory=lambda: int(_env("DEEPGRAM_ENDPOINTING_MS", "1000") or 1000))
    utterance_end_ms: int = field(default_factory=lambda: int(_env("DEEPGRAM_UTTERANCE_END_MS", "1800") or 1800))
    deepgram_keywords: str = field(default_factory=lambda: _env(
        "DEEPGRAM_KEYWORDS", "JARVIS,Autotoko,n8n,UAT,BRD,FSD,workflow,Shopee,Tokopedia"))
    # web admin -> core (internal network only)
    admin_token: str = field(default_factory=lambda: _env("CORE_ADMIN_TOKEN"))
    # hermes -> jarvis-tools MCP server
    mcp_token: str = field(default_factory=lambda: _env("MCP_TOKEN"))
    # hermes -> jarvis-core LLM gateway (/llm/v1)
    llm_gateway_key: str = field(default_factory=lambda: _env("LLM_GATEWAY_KEY"))
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))
    # local speech recognition service (faster-whisper) and speaker verification
    whisper_url: str = field(default_factory=lambda: _env("WHISPER_URL", "http://jarvis-ears:8000"))
    embed_model: str = field(default_factory=lambda: _env(
        "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"))
    memory_collection: str = "jarvis_memory"
    hermes_timeout: float = 180.0


settings = Settings()
