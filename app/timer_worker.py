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
from datetime import datetime, timedelta, timezone

from flask import Flask
from sqlalchemy import update

from .db import db
from .models import SafetyTimer, User
from .notifications import send_alarm_update, send_timer_checkin_request

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECS = 30.0


def _claim_timer(timer_id: str, from_status: str, to_status: str, **values) -> bool:
    """Atomically transition a timer's status. Returns True iff this worker won
    the transition (``rowcount == 1``).

    This compare-and-set is what makes the timer escalation safe even if more
    than one worker polls concurrently: only the worker whose UPDATE actually
    flips the status proceeds to send the push, so a check-in request / trigger
    fires exactly once.
    """
    result = db.session.execute(
        update(SafetyTimer)
        .where(SafetyTimer.id == timer_id, SafetyTimer.status == from_status)
        .values(status=to_status, **values)
    )
    db.session.commit()
    return result.rowcount == 1


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
        # Capture everything we need BEFORE the claim commit expires the ORM row.
        timer_id = timer.id
        user_id = timer.user_id
        note = timer.note
        user = db.session.get(User, user_id)
        device_token = user.apns_device_token if user else None
        environment = (user.apns_environment or 'sandbox') if user else 'sandbox'

        if not device_token:
            if _claim_timer(timer_id, 'active', 'triggered'):
                logger.info(
                    'timer_no_device_token user=%s timer=%s — marking triggered',
                    user_id, timer_id,
                )
            continue

        # Only the worker that wins the atomic active→checkin_requested claim
        # sends the push; a concurrent worker sees rowcount 0 and skips.
        if _claim_timer(timer_id, 'active', 'checkin_requested', checkin_requested_at=now):
            send_timer_checkin_request(device_token, environment, timer_id, note=note)
            logger.info('timer_checkin_requested user=%s timer=%s', user_id, timer_id)


def _step_trigger(now: datetime) -> None:
    """Notify contacts (and community) for timers past the grace period."""
    grace = SafetyTimer.GRACE_PERIOD_SECONDS

    expired_cr = SafetyTimer.query.filter(
        SafetyTimer.status == 'checkin_requested',
        SafetyTimer.checkin_requested_at <= now - timedelta(seconds=grace),
    ).all()

    for timer in expired_cr:
        # Capture before claim (commit expires ORM attributes).
        timer_id = timer.id
        user_id = timer.user_id
        contact_ids = [c for c in (timer.notify_contact_ids or '').split(',') if c]
        notify_community = timer.notify_community

        # Win the atomic checkin_requested→triggered claim or skip.
        if not _claim_timer(timer_id, 'checkin_requested', 'triggered'):
            continue

        user = db.session.get(User, user_id)
        owner_name = (user.email if user else None) or 'Jemand'

        # Notify each selected in_app contact
        for contact_user_id in contact_ids:
            contact_user = db.session.get(User, contact_user_id)
            if contact_user and contact_user.apns_device_token:
                send_alarm_update(
                    contact_user.apns_device_token,
                    contact_user.apns_environment or 'sandbox',
                    timer_id,
                    event='timer_triggered',
                    body=f'{owner_name} hat sich nicht gemeldet — bitte check nach!',
                )

        logger.info('timer_triggered user=%s timer=%s contacts=%d community=%s',
                    user_id, timer_id, len(contact_ids), notify_community)


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
