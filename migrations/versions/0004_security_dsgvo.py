"""security and DSGVO compliance improvements

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-01

Changes:
- User: add nearby_alerting_enabled (Art. 21 opt-out)
- ReputationAction: add auto_delete_at (Art. 5 storage limitation)
- AlarmResponder: composite PK already acts as unique constraint (no change needed)
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    # Art. 21 DSGVO: nearby alerting opt-out
    op.add_column('users', sa.Column(
        'nearby_alerting_enabled', sa.Boolean, nullable=False, server_default='true'
    ))

    # Art. 5 DSGVO: reputation actions retention limit
    op.add_column('reputation_actions', sa.Column(
        'auto_delete_at', sa.DateTime, nullable=True
    ))
    # Backfill existing rows: set auto_delete_at to 30 days from created_at
    op.execute(
        "UPDATE reputation_actions SET auto_delete_at = created_at + INTERVAL '30 days' "
        "WHERE auto_delete_at IS NULL"
    )
    # SQLite fallback for tests
    try:
        op.alter_column('reputation_actions', 'auto_delete_at', nullable=False)
    except Exception:
        pass


def downgrade():
    op.drop_column('reputation_actions', 'auto_delete_at')
    op.drop_column('users', 'nearby_alerting_enabled')
