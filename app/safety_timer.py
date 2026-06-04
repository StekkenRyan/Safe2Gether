"""Dead Man's Switch — /api/v1/safety-timers

The owner creates a timer before a potentially risky situation.  If they don't
check in within the set duration the server first sends them a push asking
"Bist du okay?" (checkin_requested).  If there is still no response after
GRACE_PERIOD_SECONDS (5 min) the server notifies the chosen contacts and
optionally the community.

Worker: see timer_worker.py — runs as a daemon thread, polls every 30 s.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request

from .db import db
from .models import SafetyTimer, User
from .token import require_auth

logger = logging.getLogger(__name__)
bp = Blueprint('safety_timers', __name__, url_prefix='/api/v1/safety-timers')

_MAX_DURATION_SECONDS = 86_400   # 24 h hard cap
_MIN_DURATION_SECONDS = 300      # 5 min minimum


# ─── Create ───────────────────────────────────────────────────────────────────

@bp.post('')
@require_auth
def create_timer():
    data = request.get_json(silent=True) or {}

    duration = data.get('duration_seconds')
    if not isinstance(duration, int) or not (_MIN_DURATION_SECONDS <= duration <= _MAX_DURATION_SECONDS):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_DURATION',
            'detail': f'duration_seconds must be an integer between '
                      f'{_MIN_DURATION_SECONDS} and {_MAX_DURATION_SECONDS}',
        }), 400

    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    # Cancel any previously active timer for this user before creating a new one
    existing = SafetyTimer.query.filter_by(user_id=g.user_id, status='active').first()
    if existing:
        existing.status = 'cancelled'

    existing_cr = SafetyTimer.query.filter_by(user_id=g.user_id, status='checkin_requested').first()
    if existing_cr:
        existing_cr.status = 'cancelled'

    notify_contact_ids_raw = data.get('notify_contact_ids') or []
    if not isinstance(notify_contact_ids_raw, list):
        notify_contact_ids_raw = []
    notify_contact_ids = ','.join(str(c) for c in notify_contact_ids_raw if c)

    notify_community = bool(data.get('notify_community', False))
    note = (data.get('note') or '').strip()[:200] or None

    now = datetime.now(timezone.utc)
    timer = SafetyTimer(
        id=str(uuid.uuid4()),
        user_id=g.user_id,
        duration_seconds=duration,
        expires_at=now + timedelta(seconds=duration),
        status='active',
        notify_contact_ids=notify_contact_ids or None,
        notify_community=notify_community,
        note=note,
    )
    db.session.add(timer)
    db.session.commit()

    logger.info('safety_timer_created user=%s timer=%s duration=%ss', g.user_id, timer.id, duration)
    return jsonify(timer.to_dict()), 201


# ─── Active ────────────────────────────────────────────────────────────────────

@bp.get('/active')
@require_auth
def get_active_timer():
    """Returns the single active or checkin_requested timer, or null."""
    timer = SafetyTimer.query.filter(
        SafetyTimer.user_id == g.user_id,
        SafetyTimer.status.in_(('active', 'checkin_requested')),
    ).order_by(SafetyTimer.created_at.desc()).first()

    return jsonify({'timer': timer.to_dict() if timer else None})


# ─── Check in ─────────────────────────────────────────────────────────────────

@bp.post('/<timer_id>/checkin')
@require_auth
def checkin(timer_id: str):
    timer = db.session.get(SafetyTimer, timer_id)
    if not timer or timer.user_id != g.user_id:
        return jsonify({'error': 'Not Found', 'code': 'TIMER_NOT_FOUND'}), 404
    if timer.status not in ('active', 'checkin_requested'):
        return jsonify({'error': 'Conflict', 'code': 'TIMER_NOT_ACTIVE'}), 409

    timer.status = 'checked_in'
    db.session.commit()
    logger.info('safety_timer_checkin user=%s timer=%s', g.user_id, timer_id)
    return jsonify({'status': 'ok'})


# ─── Cancel ───────────────────────────────────────────────────────────────────

@bp.delete('/<timer_id>')
@require_auth
def cancel_timer(timer_id: str):
    timer = db.session.get(SafetyTimer, timer_id)
    if not timer or timer.user_id != g.user_id:
        return jsonify({'error': 'Not Found', 'code': 'TIMER_NOT_FOUND'}), 404
    if timer.status not in ('active', 'checkin_requested'):
        return jsonify({'error': 'Conflict', 'code': 'TIMER_NOT_ACTIVE'}), 409

    timer.status = 'cancelled'
    db.session.commit()
    logger.info('safety_timer_cancelled user=%s timer=%s', g.user_id, timer_id)
    return '', 204
