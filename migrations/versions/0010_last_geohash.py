"""add last_geohash to users

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-09

Persists the user's last known H3 cell so debug distance calculations
remain accurate after the Redis TTL has expired.
"""
import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('last_geohash', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('users', 'last_geohash')
