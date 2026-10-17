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
| jarvis-brain | Hermes Agent (+ Playwright) — OpenAI-compatible API :8642 | via `vis1.cosger.online`, bearer `HERMES_API_KEY` |
| jarvis-executor | n8n | 127.0.0.1:5678 |
| jarvis-memory | Qdrant | 127.0.0.1:6333, `api-key` header |
| jarvis-db | PostgreSQL 16 | internal only |

Domains: `vis1.cosger.online` = backend, `jar1.cosger.online` = frontend (not yet wired).

## Setup (fresh server)
```bash
# Docker Engine + compose plugin from download.docker.com, then:
cd infra
./scripts/init-env.sh          # generates .env
nano .env                      # fill OPENROUTER_API_KEY, LETSENCRYPT_EMAIL
docker compose up -d
./scripts/npm-proxy-hosts.sh   # proxy hosts + SSL
```
Lightsail firewall must allow TCP 80 and 443.

## Admin UIs (SSH tunnel, never public)
```bash
ssh -L 8181:localhost:81 -L 5678:localhost:5678 -L 6333:localhost:6333 ubuntu@<server>
```
Then open http://localhost:8181 (NPM; credentials in `infra/.env`), http://localhost:5678 (n8n).
After creating the n8n owner account, create an API key (Settings → n8n API), put it in
`N8N_API_KEY`, and run `docker compose up -d hermes-agent`.

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
