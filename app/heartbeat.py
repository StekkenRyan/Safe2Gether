"""Heartbeat blueprint — POST /api/v1/heartbeat

Keep-alive signal. Resets the user's Redis TTL.
Foundation for the v2.0 Dead Man's Switch: when the TTL expires without a
heartbeat and no expected_offline grace period is active, the server will
initiate escalation. In v1.0 this is informational only.
"""
import os

import redis as redis_lib
from flask import Blueprint, g, jsonify, request

from .token import require_auth

bp = Blueprint('heartbeat', __name__, url_prefix='/api/v1')

_HEARTBEAT_TTL = 600        # 10 min — matches geo TTL
_HEARTBEAT_KEY = 'user_hb:'  # + user_id


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


@bp.post('/heartbeat')
@require_auth
def send_heartbeat():
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
        if not isinstance(offline_secs, int) or offline_secs < 0:
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_OFFLINE_DURATION'}), 400
        ttl += offline_secs

    try:
        _redis().setex(f'{_HEARTBEAT_KEY}{g.user_id}', ttl, status)
    except redis_lib.RedisError as exc:
        return jsonify({'error': 'Service Unavailable', 'code': 'REDIS_ERROR',
                        'detail': str(exc)}), 503

    return '', 204
