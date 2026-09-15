#!/usr/bin/env bash
# Daily off-server PostgreSQL backup for the Docker stack.
# Add to crontab:   0 2 * * *  /path/to/backup-db.sh   (runs daily at 02:00)
set -euo pipefail
STAMP=$(date +%Y%m%d-%H%M)
OUT_DIR="${BACKUP_DIR:-$HOME/mdc-backups}"
mkdir -p "$OUT_DIR"
# dump the database from the running 'db' container
docker compose exec -T db pg_dump -U mdc mdc_erp | gzip > "$OUT_DIR/mdc_erp-$STAMP.sql.gz"
# keep the last 30 days
find "$OUT_DIR" -name 'mdc_erp-*.sql.gz' -mtime +30 -delete
echo "Backup written: $OUT_DIR/mdc_erp-$STAMP.sql.gz"
# IMPORTANT: copy $OUT_DIR off this server (another disk / cloud storage) and
# test a RESTORE regularly — a backup you have never restored is not a backup.
