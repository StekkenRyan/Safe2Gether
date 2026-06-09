"""Geohash / Nearby Alerting blueprint — /api/v1/geohash

Redis data model (cell-based sets — avoids full SCAN):
  user_geo:<user_id>   → current H3 cell string      (SETEX, per-user TTL)
  geo_cell:<geohash>   → SET of user_ids in that cell (no TTL; lazy cleanup on read)
"""
import math
import os

import h3
import redis as redis_lib
from flask import Blueprint, g, jsonify, request

from .db import db
from .models import User
from .redis_keys import GEO_CELL, GEO_USER
from .token import require_auth

_EARTH_RADIUS_M = 6_371_000

bp = Blueprint('geo', __name__, url_prefix='/api/v1')

_GEO_TTL = 600              # 10 min base TTL
_MAX_OFFLINE_SECS = 604800  # 7 days absolute cap
# H3 resolution for clients that send raw lat/lng. Level 7 ≈ 1.2 km² average
# cell area — matches the privacy posture documented in the architecture docs.
_H3_RESOLUTION = 7


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


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng pairs in meters."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial great-circle bearing from p1 to p2 in degrees (0=N, clockwise)."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


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


def _coerce_geohash(data: dict) -> tuple[str | None, tuple[dict, int] | None]:
    """Return (geohash, None) on success or (None, (error_payload, status)) on failure.

    Accepts either a pre-computed H3 cell (`geohash` field) or raw coordinates
    (`latitude` + `longitude`). When both are present, the explicit cell wins
    so clients with their own H3 library bypass the server conversion.
    Coordinates are converted in-memory only — never stored, never logged.
    """
    raw_geo = data.get('geohash')
    if isinstance(raw_geo, str) and raw_geo.strip():
        cell = raw_geo.strip()
        if not h3.is_valid_cell(cell):
            return None, ({'error': 'Bad Request', 'code': 'INVALID_GEOHASH',
                           'detail': 'geohash must be a valid H3 index string'}, 400)
        return cell, None

    lat = data.get('latitude')
    lng = data.get('longitude')
    if lat is None or lng is None:
        return None, ({'error': 'Bad Request', 'code': 'MISSING_LOCATION',
                       'detail': 'provide either geohash or latitude+longitude'}, 400)

    # Reject booleans explicitly (bool is a subclass of int in Python).
    if (isinstance(lat, bool) or isinstance(lng, bool)
            or not isinstance(lat, (int, float))
            or not isinstance(lng, (int, float))):
        return None, ({'error': 'Bad Request', 'code': 'INVALID_COORDINATES',
                       'detail': 'latitude and longitude must be numbers'}, 400)
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return None, ({'error': 'Bad Request', 'code': 'INVALID_COORDINATES',
                       'detail': 'latitude must be -90..90 and longitude -180..180'}, 400)

    try:
        return h3.latlng_to_cell(float(lat), float(lng), _H3_RESOLUTION), None
    except Exception:
        return None, ({'error': 'Bad Request', 'code': 'INVALID_COORDINATES',
                       'detail': 'h3 conversion failed'}, 400)


@bp.put('/geohash')
@require_auth
def update_geohash():
    """Store the user's H3 cell in Redis.

    Body accepts either:
      • `geohash` (string) — pre-computed H3 cell from the client, or
      • `latitude` + `longitude` (numbers) — server converts to H3 res 7

    Raw coordinates are only used for the in-memory conversion. They are not
    persisted, not logged, and not echoed back. Only the H3 cell is written
    to Redis (matches the geohash-only-in-DB architecture invariant).

    `expected_offline` extends the TTL by `offline_duration_seconds` so entering
    a tunnel / dead zone doesn't trigger a false DMS escalation.
    """
    data = request.get_json(silent=True) or {}
    status = data.get('status')

    if status not in ('online', 'expected_offline'):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_STATUS',
            'detail': 'status must be online or expected_offline',
        }), 400

    geohash, error = _coerce_geohash(data)
    if error is not None:
        payload, code = error
        return jsonify(payload), code

    ttl = _GEO_TTL
    if status == 'expected_offline':
        offline_secs = data.get('offline_duration_seconds', 0)
        if (isinstance(offline_secs, bool)
                or not isinstance(offline_secs, int)
                or not (0 <= offline_secs <= _MAX_OFFLINE_SECS)):
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

    # Persist last_geohash to DB so debug distance calculation survives Redis TTL expiry.
    try:
        user = db.session.get(User, g.user_id)
        if user:
            user.last_geohash = geohash
            db.session.commit()
    except Exception:
        db.session.rollback()

    return '', 204
