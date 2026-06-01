"""add reputation_actions table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-01
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'reputation_actions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action_type', sa.String(40), nullable=False),
        sa.Column('score_delta', sa.Integer, nullable=False),
        sa.Column('alarm_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_reputation_actions_user_id', 'reputation_actions', ['user_id'])


def downgrade():
    op.drop_index('ix_reputation_actions_user_id', table_name='reputation_actions')
    op.drop_table('reputation_actions')
