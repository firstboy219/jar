#!/usr/bin/env bash
# Run jarvis-core tests in a throwaway network with a fresh Postgres + Qdrant (never touches live data).
# CORE_DIR: test another checkout (the self-improvement runner tests proposed changes in a worktree).
set -euo pipefail
cd "${CORE_DIR:-$(dirname "$0")/../../core}"
NET=jarvis-test-$$
cleanup() { docker rm -f "$NET-db" "$NET-qdrant" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# the 3D canvas viewer's pure modules (gestures, galaxy geometry) — ES modules tested with node when it is installed
if command -v node >/dev/null && [ -d app/web/canvas/tests ]; then
  (cd app/web/canvas && node --test tests/ >/tmp/jarvis-canvas-js.log 2>&1) || { cat /tmp/jarvis-canvas-js.log; echo "canvas JS tests failed"; exit 1; }
  echo "canvas JS: $(grep -E '^# pass' /tmp/jarvis-canvas-js.log)"
fi
if command -v node >/dev/null && [ -d app/web/notes/tests ]; then   # Catatan's editor helpers (ADR-060)
  (cd app/web/notes && node --test tests/ >/tmp/jarvis-notes-js.log 2>&1) || { cat /tmp/jarvis-notes-js.log; echo "notes JS tests failed"; exit 1; }
  echo "notes JS: $(grep -E '^# pass' /tmp/jarvis-notes-js.log)"
fi
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
