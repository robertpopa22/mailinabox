#!/bin/bash
# Nightly PostgreSQL dump of the `ges_mail` database (custom format) +
# retention prune (delete dumps older than RETENTION_DAYS).
# (DB renamed emails -> ges_mail 2026-06-19; unit name pg-backup-emails kept.)
#
# Run as user `postgres` via systemd timer (pg-backup-emails.timer).
# Output: /home/user-data/pg-backup/ges_mail-YYYY-MM-DD.dump
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/home/user-data/pg-backup}"
DB_NAME="${DB_NAME:-ges_mail}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
# Space-separated tables whose DATA is left out of the dump (their schema is kept). Used for data that is regenerable
# and large: the B6 semantic index (mail_chunk / mail_chunk_state from the maildir, vec_* by re-embedding on LLM01).
# The VM itself is covered by Synology ABB + Hyper-V Replica. (14.10.2026: with the vectors the dump overran 2 h.)
EXCLUDE_TABLE_DATA="${EXCLUDE_TABLE_DATA:-}"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

STAMP="$(date +%F)"
OUT_FILE="$BACKUP_DIR/${DB_NAME}-${STAMP}.dump"
TMP_FILE="${OUT_FILE}.partial"

echo "[$(date -Iseconds)] pg_dump $DB_NAME -> $OUT_FILE"

# --format=custom is compressed (zstd-like) + supports parallel restore.
# Local socket auth — User=postgres in the systemd unit means peer auth applies.
EXCLUDE_ARGS=()
for t in $EXCLUDE_TABLE_DATA; do
  EXCLUDE_ARGS+=("--exclude-table-data=$t")
done
if [ ${#EXCLUDE_ARGS[@]} -gt 0 ]; then
  echo "[$(date -Iseconds)] data excluded (schema kept): $EXCLUDE_TABLE_DATA"
fi

pg_dump \
  --format=custom \
  "${EXCLUDE_ARGS[@]}" \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="$TMP_FILE" \
  "$DB_NAME"

mv -f "$TMP_FILE" "$OUT_FILE"
chmod 600 "$OUT_FILE"

SIZE="$(stat -c %s "$OUT_FILE" 2>/dev/null || echo 0)"
echo "[$(date -Iseconds)] dump complete: $OUT_FILE ($SIZE bytes)"

echo "[$(date -Iseconds)] pruning dumps older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -maxdepth 1 -type f \
  -name "${DB_NAME}-*.dump" \
  -mtime "+${RETENTION_DAYS}" \
  -print -delete || true

# Also clean up any leftover .partial files older than 1 day
find "$BACKUP_DIR" -maxdepth 1 -type f -name "*.partial" -mtime +1 -print -delete || true

echo "[$(date -Iseconds)] done."
