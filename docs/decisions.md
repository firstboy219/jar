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

## Known risk
Hermes' terminal backend is `local`, i.e. commands run inside the `jarvis-brain` container. The
container is the sandbox for now; revisit (`terminal.backend: docker`) before enabling Execute-level tools.
