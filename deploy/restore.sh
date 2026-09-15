#!/bin/sh
# Restore one encrypted backup after validating its checksum and compressed payload.
set -eu
umask 077

BACKUP=${1:-}
KEY=${BACKUP_ENCRYPTION_KEY:-}
[ -n "$BACKUP" ] || { echo "usage: BACKUP_ENCRYPTION_KEY=... $0 /path/to/backup.gz.enc" >&2; exit 2; }
[ -f "$BACKUP" ] || { echo "backup not found: $BACKUP" >&2; exit 1; }
[ -n "$KEY" ] || { echo 'BACKUP_ENCRYPTION_KEY is required' >&2; exit 2; }
command -v openssl >/dev/null 2>&1 || { echo 'openssl is required' >&2; exit 2; }

if [ -f "${BACKUP%.gz.enc}.sha256" ]; then
  expected=$(awk '{print $1}' "${BACKUP%.gz.enc}.sha256")
  actual=$(sha256sum "$BACKUP" | awk '{print $1}')
  [ "$expected" = "$actual" ] || { echo 'backup checksum mismatch' >&2; exit 1; }
fi

TMP=$(mktemp)
trap 'rm -f "$TMP" "$TMP.gz"' EXIT INT TERM
openssl enc -d -aes-256-cbc -pbkdf2 -pass "pass:$KEY" -in "$BACKUP" -out "$TMP.gz"
gzip -t "$TMP.gz"
gzip -dc "$TMP.gz" > "$TMP"

case "$BACKUP" in
  *postgres*)
    command -v psql >/dev/null 2>&1 || { echo 'psql is required for PostgreSQL restore' >&2; exit 2; }
    psql "$DATABASE_URL" < "$TMP"
    ;;
  *sqlite*)
    DEST=${SQLITE_DB_PATH:-${DATA_DIR:-.}/erp.db}
    mkdir -p "$(dirname "$DEST")"
    cp "$TMP" "$DEST"
    ;;
  *)
    echo 'backup filename must include postgres or sqlite' >&2
    exit 2
    ;;
esac
printf 'restore completed and compressed payload validated: %s\n' "$BACKUP"
