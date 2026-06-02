"""user-configurable escalation chain

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-02

Adds escalation_order and escalation_delay_seconds to users. Stored on the
user row because the chain is small and always read in a single shot with
the rest of the profile.
"""
import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None

_DEFAULT_ORDER = 'device_local,contacts,community'
_DEFAULT_DELAY = 30


def upgrade():
    op.add_column('users', sa.Column(
        'escalation_order', sa.Text, nullable=False, server_default=_DEFAULT_ORDER
    ))
    op.add_column('users', sa.Column(
        'escalation_delay_seconds', sa.Integer, nullable=False,
        server_default=str(_DEFAULT_DELAY),
    ))


def downgrade():
    op.drop_column('users', 'escalation_delay_seconds')
    op.drop_column('users', 'escalation_order')
