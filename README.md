# JARVIS — Personal AI Agent Platform

Specs: [`BRD.docx`](BRD.docx) (primary) and [`JARVIS_KNOWLEDGE_BASE (1).md`](<JARVIS_KNOWLEDGE_BASE (1).md>) (reference).
Decisions and deviations from the BRD: [`docs/decisions.md`](docs/decisions.md). APK-facing API: [`docs/api.md`](docs/api.md).

## How a message flows
```
APK: mic → Silero VAD (on the phone) → utterance ──wss──▶ jarvis-core (vis1)
                                                            ├─ speech → text: Whisper local / Groq / Deepgram (+ voiceprint)
                                                            ├─ quick command (status, persetujuan, ingat: …) → no AI
                                                            └─ main agent ──▶ LLM gateway ──▶ owner's composition
                                                                 │             (cloud routes or local Qwen; /privat → local only)
                                                                 ├─ "say" sentence by sentence → phone speaks while it thinks
                                                                 ├─ stage panels (music, map, web, doc, draft) → phone screen
                                                                 └─ spawn_task ×N ─▶ Hermes runs (own flow, all features)
                                                                       ├─ LLM calls → gateway (jarvis-<category>)
                                                                       ├─ MCP jarvis-tools (memory, owner, stage, docs, n8n, DB ro)
                                                                       └─ dangerous command → approval on the phone
                                                                 └─ result → spoken report, repeated until the owner says "oke"
phone notifications ─▶ triage (skip / say once / urgent) ─▶ spoken without being asked
meetings: phone records 60 s chunks ─▶ jarvis-ears (transcribe + diarize) ─▶ minutes (.docx) + Q&A
```
Decisions: ADR-017 (gateway, local by default, budget), ADR-018 (Hermes free mode, one memory),
ADR-019 (voice), ADR-020 (meetings/drafts privacy), ADR-021 (wake word, barge-in).

## Layout
```
android/                native APK (Kotlin + Compose): talk (VAD, wake word, 3D brain, stage panels), chat, tasks,
                        meetings, full owner console (Lainnya)
core/                   jarvis-core (FastAPI) + jarvis-tools (MCP server for Hermes), tests
infra/                  Docker Compose stack for the Lightsail server
  docker-compose.yml
  .env.example          copy of every setting; real values live in infra/.env (git-ignored)
  scripts/init-env.sh   creates .env with random secrets
  scripts/npm-proxy-hosts.sh  configures Nginx Proxy Manager hosts (+ Let's Encrypt)
  scripts/test-core.sh  runs core tests against throwaway Postgres + Qdrant
  scripts/build-apk.sh  tests, builds, signs and publishes an APK release (→ web admin "Aplikasi")
  android-builder/      Docker image with JDK 17 + Android SDK 35 (no Android Studio needed)
  hermes/               Hermes persona (SOUL.md), config sync on start, jarvis-memory plugin
  ears/                 jarvis-ears: faster-whisper + sherpa-onnx (voiceprint, diarization)
  scripts/get-models.sh downloads the local Qwen models
  scripts/install-skills.sh  teaches Hermes 89 extra skills (JARVIS, anthropics/skills, superpowers, Hermes optional)
  hermes/skills/        JARVIS' own skills (Indonesian context)
  admin/                web admin (jar1)
  data/                 container volumes (git-ignored)
```

## Services
| Container | Role | Access |
|---|---|---|
| jarvis-proxy | Nginx Proxy Manager, SSL, WebSocket upgrade | public 80/443; admin UI 127.0.0.1:81 |
| jarvis-admin | Web admin: dashboard/usage, approvals, memory, devices, audit, settings, chat | `https://jar1.cosger.online` (password login) |
| jarvis-core | Device API + WSS, tiered routing, approvals, memory, audit, usage | `https://vis1.cosger.online` (device tokens) |
| jarvis-tools | MCP tool server for Hermes (memory, owner, stage, documents, approvals, n8n, read-only DB/metrics) | internal :8100, bearer `MCP_TOKEN` |
| jarvis-llm-chat | llama.cpp, Qwen3.5-2B, prompt cache (answers the owner when local) | internal |
| jarvis-llm-worker | llama.cpp, Qwen3.5-4B 64k ctx, idle CPU priority (Hermes when local) | internal |
| jarvis-ears | local speech recognition, voiceprint, meeting diarization | internal |
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
./scripts/get-models.sh        # local Qwen models (~4 GB)
./scripts/install-skills.sh    # Hermes skills (after the stack is up)
docker compose up -d --build
./scripts/npm-proxy-hosts.sh   # proxy hosts + Let's Encrypt
sudo cp systemd/jarvis-apply.* /etc/systemd/system/ && sudo systemctl enable --now jarvis-apply.path
```
Lightsail firewall must allow TCP 80 and 443. JARVIS works fully locally out of the box; cloud keys
(OpenRouter, Groq, Deepgram, TomTom/ORS) are optional and can be added in the web admin or the APK.

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
Off-site copy: put an rclone remote in `BACKUP_REMOTE` (e.g. `gdrive:jarvis-backup`, config in
`infra/backups/rclone.conf`) and the owner's age public key in `infra/backups/age-recipients.txt`; each backup
is then encrypted (only the owner's private key opens it) and uploaded, 14 copies kept. Models, prompt caches,
music and meeting audio are not backed up (re-downloadable / temporary).

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
