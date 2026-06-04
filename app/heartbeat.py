"""Heartbeat blueprint — POST /api/v1/heartbeat"""
import os

import redis as redis_lib
from flask import Blueprint, g, jsonify, request

from .db import db
from .models import User
from .redis_keys import HB
from .token import require_auth

bp = Blueprint('heartbeat', __name__, url_prefix='/api/v1')

_HEARTBEAT_TTL = 600        # 10 min base TTL
_MAX_OFFLINE_SECS = 604800  # 7 days absolute cap


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


@bp.post('/heartbeat')
@require_auth
def send_heartbeat():
    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    data = request.get_json(silent=True) or {}
    status = data.get('status')

    if status not in ('alive', 'expected_offline'):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_STATUS',
            'detail': 'status must be alive or expected_offline',
        }), 400

    ttl = _HEARTBEAT_TTL
    if status == 'expected_offline':
        offline_secs = data.get('offline_duration_seconds', 0)
        if not isinstance(offline_secs, int) or not (0 <= offline_secs <= _MAX_OFFLINE_SECS):
            return jsonify({
                'error': 'Bad Request', 'code': 'INVALID_OFFLINE_DURATION',
                'detail': f'offline_duration_seconds must be 0–{_MAX_OFFLINE_SECS}',
            }), 400
        ttl += offline_secs

    try:
        _redis().setex(f'{HB}{g.user_id}', ttl, status)
    except redis_lib.RedisError as exc:
        return jsonify({'error': 'Service Unavailable', 'code': 'REDIS_ERROR',
                        'detail': str(exc)}), 503

    return '', 204
