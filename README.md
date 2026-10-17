# JARVIS — Personal AI Agent Platform

Specs: [`BRD.docx`](BRD.docx) (primary) and [`JARVIS_KNOWLEDGE_BASE (1).md`](<JARVIS_KNOWLEDGE_BASE (1).md>) (reference).
Decisions and deviations from the BRD: [`docs/decisions.md`](docs/decisions.md). APK-facing API: [`docs/api.md`](docs/api.md).

## How a message flows (tiered routing)
```
APK ──wss/https──▶ jarvis-core (vis1)
                     ├─ tier 1: quick command (status, persetujuan, ingat:, memori …) → answered, no AI
                     ├─ privacy gate: secrets or /privat → blocked, never sent to the cloud
                     └─ main agent (fast model, ~1–2 s): talks, never blocks
                          └─ spawn_task ×N ─▶ workers = Hermes sessions ──MCP──▶ jarvis-tools
                                              (memory, approvals, n8n, images/videos)
                                └─ result → spoken report, repeated until the owner says "oke"
phone notifications ─▶ triage (skip / say once / urgent) ─▶ spoken without being asked
```

## Layout
```
android/                native APK (Kotlin + Jetpack Compose): walkie-talkie with live thought stream, chat, settings
core/                   jarvis-core (FastAPI) + jarvis-tools (MCP server for Hermes), tests
infra/                  Docker Compose stack for the Lightsail server
  docker-compose.yml
  .env.example          copy of every setting; real values live in infra/.env (git-ignored)
  scripts/init-env.sh   creates .env with random secrets
  scripts/npm-proxy-hosts.sh  configures Nginx Proxy Manager hosts (+ Let's Encrypt)
  scripts/test-core.sh  runs core tests against throwaway Postgres + Qdrant
  scripts/build-apk.sh  tests, builds, signs and publishes an APK release (→ web admin "Aplikasi")
  android-builder/      Docker image with JDK 17 + Android SDK 35 (no Android Studio needed)
  hermes/               Hermes persona (SOUL.md) + config sync on container start
  admin/                web admin (jar1)
  data/                 container volumes (git-ignored)
```

## Services
| Container | Role | Access |
|---|---|---|
| jarvis-proxy | Nginx Proxy Manager, SSL, WebSocket upgrade | public 80/443; admin UI 127.0.0.1:81 |
| jarvis-admin | Web admin: dashboard/usage, approvals, memory, devices, audit, settings, chat | `https://jar1.cosger.online` (password login) |
| jarvis-core | Device API + WSS, tiered routing, approvals, memory, audit, usage | `https://vis1.cosger.online` (device tokens) |
| jarvis-tools | MCP tool server for Hermes (memory, approval requests, n8n drafts) | internal :8100, bearer `MCP_TOKEN` |
| jarvis-brain | Hermes Agent (+ Playwright) — OpenAI-compatible API :8642 | internal only (called by jarvis-core) |
| jarvis-executor | n8n | `https://flow1.cosger.online` (n8n owner login) |
| jarvis-memory | Qdrant | 127.0.0.1:6333, `api-key` header |
| jarvis-db | PostgreSQL 16 (`n8n` db; `jarvis` db owned by least-privilege `jarvis_core`) | internal only |

Domains: `vis1.cosger.online` = backend (jarvis-core), `jar1.cosger.online` = web admin, `flow1.cosger.online` = n8n.

## Setup (fresh server)
```bash
# Docker Engine + compose plugin from download.docker.com, then:
cd infra
./scripts/init-env.sh          # generates .env, prints the web admin password once
docker compose up -d --build
./scripts/npm-proxy-hosts.sh   # proxy hosts + Let's Encrypt
sudo cp systemd/jarvis-apply.* /etc/systemd/system/ && sudo systemctl enable --now jarvis-apply.path
```
Lightsail firewall must allow TCP 80 and 443. Then log in at https://jar1.cosger.online and fill in the OpenRouter / n8n keys.

### How settings are applied
The web admin rewrites `infra/.env` **in place**; `jarvis-apply.path` (systemd) sees the change and runs
`scripts/apply.sh` → `docker compose up -d`, which recreates only the affected containers. Log:
`infra/data/admin/apply.log` (also shown in the admin). If you edit `.env` by hand, use an editor that
writes in place (nano, vim) — **not** `sed -i`, which replaces the file and detaches both the admin's bind
mount and the watcher (fix: `docker compose up -d admin && sudo systemctl restart jarvis-apply.path`).

## Internal UIs (not public)
NPM (:81) and Qdrant (:6333) are bound to 127.0.0.1 on the server.

## Test the agent
Create a device token in the web admin (**Perangkat**), then:
```bash
curl https://vis1.cosger.online/api/v1/chat -H "Authorization: Bearer jdv_…" \
  -H 'Content-Type: application/json' -d '{"user_command":"status","session_id":"tes"}'
```
Or use **Tes chat** on the admin dashboard.

## Android app
```bash
sudo infra/scripts/build-apk.sh 0.2.0 "Catatan rilis"   # unit + screenshot tests, signed release
```
Releases land in `infra/data/releases/` and appear in the web admin → **Aplikasi** (download needs the
admin login). Install on the phone, create a device token in **Perangkat**, paste it in the app's
**Pengaturan**. The signing keystore is `infra/data/android/release.keystore` (password
`ANDROID_KEYSTORE_PASSWORD` in `.env`) — it is in the nightly backup; **losing it means the app can no
longer be updated in place**.

UI is checked without an emulator via Paparazzi screenshots (`android/app/src/test/snapshots/images/`);
after an intentional UI change, re-record with `./gradlew recordPaparazziDebug` inside the builder.

## Tests
`sudo infra/scripts/test-core.sh` — unit + integration tests (approvals, devices, privacy gate, routing,
memory with real embeddings) against throwaway containers; never touches live data.
Android: protocol parsing, turn-state reducer, WebSocket auto-reconnect (MockWebServer), TTS text cleanup,
and screenshot tests — run by `build-apk.sh`.

## Operations
- Deploy a service: `sudo infra/scripts/compose.sh up -d --build <service>` (shares a lock with the .env watcher)
- Logs: `docker compose logs -f <service>`; Hermes: `infra/data/hermes/logs/`
- Upgrade: bump the pinned tag in `docker-compose.yml`, `docker compose pull && docker compose up -d`
- Rollback: revert the tag and `docker compose up -d`

## Backup & restore
`jarvis-backup.timer` runs `infra/scripts/backup.sh` daily at 03:00 WIB and keeps 7 copies in
`infra/backups/<UTC timestamp>/` (root-only; contains `.env` secrets):
`postgres.sql.gz`, `qdrant.snapshot`, `files.tar.gz` (.env + hermes/n8n/npm/letsencrypt data).
Install: `sudo cp infra/systemd/jarvis-backup.* /etc/systemd/system/ && sudo systemctl enable --now jarvis-backup.timer`.
Backups live on the same disk — also enable Lightsail automatic snapshots for off-server copies.

Restore (on a fresh checkout, after installing Docker):
```bash
cd infra && B=backups/<timestamp>
sudo tar -xzf $B/files.tar.gz                       # .env + data dirs
docker compose up -d postgres-db qdrant
gunzip -c $B/postgres.sql.gz | docker exec -i jarvis-db psql -U jarvis_admin -d postgres
curl -X POST -H "api-key: $(grep ^QDRANT_API_KEY= .env | cut -d= -f2)" \
  -F snapshot=@$B/qdrant.snapshot 'http://127.0.0.1:6333/collections/<name>/snapshots/upload'  # per collection
docker compose up -d --build
```
