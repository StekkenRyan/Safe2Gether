"""Dead-Man's-Switch timer worker tests — escalation step functions.

Exercises ``app.timer_worker`` directly (not via HTTP), covering the atomic
compare-and-set transitions that keep escalation correct under concurrent
workers (A6). APNs senders are monkeypatched so nothing touches the network or
spawns threads.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import timer_worker
from app.db import db
from app.models import SafetyTimer, User


def _mk_user(app, *, device_token='a' * 64):
    with app.app_context():
        user = User(
            id=str(uuid.uuid4()),
            auth_provider='email',
            email=f'{uuid.uuid4().hex[:8]}@t.example',
            apns_device_token=device_token,
            apns_environment='sandbox',
        )
        db.session.add(user)
        db.session.commit()
        return user.id


def _mk_timer(app, user_id, *, status='active', expires_delta_s=-10,
              checkin_delta_s=None, notify_contact_ids=None):
    with app.app_context():
        now = datetime.now(timezone.utc)
        timer = SafetyTimer(
            id=str(uuid.uuid4()),
            user_id=user_id,
            duration_seconds=600,
            expires_at=now + timedelta(seconds=expires_delta_s),
            status=status,
            notify_contact_ids=notify_contact_ids,
        )
        if checkin_delta_s is not None:
            timer.checkin_requested_at = now + timedelta(seconds=checkin_delta_s)
        db.session.add(timer)
        db.session.commit()
        return timer.id


def _status(app, timer_id):
    with app.app_context():
        return db.session.get(SafetyTimer, timer_id).status


@pytest.fixture
def captured(monkeypatch):
    calls = {'checkin': [], 'alarm_update': []}
    monkeypatch.setattr(timer_worker, 'send_timer_checkin_request',
                        lambda *a, **k: calls['checkin'].append((a, k)))
    monkeypatch.setattr(timer_worker, 'send_alarm_update',
                        lambda *a, **k: calls['alarm_update'].append((a, k)))
    return calls


# ─── _claim_timer (atomic compare-and-set) ────────────────────────────────────

def test_claim_timer_is_compare_and_set(app):
    user_id = _mk_user(app)
    timer_id = _mk_timer(app, user_id, status='active')
    with app.app_context():
        assert timer_worker._claim_timer(timer_id, 'active', 'checkin_requested') is True
        # Source status no longer matches — a second claim must lose.
        assert timer_worker._claim_timer(timer_id, 'active', 'checkin_requested') is False
    assert _status(app, timer_id) == 'checkin_requested'


# ─── _step_checkin_request ────────────────────────────────────────────────────

def test_expired_active_timer_requests_checkin(app, captured):
    user_id = _mk_user(app)
    timer_id = _mk_timer(app, user_id, status='active', expires_delta_s=-5)
    with app.app_context():
        timer_worker._step_checkin_request(datetime.now(timezone.utc))
    assert _status(app, timer_id) == 'checkin_requested'
    assert len(captured['checkin']) == 1


def test_checkin_step_idempotent(app, captured):
    user_id = _mk_user(app)
    timer_id = _mk_timer(app, user_id, status='active', expires_delta_s=-5)
    with app.app_context():
        timer_worker._step_checkin_request(datetime.now(timezone.utc))
        timer_worker._step_checkin_request(datetime.now(timezone.utc))
    assert _status(app, timer_id) == 'checkin_requested'
    assert len(captured['checkin']) == 1  # not sent twice


def test_no_device_token_marks_triggered(app, captured):
    user_id = _mk_user(app, device_token=None)
    timer_id = _mk_timer(app, user_id, status='active', expires_delta_s=-5)
    with app.app_context():
        timer_worker._step_checkin_request(datetime.now(timezone.utc))
    assert _status(app, timer_id) == 'triggered'
    assert captured['checkin'] == []


def test_unexpired_timer_untouched(app, captured):
    user_id = _mk_user(app)
    timer_id = _mk_timer(app, user_id, status='active', expires_delta_s=600)
    with app.app_context():
        timer_worker._step_checkin_request(datetime.now(timezone.utc))
    assert _status(app, timer_id) == 'active'
    assert captured['checkin'] == []


# ─── _step_trigger ────────────────────────────────────────────────────────────

def test_grace_expired_triggers_and_notifies_contacts(app, captured):
    owner_id = _mk_user(app)
    contact_id = _mk_user(app)
    grace = SafetyTimer.GRACE_PERIOD_SECONDS
    timer_id = _mk_timer(app, owner_id, status='checkin_requested',
                         checkin_delta_s=-(grace + 5), notify_contact_ids=contact_id)
    with app.app_context():
        timer_worker._step_trigger(datetime.now(timezone.utc))
    assert _status(app, timer_id) == 'triggered'
    assert len(captured['alarm_update']) == 1


def test_trigger_step_idempotent(app, captured):
    owner_id = _mk_user(app)
    contact_id = _mk_user(app)
    grace = SafetyTimer.GRACE_PERIOD_SECONDS
    timer_id = _mk_timer(app, owner_id, status='checkin_requested',
                         checkin_delta_s=-(grace + 5), notify_contact_ids=contact_id)
    with app.app_context():
        timer_worker._step_trigger(datetime.now(timezone.utc))
        timer_worker._step_trigger(datetime.now(timezone.utc))
    assert len(captured['alarm_update']) == 1  # contact not notified twice


def test_within_grace_not_triggered(app, captured):
    owner_id = _mk_user(app)
    timer_id = _mk_timer(app, owner_id, status='checkin_requested', checkin_delta_s=-10)
    with app.app_context():
        timer_worker._step_trigger(datetime.now(timezone.utc))
    assert _status(app, timer_id) == 'checkin_requested'
    assert captured['alarm_update'] == []
