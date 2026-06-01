"""Geohash / Nearby Alerting blueprint — /api/v1/geohash"""
import os

import h3
import redis as redis_lib
from flask import Blueprint, g, jsonify, request

from .token import require_auth

bp = Blueprint('geo', __name__, url_prefix='/api/v1')

_GEO_TTL = 600          # 10 min — user considered offline after this
_GEO_KEY = 'user_geo:'  # + user_id


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def nearby_user_ids(geohash: str, ring_size: int = 1) -> list[str]:
    """Return user IDs of active users in H3 cells neighbouring `geohash`.

    Queries Redis for all user_geo:* keys in the geohash and its k-ring.
    Used by the alarm endpoint to find who to alert.
    """
    try:
        r = _redis()
        neighbors = h3.grid_disk(geohash, ring_size)
        user_ids = []
        for cell in neighbors:
            # Scan for all users currently in this cell
            # Keys are stored as user_geo:<user_id> → <geohash>
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor, match=f'{_GEO_KEY}*', count=200)
                for key in keys:
                    val = r.get(key)
                    if val == cell:
                        user_ids.append(key[len(_GEO_KEY):])
                if cursor == 0:
                    break
        return list(set(user_ids))
    except redis_lib.RedisError:
        return []


@bp.put('/geohash')
@require_auth
def update_geohash():
    """Store the user's H3 cell in Redis with a TTL.

    When status is 'expected_offline', the TTL is extended by offline_duration_seconds
    so entering a tunnel/dead zone doesn't trigger a false DMS escalation.
    """
    data = request.get_json(silent=True) or {}
    geohash = data.get('geohash', '').strip()
    status = data.get('status')

    if not geohash:
        return jsonify({'error': 'Bad Request', 'code': 'MISSING_GEOHASH'}), 400
    if status not in ('online', 'expected_offline'):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_STATUS',
            'detail': 'status must be online or expected_offline',
        }), 400
    if not h3.is_valid_cell(geohash):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_GEOHASH',
            'detail': 'geohash must be a valid H3 index string',
        }), 400

    ttl = _GEO_TTL
    if status == 'expected_offline':
        offline_secs = data.get('offline_duration_seconds', 0)
        if not isinstance(offline_secs, int) or offline_secs < 0:
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_OFFLINE_DURATION'}), 400
        ttl += offline_secs

    try:
        _redis().setex(f'{_GEO_KEY}{g.user_id}', ttl, geohash)
    except redis_lib.RedisError as exc:
        return jsonify({'error': 'Service Unavailable', 'code': 'REDIS_ERROR',
                        'detail': str(exc)}), 503

    return '', 204
