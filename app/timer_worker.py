"""Background worker for Dead Man's Switch timer escalation.

Poll interval: 30 s (coarser than the escalation worker — timers are measured
in minutes, not seconds, so sub-second precision is not needed).

Escalation sequence for an expired timer:
  1. expires_at reached → send checkin-request push to owner, set status=checkin_requested
  2. checkin_requested_at + GRACE_PERIOD_SECONDS reached → notify contacts (and
     community if opted in), set status=triggered
"""
import logging
import threading
import time
from datetime import datetime, timezone

from flask import Flask

from .db import db
from .models import SafetyTimer, User
from .notifications import send_alarm_update, send_nearby_alert, send_timer_checkin_request

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECS = 30.0


def _run_escalation(app: Flask) -> None:
    with app.app_context():
        now = datetime.now(timezone.utc)
        try:
            _step_checkin_request(now)
            _step_trigger(now)
        except Exception:
            logger.exception('timer worker escalation step crashed')
        finally:
            try:
                db.session.remove()
            except Exception:
                pass


def _step_checkin_request(now: datetime) -> None:
    """Send check-in push to timers that have just expired."""
    due = SafetyTimer.query.filter(
        SafetyTimer.status == 'active',
        SafetyTimer.expires_at <= now,
    ).all()

    for timer in due:
        user = db.session.get(User, timer.user_id)
        if not user or not user.apns_device_token:
            timer.status = 'triggered'
            logger.info('timer_no_device_token user=%s timer=%s — marking triggered', timer.user_id, timer.id)
            db.session.commit()
            continue

        timer.status = 'checkin_requested'
        timer.checkin_requested_at = now
        db.session.commit()

        send_timer_checkin_request(
            user.apns_device_token,
            user.apns_environment or 'sandbox',
            timer.id,
            note=timer.note,
        )
        logger.info('timer_checkin_requested user=%s timer=%s', timer.user_id, timer.id)


def _step_trigger(now: datetime) -> None:
    """Notify contacts (and community) for timers past the grace period."""
    from datetime import timedelta
    grace = SafetyTimer.GRACE_PERIOD_SECONDS

    expired_cr = SafetyTimer.query.filter(
        SafetyTimer.status == 'checkin_requested',
        SafetyTimer.checkin_requested_at <= now - timedelta(seconds=grace),
    ).all()

    for timer in expired_cr:
        timer.status = 'triggered'
        db.session.commit()

        user = db.session.get(User, timer.user_id)
        owner_name = (user.email if user else None) or 'Jemand'

        # Notify each selected in_app contact
        contact_ids = [c for c in (timer.notify_contact_ids or '').split(',') if c]
        for contact_user_id in contact_ids:
            contact_user = db.session.get(User, contact_user_id)
            if contact_user and contact_user.apns_device_token:
                send_alarm_update(
                    contact_user.apns_device_token,
                    contact_user.apns_environment or 'sandbox',
                    timer.id,
                    event='timer_triggered',
                    body=f'{owner_name} hat sich nicht gemeldet — bitte check nach!',
                )

        logger.info('timer_triggered user=%s timer=%s contacts=%d community=%s',
                    timer.user_id, timer.id, len(contact_ids), timer.notify_community)


def _worker_loop(app: Flask) -> None:
    logger.info('timer worker starting (poll=%.0fs)', _POLL_INTERVAL_SECS)
    while True:
        try:
            _run_escalation(app)
        except Exception:
            logger.exception('timer worker iteration crashed')
        time.sleep(_POLL_INTERVAL_SECS)


def start_worker(app: Flask) -> None:
    """Spawn daemon thread. No-op in TESTING mode."""
    if app.config.get('TESTING'):
        return
    thread = threading.Thread(target=_worker_loop, args=(app,), daemon=True,
                              name='timer-worker')
    thread.start()
