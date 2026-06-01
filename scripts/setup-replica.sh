#!/usr/bin/env bash
# setup-replica.sh — Configure PostgreSQL as a Streaming Replication Replica
#
# Run this on every node that should mirror the Primary (Office Server, Hetzner VPS, NAS).
# WARNING: This will OVERWRITE the local PostgreSQL data directory with a copy from the Primary.
#
# Prerequisites:
#   - PostgreSQL 16 installed natively on this node
#   - Primary node already set up with setup-primary.sh
#   - Both nodes connected via Tailscale (can reach each other at 100.x.x.x)
#
# Usage: sudo bash scripts/setup-replica.sh

set -euo pipefail

PG_VERSION=16
PG_DATA="/var/lib/postgresql/${PG_VERSION}/main"
PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
REPLICATION_USER="replicator"

echo "=== Safe2Gether: PostgreSQL Replica Setup ==="
echo ""
echo "WARNING: The local PostgreSQL data directory will be replaced"
echo "         with a full copy from the Primary node."
echo ""

read -r -p "Primary node Tailscale IP (e.g. 100.64.0.2): " PRIMARY_IP
read -r -p "Replication user password: " -s REPL_PASS
echo ""

echo ""
echo "Primary IP  : ${PRIMARY_IP}"
echo "Data dir    : ${PG_DATA}"
echo "Replica user: ${REPLICATION_USER}"
echo ""
read -r -p "Continue? This will OVERWRITE local data. [y/N] " confirm
[[ "${confirm}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# ─── 1. Stop PostgreSQL on this replica ───────────────────────────────────────
echo ""
echo "[1/4] Stopping local PostgreSQL..."
systemctl stop "postgresql@${PG_VERSION}-main"
echo "    -> Stopped."

# ─── 2. Clear local data dir and pull base backup from Primary ────────────────
echo ""
echo "[2/4] Pulling base backup from Primary (${PRIMARY_IP})..."
rm -rf "${PG_DATA}"
mkdir -p "${PG_DATA}"
chmod 700 "${PG_DATA}"
chown postgres:postgres "${PG_DATA}"

PGPASSWORD="${REPL_PASS}" sudo -u postgres pg_basebackup \
  --host="${PRIMARY_IP}" \
  --port=5432 \
  --username="${REPLICATION_USER}" \
  --pgdata="${PG_DATA}" \
  --wal-method=stream \
  --checkpoint=fast \
  --progress \
  --verbose

echo "    -> Base backup complete."

# ─── 3. Create standby.signal (tells PostgreSQL to run as hot standby) ────────
echo ""
echo "[3/4] Configuring standby mode..."
sudo -u postgres touch "${PG_DATA}/standby.signal"

# Write primary_conninfo into postgresql.conf
PRIMARY_CONNINFO="host=${PRIMARY_IP} port=5432 user=${REPLICATION_USER} password=${REPL_PASS} application_name=$(hostname)"

if grep -q "^primary_conninfo" "${PG_CONF}"; then
  sed -i "s|^primary_conninfo.*|primary_conninfo = '${PRIMARY_CONNINFO}'|" "${PG_CONF}"
else
  echo "" >> "${PG_CONF}"
  echo "# Safe2Gether replication — added by setup-replica.sh" >> "${PG_CONF}"
  echo "primary_conninfo = '${PRIMARY_CONNINFO}'" >> "${PG_CONF}"
fi

echo "    -> standby.signal created, primary_conninfo written."

# ─── 4. Start PostgreSQL ──────────────────────────────────────────────────────
echo ""
echo "[4/4] Starting PostgreSQL replica..."
systemctl start "postgresql@${PG_VERSION}-main"

echo ""
echo "=== Replica setup complete ==="
echo ""
echo "Verify replication is working:"
echo "  On PRIMARY: sudo -u postgres psql -c \"SELECT application_name, state, sent_lsn, replay_lsn FROM pg_stat_replication;\""
echo "  On REPLICA: sudo -u postgres psql -c \"SELECT pg_is_in_recovery();\""
echo "              (should return 't' = true)"
echo ""
echo "If you need to promote this replica to Primary in an emergency, run:"
echo "  sudo bash scripts/promote-replica.sh"
