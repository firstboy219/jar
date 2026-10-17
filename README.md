# JARVIS — Personal AI Agent Platform

Specs: [`BRD.docx`](BRD.docx) (primary) and [`JARVIS_KNOWLEDGE_BASE (1).md`](<JARVIS_KNOWLEDGE_BASE (1).md>) (reference).
Decisions and deviations from the BRD: [`docs/decisions.md`](docs/decisions.md).

## Layout
```
infra/                  Docker Compose stack for the Lightsail server
  docker-compose.yml
  .env.example          copy of every setting; real values live in infra/.env (git-ignored)
  scripts/init-env.sh   creates .env with random secrets
  scripts/npm-proxy-hosts.sh  configures Nginx Proxy Manager hosts (+ Let's Encrypt)
  data/                 container volumes (git-ignored)
```

## Services
| Container | Role | Access |
|---|---|---|
| jarvis-proxy | Nginx Proxy Manager, SSL, WebSocket upgrade | public 80/443; admin UI 127.0.0.1:81 |
| jarvis-admin | Web admin: settings, service status, test chat | `https://jar1.cosger.online` (password login) |
| jarvis-brain | Hermes Agent (+ Playwright) — OpenAI-compatible API :8642 | via `vis1.cosger.online`, bearer `HERMES_API_KEY` |
| jarvis-executor | n8n | 127.0.0.1:5678 |
| jarvis-memory | Qdrant | 127.0.0.1:6333, `api-key` header |
| jarvis-db | PostgreSQL 16 | internal only |

Domains: `vis1.cosger.online` = backend (Hermes API), `jar1.cosger.online` = web admin.

## Setup (fresh server)
```bash
# Docker Engine + compose plugin from download.docker.com, then:
cd infra
./scripts/init-env.sh          # generates .env, prints the web admin password once
docker compose up -d --build
./scripts/npm-proxy-hosts.sh   # proxy hosts + Let's Encrypt
sudo cp systemd/jarvis-apply.* /etc/systemd/system/ && sudo systemctl enable --now jarvis-apply.path
```
Then log in at https://jar1.cosger.online and fill in the OpenRouter / n8n keys.

### How settings are applied
The web admin rewrites `infra/.env` **in place**; `jarvis-apply.path` (systemd) sees the change and runs
`scripts/apply.sh` → `docker compose up -d`, which recreates only the affected containers. Log:
`infra/data/admin/apply.log` (also shown in the admin). If you edit `.env` by hand, use an editor that
writes in place (nano, vim) — **not** `sed -i`, which replaces the file and detaches both the admin's bind
mount and the watcher (fix: `docker compose up -d admin && sudo systemctl restart jarvis-apply.path`).
Lightsail firewall must allow TCP 80 and 443.

## Internal UIs (not public)
NPM (:81), n8n (:5678) and Qdrant (:6333) are bound to 127.0.0.1 on the server. Public HTTPS access for
n8n needs its own subdomain (pending).

## Test the agent
```bash
source infra/.env
curl https://vis1.cosger.online/v1/chat/completions \
  -H "Authorization: Bearer $HERMES_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"hermes-agent","messages":[{"role":"user","content":"Halo JARVIS"}]}'
```

## Operations
- Logs: `docker compose logs -f <service>`; Hermes: `infra/data/hermes/logs/`
- Backup: `docker exec jarvis-db pg_dumpall -U jarvis_admin > backup.sql` plus `infra/data/{n8n,qdrant,hermes}`
- Upgrade: bump the pinned tag in `docker-compose.yml`, `docker compose pull && docker compose up -d`
- Rollback: revert the tag and `docker compose up -d`
