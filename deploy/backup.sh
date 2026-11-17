#!/bin/sh
# Backup of what cannot be made again: the account database and every project except regenerable caches.
#   deploy/backup.sh /path/to/backups        (run it from cron; copy the result off the machine, for example with rclone to Cloudflare R2)
set -eu
DEST="${1:?usage: backup.sh <folder>}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
docker compose -f "$(dirname "$0")/docker-compose.yml" exec -T app sh -c '
  python - <<PY
import sqlite3
src = sqlite3.connect("/data/work/app.db"); dst = sqlite3.connect("/tmp/app-backup.db"); src.backup(dst); dst.close()
PY
  tar -C /data -czf /tmp/avc-backup.tgz --exclude="projects/*/tl_segments*" --exclude="projects/*/audio_mix" --exclude="*.part*" projects -C /tmp app-backup.db
  cat /tmp/avc-backup.tgz; rm -f /tmp/avc-backup.tgz /tmp/app-backup.db' > "$DEST/avc-$STAMP.tgz"
echo "wrote $DEST/avc-$STAMP.tgz"
