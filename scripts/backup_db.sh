#!/usr/bin/env bash
set -euo pipefail

: "${DB_NAME:?Defina DB_NAME}"
: "${DB_USER:?Defina DB_USER}"

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/school_guard}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
MYSQL_CONFIG="${MYSQL_CONFIG:-}"

if [[ -n "$MYSQL_CONFIG" && ! -r "$MYSQL_CONFIG" ]]; then
    echo "No se puede leer MYSQL_CONFIG: $MYSQL_CONFIG" >&2
    exit 1
fi

umask 077
mkdir -p "$BACKUP_DIR"

defaults_args=()
if [[ -n "$MYSQL_CONFIG" ]]; then
    defaults_args=(--defaults-extra-file="$MYSQL_CONFIG")
fi

timestamp="$(date +%Y-%m-%d_%H%M%S)"
target="$BACKUP_DIR/${DB_NAME}_${timestamp}.sql.gz"
tmp="$target.tmp"
trap 'rm -f "$tmp"' EXIT

mysqldump "${defaults_args[@]}" \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --single-transaction \
    --quick \
    --routines \
    --triggers \
    --default-character-set=utf8mb4 \
    "$DB_NAME" | gzip -c > "$tmp"

gzip -t "$tmp"
mv "$tmp" "$target"
find "$BACKUP_DIR" -type f -name "${DB_NAME}_*.sql.gz" -mtime +"$RETENTION_DAYS" -delete

echo "Backup creado: $target"
