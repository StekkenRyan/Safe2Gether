#!/usr/bin/env bash
# setup-primary.sh — Configure PostgreSQL as the replication Primary
#
# Run this ONCE on the node that should hold the Primary database.
# Prerequisites: PostgreSQL 16 installed natively (not in Docker).
# Tested on: Raspberry Pi OS (Debian 12), Ubuntu 22.04+
#
# Usage: sudo bash scripts/setup-primary.sh

set -euo pipefail

PG_VERSION=16
PG_CONF="/etc/postgresql/${PG_VERSION}/main/postgresql.conf"
PG_HBA="/etc/postgresql/${PG_VERSION}/main/pg_hba.conf"
REPLICATION_USER="replicator"

# ─── Tailscale subnet for replication access ──────────────────────────────────
# Tailscale uses 100.64.0.0/10. Adjust if you use a custom subnet.
TAILSCALE_SUBNET="100.64.0.0/10"

echo "=== Safe2Gether: PostgreSQL Primary Setup ==="
echo ""
echo "PostgreSQL version : ${PG_VERSION}"
echo "Config file        : ${PG_CONF}"
echo "Replication user   : ${REPLICATION_USER}"
echo "Allowed subnet     : ${TAILSCALE_SUBNET} (Tailscale)"
echo ""
read -r -p "Continue? [y/N] " confirm
[[ "${confirm}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# ─── 1. postgresql.conf — enable replication ──────────────────────────────────
echo ""
echo "[1/4] Configuring postgresql.conf..."

# Backup original
cp "${PG_CONF}" "${PG_CONF}.backup-$(date +%Y%m%d%H%M%S)"

# Apply settings (append if not already set)
grep -q "^wal_level" "${PG_CONF}" \
  && sed -i "s/^wal_level.*/wal_level = replica/" "${PG_CONF}" \
  || echo "wal_level = replica" >> "${PG_CONF}"

grep -q "^max_wal_senders" "${PG_CONF}" \
  && sed -i "s/^max_wal_senders.*/max_wal_senders = 5/" "${PG_CONF}" \
  || echo "max_wal_senders = 5" >> "${PG_CONF}"

grep -q "^wal_keep_size" "${PG_CONF}" \
  && sed -i "s/^wal_keep_size.*/wal_keep_size = 256/" "${PG_CONF}" \
  || echo "wal_keep_size = 256" >> "${PG_CONF}"

grep -q "^listen_addresses" "${PG_CONF}" \
  && sed -i "s/^listen_addresses.*/listen_addresses = '*'/" "${PG_CONF}" \
  || echo "listen_addresses = '*'" >> "${PG_CONF}"

echo "    -> postgresql.conf updated."

# ─── 2. pg_hba.conf — allow replication from Tailscale subnet ────────────────
echo ""
echo "[2/4] Configuring pg_hba.conf..."

cp "${PG_HBA}" "${PG_HBA}.backup-$(date +%Y%m%d%H%M%S)"

REPLICATION_RULE="host    replication     ${REPLICATION_USER}     ${TAILSCALE_SUBNET}     scram-sha-256"
if ! grep -qF "${REPLICATION_USER}" "${PG_HBA}"; then
  echo "" >> "${PG_HBA}"
  echo "# Safe2Gether streaming replication via Tailscale" >> "${PG_HBA}"
  echo "${REPLICATION_RULE}" >> "${PG_HBA}"
  echo "    -> Replication rule added to pg_hba.conf."
else
  echo "    -> Replication rule already present, skipping."
fi

# ─── 3. Create replication user ───────────────────────────────────────────────
echo ""
echo "[3/4] Creating replication user '${REPLICATION_USER}'..."

read -r -s -p "    Enter password for '${REPLICATION_USER}': " REPL_PASS
echo ""

sudo -u postgres psql -c "
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${REPLICATION_USER}') THEN
      CREATE ROLE ${REPLICATION_USER} WITH REPLICATION LOGIN PASSWORD '${REPL_PASS}';
      RAISE NOTICE 'Role ${REPLICATION_USER} created.';
    ELSE
      ALTER ROLE ${REPLICATION_USER} WITH PASSWORD '${REPL_PASS}';
      RAISE NOTICE 'Role ${REPLICATION_USER} already exists — password updated.';
    END IF;
  END
  \$\$;
"

echo "    -> Replication user configured."

# ─── 4. Restart PostgreSQL ────────────────────────────────────────────────────
echo ""
echo "[4/4] Restarting PostgreSQL..."
systemctl restart "postgresql@${PG_VERSION}-main"
echo "    -> PostgreSQL restarted."

echo ""
echo "=== Primary setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Note this node's Tailscale IP: $(tailscale ip -4 2>/dev/null || echo '<run: tailscale ip -4>')"
echo "  2. On each Replica node, run: sudo bash scripts/setup-replica.sh"
echo "  3. Verify replication status after replica setup:"
echo "     sudo -u postgres psql -c \"SELECT * FROM pg_stat_replication;\""
