#!/usr/bin/env bash
# backup.sh — PostgreSQL dump backup
#
# Creates a compressed pg_dump of the safe2gether database.
# Designed to run via cron or `make backup`.
#
# Cron example (daily at 03:00):
#   0 3 * * * /path/to/ServerCode/scripts/backup.sh >> /var/log/safe2gether-backup.log 2>&1
#
# If a NAS is mounted, set BACKUP_DIR to its mount point to store backups there.
# Example: BACKUP_DIR=/mnt/nas/backups/safe2gether
#
# Usage: bash scripts/backup.sh
#        BACKUP_DIR=/mnt/nas/backups bash scripts/backup.sh

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/var/backups/safe2gether}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"
DB_NAME="${DB_NAME:-safe2gether}"
DB_USER="${DB_USER:-safe2gether}"
# DATABASE_URL can override DB_NAME/DB_USER if set
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.dump"

# ─── Ensure backup directory exists ──────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup of '${DB_NAME}'..."
echo "  Output : ${BACKUP_FILE}"
echo "  Retain : ${RETAIN_DAYS} days"

# ─── Detect environment: Docker or native ────────────────────────────────────
if docker-compose ps postgres 2>/dev/null | grep -q "Up"; then
  # Running inside Docker Compose environment
  docker-compose exec -T postgres pg_dump \
    --username="${DB_USER}" \
    --format=custom \
    --compress=9 \
    "${DB_NAME}" > "${BACKUP_FILE}"
else
  # Native PostgreSQL
  sudo -u postgres pg_dump \
    --format=custom \
    --compress=9 \
    --dbname="${DB_NAME}" > "${BACKUP_FILE}"
fi

BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup complete. Size: ${BACKUP_SIZE}"

# ─── Remove old backups ───────────────────────────────────────────────────────
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Removing backups older than ${RETAIN_DAYS} days..."
find "${BACKUP_DIR}" -name "${DB_NAME}_*.dump" -mtime "+${RETAIN_DAYS}" -delete
REMAINING=$(find "${BACKUP_DIR}" -name "${DB_NAME}_*.dump" | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done. ${REMAINING} backup(s) retained."

# ─── Restore instructions (printed to log for reference) ─────────────────────
cat <<EOF

To restore this backup:
  pg_restore --clean --if-exists --username=${DB_USER} --dbname=${DB_NAME} ${BACKUP_FILE}

  Or with Docker:
  docker-compose exec -T postgres pg_restore \\
    --clean --if-exists --username=${DB_USER} --dbname=${DB_NAME} < ${BACKUP_FILE}

EOF
