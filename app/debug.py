"""Debug-only endpoints — /api/v1/debug/*

Registered ONLY when DEBUG=True, ENV=development, or TESTING=True.
Never active in production. Injects synthetic alarms for iOS simulator testing.
"""
import logging
import os
import uuid
from datetime import datetime, timezone

import h3
import redis as redis_lib
from flask import Blueprint, g, jsonify

from .db import db
from .geo import bearing_between, haversine_meters
from .models import Alarm, User
from .redis_keys import GEO_USER
from .token import require_auth

logger = logging.getLogger(__name__)
bp = Blueprint('debug', __name__, url_prefix='/api/v1/debug')

_TEST_USER_ID = '0d9d31df-6bea-49bc-849b-36746be384d4'
_TEST_USER_EMAIL = 'kontakt@safe2gether.de'

_DEMO_LAT = 48.58153   # Taxispark, Dillingen an der Donau
_DEMO_LNG = 10.49527
_DEMO_GEOHASH = h3.latlng_to_cell(_DEMO_LAT, _DEMO_LNG, 7)

_DEFAULT_BEARING = 124.0
_DEFAULT_DISTANCE = 480.0


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def _ensure_test_user() -> User:
    """Fetch test user by fixed UUID; create it if the DB is fresh (e.g. tests)."""
    user = db.session.get(User, _TEST_USER_ID)
    if user is None:
        user = User(
            id=_TEST_USER_ID,
            auth_provider='debug',
            email=_TEST_USER_EMAIL,
        )
        db.session.add(user)
        db.session.commit()
    return user


def _create_debug_alarm(test_user: User) -> Alarm:
    alarm = Alarm(
        id=str(uuid.uuid4()),
        user_id=test_user.id,
        alert_type='panic',
        audience='contacts_and_community',
        trigger_source='in_app',
        status='active',
        escalation_stage='device_local',
        geohash_snapshot=_DEMO_GEOHASH,
        triggered_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.session.add(alarm)
    db.session.commit()
    return alarm


def _caller_bearing_distance() -> tuple[float, float]:
    """Bearing and distance from the calling user's cached geohash to Berlin.
    Falls back to static defaults when the caller has no cached position."""
    try:
        caller_cell = _redis().get(f'{GEO_USER}{g.user_id}')
        if caller_cell and h3.is_valid_cell(caller_cell):
            c_lat, c_lng = h3.cell_to_latlng(caller_cell)
            distance = haversine_meters(c_lat, c_lng, _DEMO_LAT, _DEMO_LNG)
            bearing = bearing_between(c_lat, c_lng, _DEMO_LAT, _DEMO_LNG)
            return round(bearing, 1), round(distance, 1)
    except Exception:
        pass
    return _DEFAULT_BEARING, _DEFAULT_DISTANCE


@bp.post('/inject-nearby-alert')
@require_auth
def inject_nearby_alert():
    test_user = _ensure_test_user()
    alarm = _create_debug_alarm(test_user)
    bearing, distance = _caller_bearing_distance()

    triggered_at = alarm.triggered_at.isoformat() + 'Z' if alarm.triggered_at else ''
    logger.info('debug: inject_nearby_alert alarm=%s caller=%s', alarm.id, g.user_id)

    return jsonify({
        'alarm_id': alarm.id,
        'triggered_at': triggered_at,
        'bearing_degrees': bearing,
        'distance_meters': distance,
        'alert_type': alarm.alert_type,
    }), 201


@bp.post('/inject-contact-alarm')
@require_auth
def inject_contact_alarm():
    test_user = _ensure_test_user()
    alarm = _create_debug_alarm(test_user)

    logger.info('debug: inject_contact_alarm alarm=%s caller=%s', alarm.id, g.user_id)
    return jsonify({'alarm_id': alarm.id}), 201
