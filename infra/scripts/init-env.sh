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
  -e "s|^HOST_UID=.*|HOST_UID=$(id -u)|" \
  -e "s|^HOST_GID=.*|HOST_GID=$(id -g)|" \
  .env.example > .env

mkdir -p data/{npm,letsencrypt,hermes,n8n,qdrant,postgres}
echo "Created .env (mode 600). Still to fill in manually: OPENROUTER_API_KEY, LETSENCRYPT_EMAIL, N8N_API_KEY."
