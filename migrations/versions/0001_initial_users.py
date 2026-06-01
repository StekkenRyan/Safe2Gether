"""initial users table

Revision ID: 0001
Revises:
Create Date: 2026-06-01
"""
import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('auth_provider', sa.String(20), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('password_hash', sa.String(255), nullable=True),
        sa.Column('apple_sub', sa.String(255), nullable=True),
        sa.Column('google_sub', sa.String(255), nullable=True),
        sa.Column('phone_number', sa.String(30), nullable=True),
        sa.Column('phone_verified', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('apns_device_token', sa.String(200), nullable=True),
        sa.Column('apns_environment', sa.String(20), nullable=True),
        sa.Column('reputation_score', sa.Integer, nullable=False, server_default='0'),
        sa.Column('reputation_level', sa.String(20), nullable=False, server_default='normal'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('scheduled_deletion_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_users_apple_sub', 'users', ['apple_sub'], unique=True)
    op.create_index('ix_users_google_sub', 'users', ['google_sub'], unique=True)

    # Partial unique index: email uniqueness only within email provider
    op.create_index(
        'uq_users_email_provider', 'users', ['email'],
        unique=True,
        postgresql_where=sa.text("auth_provider = 'email'"),
    )


def downgrade():
    op.drop_index('uq_users_email_provider', table_name='users')
    op.drop_index('ix_users_google_sub', table_name='users')
    op.drop_index('ix_users_apple_sub', table_name='users')
    op.drop_table('users')
