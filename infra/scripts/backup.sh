#!/usr/bin/env bash
# Daily JARVIS backup (run by jarvis-backup.timer, as root).
# Produces infra/backups/<timestamp>/ with:
#   postgres.sql.gz   pg_dumpall (n8n + jarvis databases)
#   qdrant.snapshot   full-storage snapshot downloaded through the Qdrant API
#   files.tar.gz      hermes, n8n, npm, letsencrypt data + .env (secrets! dir is mode 700)
# Keeps the newest $KEEP backups. Restore steps: README.md → "Backup & restore".
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

KEEP=${KEEP:-7}
DEST="backups/$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$DEST"
log() { echo "[$(date -Is)] $*"; }

log "postgres"
docker exec jarvis-db pg_dumpall -U "$POSTGRES_USER" | gzip > "$DEST/postgres.sql.gz"

log "qdrant snapshot"
Q=http://127.0.0.1:6333; QH="api-key: $QDRANT_API_KEY"
snap=$(curl -sf -X POST -H "$QH" "$Q/snapshots" | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"]["name"])')
curl -sf -H "$QH" "$Q/snapshots/$snap" -o "$DEST/qdrant.snapshot"
curl -sf -X DELETE -H "$QH" "$Q/snapshots/$snap" >/dev/null

log "files"
tar -czf "$DEST/files.tar.gz" \
  --exclude='data/hermes/cache' --exclude='data/hermes/image_cache' --exclude='data/hermes/audio_cache' \
  --exclude='data/hermes/logs' --exclude='data/npm/logs' --exclude='*.sock' \
  .env data/hermes data/n8n data/npm data/letsencrypt

log "prune (keep $KEEP)"
ls -1dt backups/*/ | tail -n +$((KEEP + 1)) | xargs -r rm -rf

log "done: $DEST ($(du -sh "$DEST" | cut -f1))"
