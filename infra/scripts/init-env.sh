#!/usr/bin/env bash
# Create infra/.env from .env.example, filling empty secrets with random values.
# Safe to re-run: an existing .env is never overwritten.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -f .env ]]; then
  echo ".env already exists; leaving it untouched."
  exit 0
fi

gen() { openssl rand -hex 32; }

umask 077
sed \
  -e "s|^HERMES_API_KEY=$|HERMES_API_KEY=$(gen)|" \
  -e "s|^POSTGRES_PASSWORD=$|POSTGRES_PASSWORD=$(gen)|" \
  -e "s|^N8N_ENCRYPTION_KEY=$|N8N_ENCRYPTION_KEY=$(gen)|" \
  -e "s|^QDRANT_API_KEY=$|QDRANT_API_KEY=$(gen)|" \
  -e "s|^JARVIS_DB_PASSWORD=$|JARVIS_DB_PASSWORD=$(gen)|" \
  -e "s|^CORE_ADMIN_TOKEN=$|CORE_ADMIN_TOKEN=$(gen)|" \
  -e "s|^MCP_TOKEN=$|MCP_TOKEN=$(gen)|" \
  -e "s|^LLM_GATEWAY_KEY=$|LLM_GATEWAY_KEY=$(gen)|" \
  -e "s|^JARVIS_RO_PASSWORD=$|JARVIS_RO_PASSWORD=$(gen)|" \
  -e "s|^ANDROID_KEYSTORE_PASSWORD=$|ANDROID_KEYSTORE_PASSWORD=$(gen)|" \
  -e "s|^HOST_UID=.*|HOST_UID=$(id -u)|" \
  -e "s|^HOST_GID=.*|HOST_GID=$(id -g)|" \
  .env.example > .env

admin_pw=$(openssl rand -base64 18 | tr -d '/+=')
admin_hash=$(cd admin && python3 -I -c 'import sys; sys.path.insert(0, "."); from app.auth import hash_password; print(hash_password(sys.argv[1]))' "$admin_pw")
sed -i \
  -e "s|^ADMIN_PASSWORD_HASH=$|ADMIN_PASSWORD_HASH=$admin_hash|" \
  -e "s|^ADMIN_SESSION_SECRET=$|ADMIN_SESSION_SECRET=$(gen)|" \
  .env

mkdir -p data/{npm/logs,letsencrypt,hermes,n8n,qdrant,postgres,admin,documents,models,llm-slots/chat,llm-slots/worker}
echo "Created .env (mode 600)."
echo "Web admin password (shown once, change it after first login): $admin_pw"
echo "Download the local models: ./scripts/get-models.sh"
echo "Optional (from the web admin or APK): OpenRouter / Groq / Deepgram keys, n8n API key."
