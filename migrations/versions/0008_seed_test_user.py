"""seed debug test account (kontakt@safe2gether.de)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-05

Seeds the fixed-UUID demo account used by iOS debug injection endpoints.
Idempotent: SELECT-before-INSERT, no-op if the row already exists (e.g. dev).
downgrade is intentionally a no-op — never delete accounts in a migration.
"""
import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

_TEST_USER_ID = '0d9d31df-6bea-49bc-849b-36746be384d4'
_TEST_USER_EMAIL = 'kontakt@safe2gether.de'


def upgrade():
    conn = op.get_bind()
    existing = conn.execute(
        sa.text('SELECT id FROM users WHERE id = :id'),
        {'id': _TEST_USER_ID},
    ).fetchone()
    if existing is None:
        conn.execute(
            sa.text(
                'INSERT INTO users (id, auth_provider, email) '
                'VALUES (:id, :auth_provider, :email)'
            ),
            {
                'id': _TEST_USER_ID,
                'auth_provider': 'email',
                'email': _TEST_USER_EMAIL,
            },
        )


def downgrade():
    pass  # never delete accounts in a migration
