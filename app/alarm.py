"""Alarm (Panic Button) blueprint — /api/v1/alarms"""
import os
import uuid

import redis as redis_lib
from flask import Blueprint, g, jsonify, request

from .db import db
from .geo import nearby_user_ids
from .models import Alarm, AlarmResponder, User
from .notifications import send_alarm_update, send_nearby_alert
from .token import require_auth

bp = Blueprint('alarms', __name__, url_prefix='/api/v1/alarms')

_GEO_KEY = 'user_geo:'


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def _user_geohash(user_id: str) -> str | None:
    try:
        return _redis().get(f'{_GEO_KEY}{user_id}')
    except redis_lib.RedisError:
        return None


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

    # Geohash: prefer client-provided snapshot, fall back to Redis cached value
    geohash = (data.get('geohash_snapshot') or '').strip() or _user_geohash(g.user_id)

    # Idempotency: client may retry — if alarm_id already exists, return existing record
    alarm_id = data.get('alarm_id') or str(uuid.uuid4())
    existing = db.session.get(Alarm, alarm_id)
    if existing:
        return jsonify(existing.to_dict()), 201

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

    # Notify emergency contacts (non-blocking)
    contacts = user.emergency_contacts.all()
    for contact in contacts:
        if contact.contact_type == 'in_app':
            # Find the in-app contact user and push to their device
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
        nearby_ids = nearby_user_ids(geohash)
        nearby_ids = [uid for uid in nearby_ids if uid != g.user_id]
        for nearby_id in nearby_ids:
            nearby_user = db.session.get(User, nearby_id)
            if not nearby_user or not nearby_user.apns_device_token:
                continue
            # Reputation check: low-reputation users don't receive community alerts
            if nearby_user.reputation_level == 'very_low':
                continue
            send_nearby_alert(
                nearby_user.apns_device_token,
                nearby_user.apns_environment or 'sandbox',
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
        # Only owner and confirmed responders can see the alarm
        return jsonify({'error': 'Not Found', 'code': 'ALARM_NOT_FOUND'}), 404

    return jsonify(alarm.to_dict(include_exact_location=is_responder and not is_owner))


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

    # Notify all responders
    msg = 'Alarm aufgehoben' if new_status == 'resolved' else 'Fehlalarm gemeldet'
    for responder in alarm.responders.all():
        ruser = db.session.get(User, responder.user_id)
        if ruser and ruser.apns_device_token:
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

    already = alarm.responders.filter_by(user_id=g.user_id).first()
    if already:
        return jsonify({'error': 'Conflict', 'code': 'ALREADY_RESPONDING'}), 409

    responder = AlarmResponder(alarm_id=alarm_id, user_id=g.user_id)
    db.session.add(responder)
    db.session.commit()

    # Notify alarm owner that help is on the way
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

    return jsonify({
        'alarm_id': alarm_id,
        'exact_location': location_data,
    })
