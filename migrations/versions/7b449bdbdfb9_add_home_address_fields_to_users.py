"""add home_address fields to users; add home_distance_category to alarms

Revision ID: 7b449bdbdfb9
Revises: 0006
Create Date: 2026-06-05

Adds home_address_label and home_address to users (optional home location for
Dead Man's Switch routing). Adds home_distance_category to alarms (was missing
from the 0006 DDL run on production due to the alembic_version mismatch).
"""
import sqlalchemy as sa
from alembic import op

revision = '7b449bdbdfb9'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('home_address_label', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('home_address', sa.String(300), nullable=True))


def downgrade():
    op.drop_column('users', 'home_address')
    op.drop_column('users', 'home_address_label')
