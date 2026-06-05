"""add alert_type/audience to alarms; create safety_timers table

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-05

Adds alert_type, audience, home_distance_category to existing alarms rows
(all default to 'panic' / 'contacts_and_community' / NULL respectively).
Creates the safety_timers table for the Dead Man's Switch feature (v1.2).
"""
import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('alarms', sa.Column(
        'alert_type', sa.String(30), nullable=False, server_default='panic'
    ))
    op.add_column('alarms', sa.Column(
        'audience', sa.String(30), nullable=False,
        server_default='contacts_and_community',
    ))
    op.add_column('alarms', sa.Column(
        'home_distance_category', sa.String(20), nullable=True
    ))

    op.create_table(
        'safety_timers',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'user_id', sa.String(36),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('duration_seconds', sa.Integer, nullable=False),
        sa.Column('expires_at', sa.DateTime, nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='active'),
        sa.Column('notify_contact_ids', sa.Text, nullable=True),
        sa.Column(
            'notify_community', sa.Boolean, nullable=False, server_default='false'
        ),
        sa.Column('note', sa.String(200), nullable=True),
        sa.Column('checkin_requested_at', sa.DateTime, nullable=True),
        sa.Column(
            'created_at', sa.DateTime, nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index('ix_safety_timers_user_id', 'safety_timers', ['user_id'])
    op.create_index('ix_safety_timers_status', 'safety_timers', ['status'])


def downgrade():
    op.drop_index('ix_safety_timers_status', table_name='safety_timers')
    op.drop_index('ix_safety_timers_user_id', table_name='safety_timers')
    op.drop_table('safety_timers')
    op.drop_column('alarms', 'home_distance_category')
    op.drop_column('alarms', 'audience')
    op.drop_column('alarms', 'alert_type')
