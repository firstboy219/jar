#!/usr/bin/env bash
# Run by jarvis-apply.service whenever infra/.env changes (e.g. saved from the web admin).
# `docker compose up -d` recreates only the services whose effective config changed.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/admin
{
  echo "[$(date -Is)] .env changed -> docker compose up -d"
  docker compose up -d 2>&1 | grep -vE '^\s*$' | sed 's/^/  /'
  echo "[$(date -Is)] exit ${PIPESTATUS[0]}"
} >> data/admin/apply.log
tail -n 200 data/admin/apply.log > data/admin/apply.log.tmp && cat data/admin/apply.log.tmp > data/admin/apply.log && rm data/admin/apply.log.tmp
