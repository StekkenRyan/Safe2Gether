"""Alarm (Panic Button) blueprint — /api/v1/alarms"""
import logging
import os
import uuid

import h3
import redis as redis_lib
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from .db import db
from .geo import nearby_user_ids
from .models import Alarm, AlarmResponder, User
from .notifications import send_alarm_update, send_nearby_alert
from .redis_keys import ALARM_RATE, GEO_USER
from .token import require_auth

logger = logging.getLogger(__name__)
bp = Blueprint('alarms', __name__, url_prefix='/api/v1/alarms')

_ALARM_RATE_LIMIT_SECS = 60   # max 1 alarm per user per minute


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def _user_geohash(user_id: str) -> str | None:
    try:
        return _redis().get(f'{GEO_USER}{user_id}')
    except redis_lib.RedisError:
        return None


def _check_rate_limit(user_id: str) -> bool:
    """Return True if within limit, False if rate limited (1 alarm / 60 s)."""
    try:
        result = _redis().set(f'{ALARM_RATE}{user_id}', '1',
                              nx=True, ex=_ALARM_RATE_LIMIT_SECS)
        return result is not None
    except redis_lib.RedisError:
        return True  # Fail open: never block a real emergency due to Redis outage


# ─── Create alarm ─────────────────────────────────────────────────────────────

@bp.post('')
@require_auth
def trigger_alarm():
    data = request.get_json(silent=True) or {}
    trigger_source = data.get('trigger_source')

    valid_sources = ('in_app', 'widget', 'hardware_button')
    if trigger_source not in valid_sources:
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_TRIGGER_SOURCE',
                        'detail': f'trigger_source must be one of {valid_sources}'}), 400

    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    if not _check_rate_limit(g.user_id):
        return jsonify({
            'error': 'Too Many Requests', 'code': 'ALARM_RATE_LIMIT',
            'detail': f'Maximum 1 alarm per {_ALARM_RATE_LIMIT_SECS} seconds.',
        }), 429

    # Geohash: client-provided snapshot is preferred; fall back to Redis cached value
    geohash_snapshot = (data.get('geohash_snapshot') or '').strip()
    if geohash_snapshot and not h3.is_valid_cell(geohash_snapshot):
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_GEOHASH'}), 400
    geohash = geohash_snapshot or _user_geohash(g.user_id)

    alarm_id = str(uuid.uuid4())  # Always server-generated — no client-provided IDs

    alarm = Alarm(
        id=alarm_id,
        user_id=g.user_id,
        trigger_source=trigger_source,
        status='active',
        escalation_stage='device_local',
        geohash_snapshot=geohash,
    )
    db.session.add(alarm)
    db.session.commit()
    logger.info('alarm_triggered user=%s alarm=%s source=%s geohash=%s',
                g.user_id, alarm_id, trigger_source, geohash)

    # Notify emergency contacts (non-blocking, fire-and-forget)
    contacts = user.emergency_contacts.all()
    for contact in contacts:
        if contact.contact_type == 'in_app':
            contact_user = db.session.get(User, contact.contact_value)
            if contact_user and contact_user.apns_device_token:
                send_alarm_update(
                    contact_user.apns_device_token,
                    contact_user.apns_environment or 'sandbox',
                    alarm_id,
                    f'{user.email or "Dein Kontakt"} hat einen Notruf ausgelöst!',
                )

    # Notify nearby community users (non-blocking)
    if geohash:
        nearby_ids = [uid for uid in nearby_user_ids(geohash) if uid != g.user_id]
        # Batch-load nearby users to avoid N+1
        nearby_users = {u.id: u for u in User.query.filter(User.id.in_(nearby_ids)).all()}
        for uid in nearby_ids:
            nu = nearby_users.get(uid)
            if not nu or not nu.apns_device_token:
                continue
            if not nu.nearby_alerting_enabled:
                continue
            if nu.reputation_level == 'very_low':
                continue
            send_nearby_alert(
                nu.apns_device_token,
                nu.apns_environment or 'sandbox',
                alarm_id,
                direction='In deiner Nähe',
                distance_m=500,
            )

    db.session.refresh(alarm)
    return jsonify(alarm.to_dict()), 201


# ─── Get alarm ────────────────────────────────────────────────────────────────

@bp.get('/<alarm_id>')
@require_auth
def get_alarm(alarm_id: str):
    alarm = db.session.get(Alarm, alarm_id)
    if not alarm:
        return jsonify({'error': 'Not Found', 'code': 'ALARM_NOT_FOUND'}), 404

    is_owner = alarm.user_id == g.user_id
    is_responder = alarm.responders.filter_by(user_id=g.user_id).first() is not None

    if not is_owner and not is_responder:
        return jsonify({'error': 'Not Found', 'code': 'ALARM_NOT_FOUND'}), 404

    include_exact = is_responder and not is_owner
    if include_exact and alarm.exact_latitude is not None:
        logger.info('exact_coords_accessed alarm=%s by user=%s role=responder',
                    alarm_id, g.user_id)

    return jsonify(alarm.to_dict(include_exact_location=include_exact))


# ─── Update alarm status ──────────────────────────────────────────────────────

@bp.patch('/<alarm_id>')
@require_auth
def update_alarm(alarm_id: str):
    alarm = db.session.get(Alarm, alarm_id)
    if not alarm:
        return jsonify({'error': 'Not Found', 'code': 'ALARM_NOT_FOUND'}), 404
    if alarm.user_id != g.user_id:
        return jsonify({'error': 'Forbidden', 'code': 'NOT_ALARM_OWNER'}), 403

    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    if new_status not in ('resolved', 'false_alarm'):
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_STATUS'}), 400

    alarm.status = new_status
    db.session.commit()
    logger.info('alarm_updated alarm=%s status=%s by user=%s', alarm_id, new_status, g.user_id)

    # Notify all responders (batch-load to avoid N+1)
    responder_ids = [r.user_id for r in alarm.responders.all()]
    responder_users = User.query.filter(User.id.in_(responder_ids)).all()
    msg = 'Alarm aufgehoben' if new_status == 'resolved' else 'Fehlalarm gemeldet'
    for ruser in responder_users:
        if ruser.apns_device_token:
            send_alarm_update(ruser.apns_device_token,
                              ruser.apns_environment or 'sandbox', alarm_id, msg)

    return jsonify(alarm.to_dict())


# ─── Respond to alarm ─────────────────────────────────────────────────────────

@bp.post('/<alarm_id>/respond')
@require_auth
def respond_to_alarm(alarm_id: str):
    alarm = db.session.get(Alarm, alarm_id)
    if not alarm or alarm.status != 'active':
        return jsonify({'error': 'Not Found', 'code': 'ALARM_NOT_FOUND'}), 404
    if alarm.user_id == g.user_id:
        return jsonify({'error': 'Bad Request', 'code': 'CANNOT_RESPOND_OWN_ALARM'}), 400

    try:
        responder = AlarmResponder(alarm_id=alarm_id, user_id=g.user_id)
        db.session.add(responder)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Conflict', 'code': 'ALREADY_RESPONDING'}), 409

    logger.info('alarm_response alarm=%s responder=%s', alarm_id, g.user_id)

    # Notify alarm owner
    owner = db.session.get(User, alarm.user_id)
    if owner and owner.apns_device_token:
        send_alarm_update(owner.apns_device_token,
                          owner.apns_environment or 'sandbox',
                          alarm_id, 'Jemand kommt zu dir!')

    location_data = None
    if alarm.exact_latitude is not None:
        location_data = {
            'latitude': alarm.exact_latitude,
            'longitude': alarm.exact_longitude,
        }
        logger.info('exact_coords_accessed alarm=%s by user=%s role=responder',
                    alarm_id, g.user_id)

    return jsonify({'alarm_id': alarm_id, 'exact_location': location_data})
