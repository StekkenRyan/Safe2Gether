"""add error_events table (anonymous monitoring)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-28
"""
import sqlalchemy as sa
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'error_events',
        sa.Column('id', sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('error_code', sa.String(40), nullable=False),
        sa.Column('endpoint', sa.String(200), nullable=True),
        sa.Column('http_status', sa.Integer, nullable=True),
        sa.Column('app_version', sa.String(20), nullable=True),
        sa.Column('os_version', sa.String(20), nullable=True),
        sa.Column('auto_delete_at', sa.DateTime, nullable=False),
    )
    op.create_index('ix_error_events_created_at', 'error_events', ['created_at'])
    op.create_index('ix_error_events_error_code', 'error_events', ['error_code'])


def downgrade():
    op.drop_index('ix_error_events_error_code', table_name='error_events')
    op.drop_index('ix_error_events_created_at', table_name='error_events')
    op.drop_table('error_events')
