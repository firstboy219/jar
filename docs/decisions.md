# Architecture Decision Record

Spec hierarchy: `BRD.docx` is primary; `JARVIS_KNOWLEDGE_BASE (1).md` is reference.

## ADR-001 — n8n is installed fresh in Docker (2026-10-17)
The KB says to reuse an existing n8n, but the target server had none. Per the BRD, n8n + PostgreSQL
run in the JARVIS compose stack.

## ADR-002 — Hermes Agent only; OpenClaw deferred (2026-10-17)
BRD runs both. We start with Hermes Agent (its built-in OpenAI-compatible API server on :8642
serves as the backend endpoint) and add OpenClaw only when a concrete need appears.

## ADR-003 — Generated n8n workflows need owner approval (2026-10-17)
Deviation from BR-002 "100% autonomous". Workflows Hermes generates are created **inactive** in n8n
and activated only after approval in the Action Approval Queue.

## ADR-004 — Models (2026-10-17)
BRD's `nousresearch/hermes-3-llama-3.1-70b` has **no tool-calling** on OpenRouter, and
Qwen 2.5 Coder 72B is no longer listed. Hermes Agent needs tool calling, so defaults are:
- general: `deepseek/deepseek-v4-flash` (≈$0.09/M in, $0.18/M out, 1M ctx)
- coding / n8n JSON: `qwen/qwen3-coder-next`

Both are `.env` settings (`JARVIS_DEFAULT_MODEL`, `JARVIS_CODER_MODEL`), so they can change without code.

## ADR-005 — Security deviations from the BRD compose
| BRD | Here | Why |
|---|---|---|
| Passwords/API keys inline | `.env` (mode 600, git-ignored), random secrets from `scripts/init-env.sh` | No secrets in git |
| `:latest` tags | Pinned versions | Reproducible, no surprise upgrades |
| 81, 1024, 5678, 6333, 18789 published on 0.0.0.0 | Only 80/443 public; 81/5678/6333 bound to 127.0.0.1 | Admin UIs and DBs not on the internet |
| Qdrant without auth | `QDRANT__SERVICE__API_KEY` | Defense in depth |
| `hermes-agent:latest-playwright`, `/app/config` mounts | `hermes-agent:v0.22.2` (tag in BRD does not exist), `/opt/data` | Match the real image |
| `ipc: host` | `shm_size: 1gb` | Chromium shared memory without sharing host IPC |
| `/var/www/...`, `/var/log/nginx` mounts | NPM logs mounted `:ro` | Those host paths don't exist on this server |
| Deepgram key in the APK (FS-101) | Backend will mint short-lived Deepgram tokens | A key in an APK is extractable (Milestone: APK) |

## ADR-006 — Web admin applies settings without a Docker socket (2026-10-17)
The owner wants to enter keys from the browser (jar1.cosger.online). The admin container only gets
`infra/.env` (rw) and `data/admin` (ro); a host systemd path unit runs `docker compose up -d` on change.
Giving the admin the Docker socket would make a web login equivalent to root on the host.
Auth: scrypt password hash in `.env`, HMAC-signed HttpOnly/Secure/SameSite=Strict cookie (12 h,
invalidated on password change), Origin check on POSTs, 5 failed logins / 15 min per IP.
Secrets are write-only in the UI (only the last 4 chars are shown).

## ADR-007 — Tiered routing; no local LLM on this server (2026-10-17)
The owner does not want every chat sent straight to OpenRouter. A local model was benchmarked here
(qwen3:4b, Ollama, 4 vCPU Xeon 8175M, no GPU): ~13 tok/s prompt processing, 4.5 tok/s generation —
a single Hermes turn (≈13k-token prompt) would take ~17 minutes. So, chosen by the owner:
1. **Tier 1 — jarvis-core rules**: quick commands answered with no model at all.
2. **Privacy gate**: messages with secrets (API keys, passwords, private keys, Luhn-valid card numbers)
   or prefixed `/privat` are never sent to a cloud model; the stored log is redacted.
3. **Tier 2 — Hermes on a cheap model** (`JARVIS_DEFAULT_MODEL`).
4. **Tier 3 — `delegate_task`** to `JARVIS_EXPERT_MODEL`, only when Hermes judges it necessary (SOUL.md).
Embeddings for memory run locally on CPU (fastembed multilingual MiniLM), so memory text is not sent
out just to be indexed. A GPU host can later be plugged in as Hermes' main provider.

## ADR-008 — jarvis-core owns state; Hermes acts through MCP tools (2026-10-17)
KB: the agent runtime must not be the source of truth. jarvis-core (FastAPI, `jarvis` Postgres db)
stores devices, messages, approvals, memories and the audit log. Hermes gets tools only via the
`jarvis-tools` MCP server and holds no n8n/Qdrant credentials, so every side effect is policy-checked:
risky actions become approval requests, and n8n workflows are created inactive with an activation
approval (ADR-003). Hermes' API is no longer public; `vis1` points to jarvis-core.

## ADR-009 — Native Android app (Kotlin + Compose) (2026-10-17)
Owner asked for a native APK (KB suggested Flutter). Stack: Kotlin 2.0, Jetpack Compose (BOM 2024.12),
OkHttp WebSockets, EncryptedSharedPreferences for the device token, minSdk 26 / target 35.
- Walkie-talkie screen shows JARVIS' live "thought stream": jarvis-core relays Hermes' streamed reasoning,
  tool lifecycle and answer deltas over WSS, and re-runs Hermes' memory queries locally to show which
  memories it is looking at (context cards).
- Voice: AudioRecord Linear16 16 kHz mono, 100 ms chunks → Deepgram `nova-3` (`language=id`) with a
  60-second token from jarvis-core; KeepAlive every 5 s (FS-101). Replies are spoken with on-device
  Android TTS (id-ID) — free and no extra round trip, unlike the BRD's OpenAI TTS.
- Built in Docker (`infra/android-builder`), signed with a server-side keystore, published to the web admin.

## ADR-010 — Hermes built-in memory disabled (2026-10-17)
Hermes was writing its own MEMORY.md/USER.md entries alongside the jarvis memory. Two unmanaged stores
violate "memory is visible/editable by the owner", so `memory.memory_enabled` and
`user_profile_enabled` are off; all long-term memory goes through the jarvis MCP tools.

## Known gap — latency vs BR-001
Measured end-to-end: tier-1 commands ~0.1 s; Hermes turns 6–23 s (cloud model + 13k-token agent prompt +
tool calls). BR-001's < 1.5 s target is not met for agent answers. Since streaming (ADR-009) the first
visible sign of thinking arrives in ~3 s and the answer streams as it is written. Options to evaluate with the APK:
stream partial text over WSS, a faster tier-2 model, prompt caching, trimming Hermes toolsets.

## Known risk
Hermes' terminal backend is `local`, i.e. commands run inside the `jarvis-brain` container. The
container is the sandbox for now; revisit (`terminal.backend: docker`) before enabling Execute-level tools.
