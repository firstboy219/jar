#!/usr/bin/env bash
# Run jarvis-core tests in a throwaway network with a fresh Postgres + Qdrant (never touches live data).
# CORE_DIR: test another checkout (the self-improvement runner tests proposed changes in a worktree).
set -euo pipefail
cd "${CORE_DIR:-$(dirname "$0")/../../core}"
NET=jarvis-test-$$
cleanup() { docker rm -f "$NET-db" "$NET-qdrant" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker build -q --build-arg DEV=1 -t jarvis-core:test . >/dev/null
docker network create "$NET" >/dev/null
docker run -d --name "$NET-db" --network "$NET" -e POSTGRES_PASSWORD=test -e POSTGRES_DB=jarvis postgres:16.15-alpine >/dev/null
docker run -d --name "$NET-qdrant" --network "$NET" qdrant/qdrant:v1.19.2 >/dev/null
until docker exec "$NET-db" pg_isready -U postgres -d jarvis >/dev/null 2>&1; do sleep 1; done
sleep 2
docker run --rm --network "$NET" \
  -e TEST_DATABASE_URL="postgresql://postgres:test@$NET-db/jarvis" \
  -e TEST_QDRANT_URL="http://$NET-qdrant:6333" \
  jarvis-core:test python -m pytest -q "$@"
