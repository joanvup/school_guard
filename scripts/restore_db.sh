#!/usr/bin/env bash
set -euo pipefail

: "${DB_NAME:?Defina DB_NAME}"
: "${DB_USER:?Defina DB_USER}"

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
MYSQL_CONFIG="${MYSQL_CONFIG:-}"
backup_file="${1:-}"

if [[ "${CONFIRM_RESTORE:-}" != "YES" ]]; then
    echo "Restore bloqueado. Exporte CONFIRM_RESTORE=YES y detenga la aplicación primero." >&2
    exit 1
fi

if [[ -z "$backup_file" || ! -r "$backup_file" ]]; then
    echo "Uso: CONFIRM_RESTORE=YES $0 /ruta/al/backup.sql.gz" >&2
    exit 1
fi

if [[ -n "$MYSQL_CONFIG" && ! -r "$MYSQL_CONFIG" ]]; then
    echo "No se puede leer MYSQL_CONFIG: $MYSQL_CONFIG" >&2
    exit 1
fi

gzip -t "$backup_file"

defaults_args=()
if [[ -n "$MYSQL_CONFIG" ]]; then
    defaults_args=(--defaults-extra-file="$MYSQL_CONFIG")
fi

echo "Restaurando $backup_file en la base $DB_NAME ($DB_HOST:$DB_PORT)..."
gzip -dc "$backup_file" | mysql "${defaults_args[@]}" \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    "$DB_NAME"

echo "Restore completado. Verifique /healthz y el smoke test antes de reabrir el servicio."
