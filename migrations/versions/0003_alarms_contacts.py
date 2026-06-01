"""add emergency_contacts, alarms, alarm_responders tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-01
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'emergency_contacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contact_type', sa.String(20), nullable=False),
        sa.Column('contact_value', sa.String(255), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('order_in_escalation', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_emergency_contacts_user_id', 'emergency_contacts', ['user_id'])

    op.create_table(
        'alarms',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('triggered_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column('trigger_source', sa.String(30), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('escalation_stage', sa.String(20), nullable=False,
                  server_default='device_local'),
        sa.Column('geohash_snapshot', sa.String(20), nullable=True),
        sa.Column('exact_latitude', sa.Float, nullable=True),
        sa.Column('exact_longitude', sa.Float, nullable=True),
        sa.Column('auto_delete_at', sa.DateTime, nullable=False),
    )
    op.create_index('ix_alarms_user_id', 'alarms', ['user_id'])
    op.create_index('ix_alarms_status', 'alarms', ['status'])

    op.create_table(
        'alarm_responders',
        sa.Column('alarm_id', sa.String(36),
                  sa.ForeignKey('alarms.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('responded_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('alarm_responders')
    op.drop_index('ix_alarms_status', table_name='alarms')
    op.drop_index('ix_alarms_user_id', table_name='alarms')
    op.drop_table('alarms')
    op.drop_index('ix_emergency_contacts_user_id', table_name='emergency_contacts')
    op.drop_table('emergency_contacts')
