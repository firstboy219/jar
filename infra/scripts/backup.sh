#!/usr/bin/env bash
# Daily JARVIS backup (run by jarvis-backup.timer, as root).
# Produces infra/backups/<timestamp>/ with:
#   postgres.sql.gz   pg_dumpall (n8n + jarvis databases)
#   qdrant.snapshot   full-storage snapshot downloaded through the Qdrant API
#   files.tar.gz      hermes, n8n, npm, letsencrypt data, documents, APK signing keystore + releases, .env (secrets! mode 700)
# Keeps the newest $KEEP backups. Restore steps: README.md → "Backup & restore".
# Off-site copy (a backup on the same disk does not survive the disk): when BACKUP_REMOTE (an rclone
# remote, e.g. "gdrive:jarvis-backup" or "r2:jarvis") and backups/age-recipients.txt exist, the backup is
# encrypted with age (only the owner's private key can open it) and uploaded; 14 copies are kept there.
# Not backed up: downloaded speech models (jarvis-ears fetches them again), prompt caches, music cache, and
# meeting audio (deleted after 30 days anyway; transcripts and minutes are in Postgres).
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
  --exclude='data/android/gradle-cache' --exclude='data/hermes/plugins/jarvis-memory' \
  .env data/hermes data/n8n data/npm data/letsencrypt data/android data/releases data/documents

REMOTE=$(grep '^BACKUP_REMOTE=' .env | cut -d= -f2- || true)
if [[ -n $REMOTE && -s backups/age-recipients.txt ]] && command -v age >/dev/null && command -v rclone >/dev/null; then
  log "off-site: encrypt + upload to $REMOTE"
  ARCHIVE="backups/$(basename "$DEST").tar.age"
  tar -C backups -cf - "$(basename "$DEST")" | age -R backups/age-recipients.txt > "$ARCHIVE"
  if rclone --config backups/rclone.conf copy "$ARCHIVE" "$REMOTE/" --quiet; then
    rclone --config backups/rclone.conf lsf "$REMOTE/" | sort | head -n -14 | xargs -r -I{} rclone --config backups/rclone.conf deletefile "$REMOTE/{}"
    log "off-site ok"
  else
    log "off-site upload FAILED (local backup kept)"
  fi
  rm -f "$ARCHIVE"
else
  log "off-site: not configured (BACKUP_REMOTE + backups/age-recipients.txt + age/rclone) — local copy only"
fi

log "prune (keep $KEEP)"
ls -1dt backups/*/ | tail -n +$((KEEP + 1)) | xargs -r rm -rf

log "done: $DEST ($(du -sh "$DEST" | cut -f1))"
