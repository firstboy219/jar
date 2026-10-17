#!/usr/bin/env bash
# docker compose, serialized with the .env watcher (jarvis-apply) so two `up`s never race.
# Usage: sudo infra/scripts/compose.sh up -d --build jarvis-core
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/admin
exec flock data/admin/compose.lock docker compose "$@"
