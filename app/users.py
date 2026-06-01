"""User profile blueprint — /api/v1/users/me"""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request

from .db import db
from .models import User
from .token import require_auth

bp = Blueprint('users', __name__, url_prefix='/api/v1/users')

_DELETION_GRACE_DAYS = 30


@bp.get('/me')
@require_auth
def get_me():
    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404
    return jsonify(user.to_dict())


@bp.patch('/me')
@require_auth
def update_me():
    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    data = request.get_json(silent=True) or {}
    changed = False

    if 'email' in data:
        email = (data['email'] or '').lower().strip()
        if not email:
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_EMAIL'}), 400
        user.email = email
        changed = True

    if 'phone_number' in data:
        user.phone_number = data['phone_number'] or None
        # Changing the number invalidates the previous verification
        user.phone_verified = False
        changed = True

    if not changed:
        return jsonify({'error': 'Bad Request', 'code': 'NO_UPDATABLE_FIELDS'}), 400

    db.session.commit()
    db.session.refresh(user)
    return jsonify(user.to_dict())


@bp.delete('/me')
@require_auth
def delete_me():
    """GDPR Art. 17 — soft-delete with immediate PII anonymisation."""
    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    deletion_at = datetime.now(timezone.utc) + timedelta(days=_DELETION_GRACE_DAYS)

    # Anonymise PII immediately
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


@bp.get('/me/reputation')
@require_auth
def get_reputation():
    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    recent = user.reputation_actions.limit(20).all()

    return jsonify({
        'score': user.reputation_score,
        'level': user.reputation_level,
        'recent_actions': [a.to_dict() for a in recent],
    })
