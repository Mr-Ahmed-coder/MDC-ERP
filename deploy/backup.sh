#!/bin/sh
# Encrypted daily backup. Schedule after setting BACKUP_ENCRYPTION_KEY in a
# root-only environment file, for example: 0 2 * * * /opt/mdc-erp/deploy/backup.sh
set -eu
umask 077

STAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
DEST=${BACKUP_DIR:-/var/backups/mdc}
KEY=${BACKUP_ENCRYPTION_KEY:-}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-30}

if [ -z "$KEY" ]; then
  echo 'BACKUP_ENCRYPTION_KEY is required; refusing to create an unencrypted backup.' >&2
  exit 2
fi
command -v openssl >/dev/null 2>&1 || { echo 'openssl is required' >&2; exit 2; }
mkdir -p "$DEST"
TMP=$(mktemp)
trap 'rm -f "$TMP" "$TMP.gz" "$TMP.enc"' EXIT INT TERM

if [ -n "${DATABASE_URL:-}" ]; then
  if command -v pg_dump >/dev/null 2>&1; then
    pg_dump --no-owner --no-privileges "$DATABASE_URL" > "$TMP"
  else
    docker compose exec -T db pg_dump -U "${POSTGRES_USER:-mdc}" "${POSTGRES_DB:-mdc_erp}" > "$TMP"
  fi
  gzip -c "$TMP" > "$TMP.gz"
  TYPE=postgres
else
  DB_PATH=${SQLITE_DB_PATH:-${DATA_DIR:-.}/erp.db}
  [ -f "$DB_PATH" ] || { echo "SQLite database not found: $DB_PATH" >&2; exit 1; }
  gzip -c "$DB_PATH" > "$TMP.gz"
  TYPE=sqlite
fi

openssl enc -aes-256-cbc -pbkdf2 -salt -pass "pass:$KEY" -in "$TMP.gz" -out "$DEST/mdc-${TYPE}-${STAMP}.gz.enc"
openssl enc -d -aes-256-cbc -pbkdf2 -pass "pass:$KEY" -in "$DEST/mdc-${TYPE}-${STAMP}.gz.enc" | gzip -t
printf '%s %s\n' "$(sha256sum "$DEST/mdc-${TYPE}-${STAMP}.gz.enc" | awk '{print $1}')" "$DEST/mdc-${TYPE}-${STAMP}.gz.enc" > "$DEST/mdc-${TYPE}-${STAMP}.sha256"
find "$DEST" -name 'mdc-*.gz.enc' -mtime +"$RETENTION_DAYS" -delete
find "$DEST" -name 'mdc-*.sha256' -mtime +"$RETENTION_DAYS" -delete
echo "encrypted backup verified: $DEST/mdc-${TYPE}-${STAMP}.gz.enc"
