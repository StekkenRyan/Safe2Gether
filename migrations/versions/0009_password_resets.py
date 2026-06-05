"""add password_resets table

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-05
"""
import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'password_resets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'user_id', sa.String(36),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('token_hash', sa.Text, nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('used_at', sa.DateTime, nullable=True),
    )
    op.create_index('ix_password_resets_user_id', 'password_resets', ['user_id'])


def downgrade():
    op.drop_index('ix_password_resets_user_id', table_name='password_resets')
    op.drop_table('password_resets')
