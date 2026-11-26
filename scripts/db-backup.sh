#!/usr/bin/env bash
#
# Backup database MySQL Kampung Merak.
#
# Dipakai sebelum migrasi apapun (lihat fastapi-backend/app/migrate.py) dan
# aman dijadwalkan lewat cron. Kredensial root diambil dari dalam container
# mysql — TIDAK ditulis di berkas ini maupun di repo.
#
# Pemakaian:
#   ./scripts/db-backup.sh                  # backup ke backups/*.sql.gz
#   BACKUP_KEEP=14 ./scripts/db-backup.sh    # simpan 14 file terakhir
#   ./scripts/db-backup.sh --restore FILE   # pulihkan (menimpa database!)
#
set -euo pipefail

CONTAINER="${MYSQL_CONTAINER:-merak-mysql}"
DB="${MYSQL_DATABASE:-kampung_merak}"
BACKUP_DIR="${BACKUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backups}"
KEEP="${BACKUP_KEEP:-7}"

log() { printf '[backup] %s\n' "$*" >&2; }

usage() {
  cat >&2 <<'USAGE'
Pemakaian:
  db-backup.sh                  Backup ke backups/merak-<waktu>.sql.gz
  db-backup.sh --restore FILE   Restore FILE ke database (menimpa data!)
USAGE
  exit 1
}

[[ "${1:-}" == "--help" || "${1:-}" == "-h" ]] && usage
if [[ "${1:-}" == "--restore" ]]; then
  FILE="${2:-}"
  [[ -n "$FILE" && -f "$FILE" ]] || usage
  log "MEMULIHKAN $FILE ke database '$DB' (semua data saat ini ditimpa)"
  if [[ "$FILE" == *.gz ]]; then
    gzip -dc "$FILE" | docker exec -i "$CONTAINER" sh -c \
      'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" '"$DB"
  else
    docker exec -i "$CONTAINER" sh -c \
      'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" '"$DB" < "$FILE"
  fi
  log "Restore selesai."
  exit 0
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/merak-$STAMP.sql.gz"

log "Container $CONTAINER, database $DB"
docker exec -i "$CONTAINER" sh -c \
  'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction --quick \
   --routines --triggers --events '"$DB" | gzip > "$OUT"

# Verifikasi arsipnya benar-benar bisa dibaca sebelum klaim berhasil.
gzip -t "$OUT"
BYTES=$(wc -c < "$OUT")
log "Tersimpan: $OUT ($BYTES byte)"

# Buang backup paling lama agar tidak menumpuk.
mapfile -t FILES < <(ls -1t "$BACKUP_DIR"/merak-*.sql.gz 2>/dev/null || true)
if (( ${#FILES[@]} > KEEP )); then
  for (( i = KEEP; i < ${#FILES[@]}; i++ )); do
    rm -f "${FILES[i]}"
    log "Buang (retensi $KEEP): ${FILES[i]}"
  done
fi
log "Selesai (${#FILES[@]} backup tersimpan)."
