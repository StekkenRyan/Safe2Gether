"""User profile blueprint — /api/v1/users/me"""
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request

from .db import db
from .models import Alarm, EmergencyContact, ReputationAction, SafetyTimer, User
from .token import require_auth

bp = Blueprint('users', __name__, url_prefix='/api/v1/users')

_DELETION_GRACE_DAYS = 30
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')
_PHONE_RE = re.compile(r'^\+?[0-9]{7,15}$')


def _get_active_user(user_id: str) -> User | None:
    user = db.session.get(User, user_id)
    return user if (user and user.is_active) else None


@bp.get('/me')
@require_auth
def get_me():
    user = _get_active_user(g.user_id)
    if not user:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404
    return jsonify(user.to_dict())


@bp.patch('/me')
@require_auth
def update_me():
    user = _get_active_user(g.user_id)
    if not user:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    data = request.get_json(silent=True) or {}
    changed = False

    if 'email' in data:
        email = (data['email'] or '').lower().strip()
        if not email or not _EMAIL_RE.match(email):
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_EMAIL'}), 400
        # Prevent email collision within the email provider
        if user.auth_provider == 'email':
            clash = User.query.filter(
                User.email == email,
                User.auth_provider == 'email',
                User.id != g.user_id,
            ).first()
            if clash:
                return jsonify({'error': 'Conflict', 'code': 'EMAIL_IN_USE'}), 409
        user.email = email
        changed = True

    if 'phone_number' in data:
        phone = (data['phone_number'] or '').strip() or None
        if phone and not _PHONE_RE.match(phone):
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_PHONE'}), 400
        user.phone_number = phone
        user.phone_verified = False
        changed = True

    if 'nearby_alerting_enabled' in data:
        val = data['nearby_alerting_enabled']
        if not isinstance(val, bool):
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_VALUE',
                            'detail': 'nearby_alerting_enabled must be a boolean'}), 400
        user.nearby_alerting_enabled = val
        changed = True

    if 'home_address_label' in data:
        user.home_address_label = (data['home_address_label'] or '').strip() or None
        changed = True

    if 'home_address' in data:
        user.home_address = (data['home_address'] or '').strip() or None
        changed = True

    if not changed:
        return jsonify({'error': 'Bad Request', 'code': 'NO_UPDATABLE_FIELDS'}), 400

    db.session.commit()
    db.session.refresh(user)
    return jsonify(user.to_dict())


@bp.delete('/me')
@require_auth
def delete_me():
    """GDPR Art. 17 — soft-delete with immediate PII anonymisation.

    Accepts an optional `refresh_token` body param; if provided, the token is
    revoked immediately so the deleted account cannot obtain new access tokens.
    """
    user = _get_active_user(g.user_id)
    if not user:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    data = request.get_json(silent=True) or {}
    refresh_token = data.get('refresh_token')
    if refresh_token:
        from .token import revoke_refresh_token
        revoke_refresh_token(refresh_token)

    deletion_at = datetime.now(timezone.utc) + timedelta(days=_DELETION_GRACE_DAYS)

    # Anonymise all PII immediately
    user.email = None
    user.password_hash = None
    user.apple_sub = None
    user.google_sub = None
    user.phone_number = None
    user.phone_verified = False
    user.apns_device_token = None
    user.apns_environment = None

    user.is_active = False
    user.scheduled_deletion_at = deletion_at

    db.session.commit()
    return jsonify({
        'scheduled_deletion_at': deletion_at.isoformat().replace('+00:00', 'Z'),
    }), 202


@bp.get('/me/export')
@require_auth
def export_me():
    """GDPR Art. 15 — data portability export.

    Returns a single JSON object with all personal data held for the user.
    Capped: last 100 alarms, last 50 reputation actions, all safety timers.
    """
    user = _get_active_user(g.user_id)
    if not user:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    alarms = (
        Alarm.query
        .filter_by(user_id=g.user_id)
        .order_by(Alarm.triggered_at.desc())
        .limit(100)
        .all()
    )
    reputation = (
        ReputationAction.query
        .filter_by(user_id=g.user_id)
        .order_by(ReputationAction.created_at.desc())
        .limit(50)
        .all()
    )
    contacts = (
        EmergencyContact.query
        .filter_by(user_id=g.user_id)
        .order_by(EmergencyContact.order_in_escalation)
        .all()
    )
    timers = (
        SafetyTimer.query
        .filter_by(user_id=g.user_id)
        .order_by(SafetyTimer.created_at.desc())
        .all()
    )

    return jsonify({
        'exported_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'user': user.to_dict(),
        'escalation_chain': user.escalation_to_dict(),
        'contacts': [c.to_dict() for c in contacts],
        'alarm_history': [a.to_dict() for a in alarms],
        'reputation_history': [r.to_dict() for r in reputation],
        'safety_timer_history': [t.to_dict() for t in timers],
    })


@bp.get('/me/reputation')
@require_auth
def get_reputation():
    user = _get_active_user(g.user_id)
    if not user:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    recent = user.reputation_actions.limit(20).all()
    return jsonify({
        'score': user.reputation_score,
        'level': user.reputation_level,
        'recent_actions': [a.to_dict() for a in recent],
    })
