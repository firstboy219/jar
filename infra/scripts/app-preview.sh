#!/usr/bin/env bash
# Screenshots of the app v2 (ADR-087) on a throwaway stack: fresh Postgres + Qdrant + jarvis-core:test (this checkout) + headless Chrome.
# Never touches live data. Usage: OUT=/some/dir infra/scripts/app-preview.sh [route ...]   (routes like "beranda" "misi" "kontrol")
set -euo pipefail
cd "$(dirname "$0")/../../core"
OUT="${OUT:-/tmp/jarvis-preview}"; mkdir -p "$OUT"
NET=jarvis-preview-$$
cleanup() { docker rm -f "$NET-db" "$NET-qdrant" "$NET-core" "$NET-chrome" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
[ "${SKIP_BUILD:-0}" = 1 ] || docker build -q --build-arg DEV=1 -t jarvis-core:test . >/dev/null
docker network create "$NET" >/dev/null
docker run -d --name "$NET-db" --network "$NET" -e POSTGRES_PASSWORD=test -e POSTGRES_DB=jarvis postgres:16.15-alpine >/dev/null
docker run -d --name "$NET-qdrant" --network "$NET" qdrant/qdrant:v1.19.2 >/dev/null
until docker exec "$NET-db" pg_isready -U postgres -d jarvis >/dev/null 2>&1; do sleep 1; done
sleep 2
docker run -d --name "$NET-core" --network "$NET" --network-alias core -e DATABASE_URL="postgresql://postgres:test@$NET-db/jarvis" \
  -e QDRANT_URL="http://$NET-qdrant:6333" -e CORE_ADMIN_TOKEN=preview -e OPENROUTER_API_KEY=sk-or-preview jarvis-core:test >/dev/null
docker run -d --name "$NET-chrome" --network "$NET" --network-alias chrome chromedp/headless-shell:latest >/dev/null
for i in $(seq 1 60); do docker exec "$NET-core" python -c "import httpx;httpx.get('http://localhost:8000/healthz').raise_for_status()" >/dev/null 2>&1 && break; sleep 1; done
docker cp ../infra/scripts/app_preview.py "$NET-core":/tmp/app_preview.py
docker exec -e PYTHONPATH=/srv -e DATABASE_URL="postgresql://postgres:test@$NET-db/jarvis" "$NET-core" python -u /tmp/app_preview.py "$@"
docker cp "$NET-core":/tmp/shots/. "$OUT"/
echo "screenshots in $OUT"
