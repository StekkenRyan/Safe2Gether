#!/usr/bin/env bash
# promote-replica.sh — Emergency failover: promote this Replica to Primary
#
# Run this on a Replica node when the current Primary has failed and you need
# this node to start accepting writes.
#
# What this script does:
#   1. Promotes the local PostgreSQL replica to primary (pg_ctl promote)
#   2. Removes standby.signal
#   3. Prints the exact steps to update all other nodes
#
# Usage: sudo bash scripts/promote-replica.sh

set -euo pipefail

PG_VERSION=16
PG_DATA="/var/lib/postgresql/${PG_VERSION}/main"
PG_CTL="/usr/lib/postgresql/${PG_VERSION}/bin/pg_ctl"

echo "=== Safe2Gether: Replica Promotion (Emergency Failover) ==="
echo ""
echo "This will promote the local PostgreSQL replica to PRIMARY."
echo "After promotion, this node will accept both reads and writes."
echo ""

# Safety check: is this actually a replica?
IS_REPLICA=$(sudo -u postgres psql -tAc "SELECT pg_is_in_recovery();" 2>/dev/null || echo "error")
if [[ "${IS_REPLICA}" != "t" ]]; then
  echo "ERROR: This node does not appear to be a replica (pg_is_in_recovery() = ${IS_REPLICA})."
  echo "       Either PostgreSQL is not running, or this is already a Primary."
  exit 1
fi

THIS_IP=$(tailscale ip -4 2>/dev/null || hostname -I | awk '{print $1}')

echo "Current Tailscale IP of this node: ${THIS_IP}"
echo ""
read -r -p "Confirm promotion? This action cannot be undone easily. [y/N] " confirm
[[ "${confirm}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

# ─── Promote ──────────────────────────────────────────────────────────────────
echo ""
echo "[1/2] Promoting replica to primary..."
sudo -u postgres "${PG_CTL}" promote -D "${PG_DATA}"
sleep 2

# Verify
IS_RECOVERY=$(sudo -u postgres psql -tAc "SELECT pg_is_in_recovery();" 2>/dev/null)
if [[ "${IS_RECOVERY}" == "f" ]]; then
  echo "    -> Promotion successful. This node is now PRIMARY."
else
  echo "ERROR: Promotion may have failed. pg_is_in_recovery() = ${IS_RECOVERY}"
  exit 1
fi

# ─── Print next steps ─────────────────────────────────────────────────────────
echo ""
echo "[2/2] Printing required follow-up actions..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "REQUIRED: Update DATABASE_URL on ALL Flask nodes"
echo ""
echo "  Edit the .env file on each node and change DATABASE_URL to:"
echo "  DATABASE_URL=postgresql://safe2gether:<password>@${THIS_IP}:5432/safe2gether"
echo ""
echo "  Then restart the API container:"
echo "  docker-compose restart api"
echo ""
echo "OPTIONAL: Re-configure remaining nodes as replicas of this new primary"
echo ""
echo "  On each node that should replicate from here, run:"
echo "  sudo bash scripts/setup-replica.sh"
echo "  (Enter this node's IP: ${THIS_IP} as the Primary IP)"
echo ""
echo "WHEN old Primary recovers:"
echo "  Do NOT start it as Primary again — it will conflict."
echo "  Either: run setup-replica.sh on it to join as a new replica,"
echo "  or:     keep it offline until you are ready to re-integrate."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
