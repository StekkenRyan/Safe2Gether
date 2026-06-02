"""Escalation chain blueprint — /api/v1/escalation

The chain is the order in which alarm recipients are notified:
  device_local → contacts → community → contacts+community

Stored on the user row (see models.py). GET returns the current chain;
PATCH replaces it after validation.
"""
from flask import Blueprint, g, jsonify, request

from .db import db
from .models import User
from .token import require_auth

bp = Blueprint('escalation', __name__, url_prefix='/api/v1/escalation')

_VALID_STAGES = ('device_local', 'contacts', 'community', 'contacts+community')
_MAX_DELAY_SECONDS = 600


def _get_active_user(user_id: str) -> User | None:
    user = db.session.get(User, user_id)
    return user if (user and user.is_active) else None


@bp.get('')
@require_auth
def get_escalation():
    user = _get_active_user(g.user_id)
    if not user:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404
    return jsonify(user.escalation_to_dict())


@bp.patch('')
@require_auth
def update_escalation():
    user = _get_active_user(g.user_id)
    if not user:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    data = request.get_json(silent=True) or {}

    order = data.get('escalation_order')
    if not isinstance(order, list) or not order:
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_ESCALATION_ORDER',
            'detail': 'escalation_order must be a non-empty list',
        }), 400
    if any(not isinstance(s, str) or s not in _VALID_STAGES for s in order):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_ESCALATION_STAGE',
            'detail': f'each stage must be one of {_VALID_STAGES}',
        }), 400
    if len(set(order)) != len(order):
        return jsonify({
            'error': 'Bad Request', 'code': 'DUPLICATE_ESCALATION_STAGE',
            'detail': 'escalation_order must contain unique stages',
        }), 400

    user.escalation_order = ','.join(order)

    if 'delay_seconds_between_stages' in data:
        delay = data['delay_seconds_between_stages']
        if not isinstance(delay, int) or not (0 <= delay <= _MAX_DELAY_SECONDS):
            return jsonify({
                'error': 'Bad Request', 'code': 'INVALID_DELAY',
                'detail': f'delay_seconds_between_stages must be 0–{_MAX_DELAY_SECONDS}',
            }), 400
        user.escalation_delay_seconds = delay

    db.session.commit()
    return jsonify(user.escalation_to_dict())
