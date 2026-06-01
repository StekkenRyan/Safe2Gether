"""Scheduled data cleanup — DSGVO Art. 17 enforcement.

Register Flask CLI commands that a cron job calls daily:
  flask cleanup users    → permanently delete accounts past grace period
  flask cleanup alarms   → purge alarm records past 30-day retention
  flask cleanup reputation → purge reputation actions past 30-day retention

Cron example (4:00 AM daily):
  0 4 * * * cd /app && flask cleanup users && flask cleanup alarms && flask cleanup reputation
"""
import logging
import os

import click
import redis as redis_lib
from flask import Flask

from .db import db
from .redis_keys import GEO_USER, HB

logger = logging.getLogger(__name__)


def _redis():
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def register_commands(app: Flask) -> None:
    @app.cli.group()
    def cleanup():
        """DSGVO data retention cleanup commands."""

    @cleanup.command('users')
    def cleanup_users():
        """Hard-delete user accounts that have passed their grace period."""
        from datetime import datetime, timezone

        from .models import User
        now = datetime.now(timezone.utc)
        expired = User.query.filter(
            User.is_active.is_(False),
            User.scheduled_deletion_at <= now,
        ).all()

        r = _redis()
        deleted = 0
        for user in expired:
            # Clean Redis keys before DB deletion
            try:
                r.delete(f'{GEO_USER}{user.id}', f'{HB}{user.id}')
            except redis_lib.RedisError:
                pass
            db.session.delete(user)
            deleted += 1

        db.session.commit()
        click.echo(f'Deleted {deleted} expired user account(s).')
        logger.info('cleanup_users: deleted %d accounts', deleted)

    @cleanup.command('alarms')
    def cleanup_alarms():
        """Delete alarm records past their 30-day retention period."""
        from datetime import datetime, timezone

        from sqlalchemy import delete as sa_delete

        from .models import Alarm
        now = datetime.now(timezone.utc)
        result = db.session.execute(
            sa_delete(Alarm).where(Alarm.auto_delete_at <= now)
        )
        db.session.commit()
        click.echo(f'Deleted {result.rowcount} expired alarm record(s).')
        logger.info('cleanup_alarms: deleted %d records', result.rowcount)

    @cleanup.command('reputation')
    def cleanup_reputation():
        """Delete reputation actions past their 30-day retention period."""
        from datetime import datetime, timezone

        from sqlalchemy import delete as sa_delete

        from .models import ReputationAction
        now = datetime.now(timezone.utc)
        result = db.session.execute(
            sa_delete(ReputationAction).where(ReputationAction.auto_delete_at <= now)
        )
        db.session.commit()
        click.echo(f'Deleted {result.rowcount} expired reputation action(s).')
        logger.info('cleanup_reputation: deleted %d records', result.rowcount)
