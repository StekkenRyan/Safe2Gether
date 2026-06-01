"""Geohash / Nearby Alerting blueprint — /api/v1/geohash

Redis data model (cell-based sets — avoids full SCAN):
  user_geo:<user_id>   → current H3 cell string      (SETEX, per-user TTL)
  geo_cell:<geohash>   → SET of user_ids in that cell (no TTL; lazy cleanup on read)
"""
import os

import h3
import redis as redis_lib
from flask import Blueprint, g, jsonify, request

from .redis_keys import GEO_CELL, GEO_USER
from .token import require_auth

bp = Blueprint('geo', __name__, url_prefix='/api/v1')

_GEO_TTL = 600              # 10 min base TTL
_MAX_OFFLINE_SECS = 604800  # 7 days absolute cap


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def _update_user_geo(r: redis_lib.Redis, user_id: str, geohash: str, ttl: int) -> None:
    """Atomically move user from old cell set to new one, then set geo key."""
    old = r.get(f'{GEO_USER}{user_id}')
    pipe = r.pipeline()
    if old and old != geohash:
        pipe.srem(f'{GEO_CELL}{old}', user_id)
    pipe.setex(f'{GEO_USER}{user_id}', ttl, geohash)
    pipe.sadd(f'{GEO_CELL}{geohash}', user_id)
    pipe.execute()


def nearby_user_ids(geohash: str, ring_size: int = 1) -> list[str]:
    """Return IDs of users currently active in the H3 k-ring around geohash.

    Uses cell-based sets (O(users_in_cells)) instead of a full Redis SCAN.
    Stale members (expired GEO_USER keys) are lazily removed.
    """
    try:
        r = _redis()
        neighbors = h3.grid_disk(geohash, ring_size)
        active: set[str] = set()
        stale_cleanup = r.pipeline()

        for cell in neighbors:
            candidates = r.smembers(f'{GEO_CELL}{cell}')
            for uid in candidates:
                if r.exists(f'{GEO_USER}{uid}'):
                    active.add(uid)
                else:
                    stale_cleanup.srem(f'{GEO_CELL}{cell}', uid)

        stale_cleanup.execute()
        return list(active)
    except redis_lib.RedisError:
        return []


@bp.put('/geohash')
@require_auth
def update_geohash():
    """Store the user's H3 cell in Redis.

    expected_offline extends the TTL by offline_duration_seconds so entering
    a tunnel / dead zone doesn't trigger a false DMS escalation.
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
        if not isinstance(offline_secs, int) or not (0 <= offline_secs <= _MAX_OFFLINE_SECS):
            return jsonify({
                'error': 'Bad Request', 'code': 'INVALID_OFFLINE_DURATION',
                'detail': f'offline_duration_seconds must be 0–{_MAX_OFFLINE_SECS}',
            }), 400
        ttl += offline_secs

    try:
        _update_user_geo(_redis(), g.user_id, geohash, ttl)
    except redis_lib.RedisError as exc:
        return jsonify({'error': 'Service Unavailable', 'code': 'REDIS_ERROR',
                        'detail': str(exc)}), 503

    return '', 204
