"""Alarm (Panic Button) blueprint — /api/v1/alarms

Escalation chain runs through a Redis-backed scheduler (see
`escalation_worker.py`). The first stage executes inline on the trigger
request so the responsive APNs fanout still happens in the same request
window; subsequent stages are enqueued and picked up by the worker.
"""
import logging
import os
import time
import uuid

import h3
import redis as redis_lib
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from .db import db
from .geo import bearing_between, haversine_meters, nearby_user_ids
from .models import Alarm, AlarmResponder, ReputationAction, User
from .notifications import (
    EVENT_ALARM_FALSE_ALARM,
    EVENT_ALARM_RESOLVED,
    EVENT_CONTACT_ALARM_TRIGGERED,
    EVENT_RESPONDER_ADDED,
    send_alarm_update,
    send_nearby_alert,
)
from .redis_keys import ALARM_RATE, ESCALATION_QUEUE, GEO_USER
from .token import require_auth

logger = logging.getLogger(__name__)
bp = Blueprint('alarms', __name__, url_prefix='/api/v1/alarms')

_ALARM_RATE_LIMIT_SECS = 60   # max 1 alarm per user per minute

_VALID_STAGES = ('device_local', 'contacts', 'community', 'contacts+community')
_VALID_ALERT_TYPES = ('panic', 'need_help', 'car_breakdown', 'cant_get_home')
_VALID_AUDIENCES = ('contacts', 'community', 'contacts_and_community')
_VALID_HOME_DISTANCES = ('under_1km', '1_5km', '5_15km', 'over_15km')

_REP_RESPONDED = 10          # pressed "Ich helfe"
_REP_RESPONSE_VERIFIED = 5   # alarm resolved → responder's effort confirmed
_REP_FALSE_ALARM = -5        # owner flagged own alarm as false alarm


# ─── Redis helpers ───────────────────────────────────────────────────────────

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


def schedule_stage(alarm_id: str, stage_index: int, run_at_ts: float) -> None:
    """Push a stage onto the escalation queue. Idempotent."""
    member = f'{alarm_id}:{stage_index}'
    try:
        _redis().zadd(ESCALATION_QUEUE, {member: run_at_ts})
    except redis_lib.RedisError:
        # Best-effort: a Redis outage here means the later stages won't fire,
        # but stage 0 already ran inline so the user still gets fanout. Log
        # and continue.
        logger.exception('escalation enqueue failed for %s stage=%s', alarm_id, stage_index)


def _route_from_receiver(receiver_cell: str | None,
                         sender_lat: float, sender_lng: float) -> tuple[int, float]:
    """Distance (m) and bearing (deg) from the receiver to the alarm sender."""
    if not receiver_cell:
        return 500, 0.0
    try:
        r_lat, r_lng = h3.cell_to_latlng(receiver_cell)
        distance_m = int(haversine_meters(r_lat, r_lng, sender_lat, sender_lng))
        bearing = bearing_between(r_lat, r_lng, sender_lat, sender_lng)
        return distance_m, bearing
    except Exception:
        return 500, 0.0


# ─── Reputation helpers ──────────────────────────────────────────────────────

def _compute_level(score: int) -> str:
    if score < -20:
        return 'very_low'
    if score < 0:
        return 'low'
    if score < 50:
        return 'normal'
    if score < 200:
        return 'high'
    return 'very_high'


def _award_reputation(user: User, action_type: str, score_delta: int,
                      alarm_id: str | None = None) -> None:
    """Append a ReputationAction and update user score/level in-place.
    Caller is responsible for db.session.commit()."""
    db.session.add(ReputationAction(
        id=str(uuid.uuid4()),
        user_id=user.id,
        action_type=action_type,
        score_delta=score_delta,
        alarm_id=alarm_id,
    ))
    user.reputation_score = (user.reputation_score or 0) + score_delta
    user.reputation_level = _compute_level(user.reputation_score)


# ─── Stage fan-out helpers (used inline + by the escalation worker) ──────────

def _notify_contacts(alarm: Alarm, user: User) -> None:
    """Push notification to every `in_app` emergency contact of the alarmee.

    `phone` / `email` contact types are stored on the user but not delivered
    by the v1.0 server — they're a v2.x SMS/Email provider concern.
    """
    contacts = user.emergency_contacts.all()
    for contact in contacts:
        if contact.contact_type != 'in_app':
            continue
        contact_user = db.session.get(User, contact.contact_value)
        if not contact_user or not contact_user.apns_device_token:
            continue
        send_alarm_update(
            contact_user.apns_device_token,
            contact_user.apns_environment or 'sandbox',
            alarm.id,
            event=EVENT_CONTACT_ALARM_TRIGGERED,
            body=f'{user.email or "Dein Kontakt"} hat einen Notruf ausgelöst!',
        )


def _notify_community(alarm: Alarm, user: User, home_distance_category: str | None = None) -> None:
    """Push notification to every Nearby-Alerting-enabled user in the H3 k-ring
    around the alarm's geohash_snapshot. Uses the snapshot deliberately —
    nearby users near the *original* panic site should be alerted even if the
    alarmee has been moving for some minutes.
    """
    geohash = alarm.geohash_snapshot
    if not geohash:
        return

    sender_lat, sender_lng = h3.cell_to_latlng(geohash)
    triggered_at_iso = alarm.triggered_at.isoformat() if alarm.triggered_at else ''

    nearby_ids = [uid for uid in nearby_user_ids(geohash) if uid != alarm.user_id]
    nearby_users = {u.id: u for u in User.query.filter(User.id.in_(nearby_ids)).all()}
    for uid in nearby_ids:
        nu = nearby_users.get(uid)
        if not nu or not nu.apns_device_token:
            continue
        if not nu.nearby_alerting_enabled:
            continue
        if nu.reputation_level == 'very_low':
            continue

        distance_m, bearing = _route_from_receiver(_user_geohash(uid),
                                                   sender_lat, sender_lng)
        send_nearby_alert(
            nu.apns_device_token,
            nu.apns_environment or 'sandbox',
            alarm.id,
            triggered_at_iso=triggered_at_iso,
            bearing_degrees=bearing,
            distance_meters=distance_m,
            responder_count=0,
            alert_type=alarm.alert_type,
            home_distance_category=home_distance_category,
        )


def run_stage(alarm: Alarm, user: User, stage: str) -> None:
    """Dispatch a single escalation stage. `device_local` is a no-op on the
    server side (the iOS local timer is the source of truth for that stage).
    """
    if stage == 'device_local':
        return
    hdc = alarm.home_distance_category
    if stage == 'contacts':
        _notify_contacts(alarm, user)
    elif stage == 'community':
        _notify_community(alarm, user, home_distance_category=hdc)
    elif stage == 'contacts+community':
        _notify_contacts(alarm, user)
        _notify_community(alarm, user, home_distance_category=hdc)
    else:
        logger.warning('unknown escalation stage %r on alarm %s', stage, alarm.id)


def _user_stages(user: User) -> list[str]:
    """Sanitised escalation chain for a user — drops empty / unknown values."""
    raw = (user.escalation_order or '').split(',')
    return [s for s in raw if s in _VALID_STAGES]


def _stages_for_audience(base_stages: list[str], audience: str) -> list[str]:
    """Filter escalation stages to match the requested audience.

    When a specific audience is chosen the user's full escalation chain is
    overridden: only the stages relevant to that audience are kept.
    contacts_and_community uses the chain as-is.
    """
    if audience == 'contacts':
        return [s for s in base_stages if s not in ('community',)]
    if audience == 'community':
        return [s for s in base_stages if s not in ('contacts',)]
    return base_stages


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

    alert_type = data.get('alert_type', 'panic')
    if alert_type not in _VALID_ALERT_TYPES:
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_ALERT_TYPE',
                        'detail': f'alert_type must be one of {_VALID_ALERT_TYPES}'}), 400

    audience = data.get('audience', 'contacts_and_community')
    if audience not in _VALID_AUDIENCES:
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_AUDIENCE',
                        'detail': f'audience must be one of {_VALID_AUDIENCES}'}), 400

    home_distance_category = data.get('home_distance_category') or None
    if home_distance_category and home_distance_category not in _VALID_HOME_DISTANCES:
        return jsonify({
            'error': 'Bad Request',
            'code': 'INVALID_HOME_DISTANCE_CATEGORY',
            'detail': f'home_distance_category must be one of {_VALID_HOME_DISTANCES}',
        }), 400

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

    base_stages = _user_stages(user) or ['device_local', 'contacts', 'community']
    stages = _stages_for_audience(base_stages, audience)
    # Guarantee at least device_local so the alarm always has a valid first stage
    if not stages:
        stages = ['device_local']
    delay = user.escalation_delay_seconds

    alarm = Alarm(
        id=alarm_id,
        user_id=g.user_id,
        trigger_source=trigger_source,
        alert_type=alert_type,
        audience=audience,
        home_distance_category=home_distance_category,
        status='active',
        escalation_stage=stages[0],
        geohash_snapshot=geohash,
    )
    db.session.add(alarm)
    db.session.commit()
    logger.info('alarm_triggered user=%s alarm=%s source=%s stages=%s delay=%ss',
                g.user_id, alarm_id, trigger_source, stages, delay)

    # Stage 0 inline: keeps the panic-button → first-fanout round-trip tight.
    run_stage(alarm, user, stages[0])

    # Stage 1+ go through the persistent scheduler so an api restart doesn't
    # lose them. Worker re-checks alarm.status before each execution.
    now = time.time()
    for index, _stage in enumerate(stages[1:], start=1):
        schedule_stage(alarm_id, index, now + index * delay)

    db.session.refresh(alarm)
    return jsonify(alarm.to_dict()), 201


# ─── List alarms (user history) ───────────────────────────────────────────────

_HISTORY_LIMIT = 50


@bp.get('')
@require_auth
def list_alarms():
    """User's alarm history — alarms they triggered + alarms they responded to,
    merged by triggered_at desc and capped at the most recent 50.

    Each entry carries `your_role: 'sender' | 'responder'` so the iOS history
    list can render the badge without a second round-trip.
    """
    user_id = g.user_id

    sent_alarms = Alarm.query.filter_by(user_id=user_id).all()

    responded_ids = [
        r.alarm_id for r in AlarmResponder.query.filter_by(user_id=user_id).all()
    ]
    responded_alarms = (
        Alarm.query.filter(Alarm.id.in_(responded_ids)).all() if responded_ids else []
    )

    # Dedup (defensive: server prevents responding to own alarms but be safe)
    # and sort newest-first, then cap.
    seen: set[str] = set()
    combined = []
    for alarm in sent_alarms + responded_alarms:
        if alarm.id in seen:
            continue
        seen.add(alarm.id)
        combined.append(alarm)
    combined.sort(key=lambda a: a.triggered_at, reverse=True)
    combined = combined[:_HISTORY_LIMIT]

    def serialize(a: Alarm) -> dict:
        data = a.to_dict()
        data['your_role'] = 'sender' if a.user_id == user_id else 'responder'
        return data

    return jsonify({'alarms': [serialize(a) for a in combined]})


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

    # Pending escalation stages in the queue self-skip on next poll because
    # the worker checks status before executing — no active cleanup needed.

    # Notify all responders (batch-load to avoid N+1)
    responder_ids = [r.user_id for r in alarm.responders.all()]
    responder_users = User.query.filter(User.id.in_(responder_ids)).all()
    if new_status == 'resolved':
        event = EVENT_ALARM_RESOLVED
        msg = 'Alarm aufgehoben'
    else:
        event = EVENT_ALARM_FALSE_ALARM
        msg = 'Fehlalarm gemeldet'
    for ruser in responder_users:
        if ruser.apns_device_token:
            send_alarm_update(
                ruser.apns_device_token,
                ruser.apns_environment or 'sandbox',
                alarm_id,
                event=event,
                body=msg,
            )

    # Reputation updates
    if new_status == 'resolved':
        for ruser in responder_users:
            _award_reputation(ruser, 'response_verified', _REP_RESPONSE_VERIFIED, alarm_id)
    else:  # false_alarm
        owner_user = db.session.get(User, g.user_id)
        if owner_user:
            _award_reputation(owner_user, 'false_alarm_triggered', _REP_FALSE_ALARM, alarm_id)
    db.session.commit()

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

    responder_user = db.session.get(User, g.user_id)
    if responder_user:
        _award_reputation(responder_user, 'responded_to_alarm', _REP_RESPONDED, alarm_id)
        db.session.commit()

    # Notify alarm owner
    owner = db.session.get(User, alarm.user_id)
    if owner and owner.apns_device_token:
        send_alarm_update(
            owner.apns_device_token,
            owner.apns_environment or 'sandbox',
            alarm_id,
            event=EVENT_RESPONDER_ADDED,
            body='Jemand kommt zu dir!',
        )

    location_data = None
    if alarm.exact_latitude is not None:
        location_data = {
            'latitude': alarm.exact_latitude,
            'longitude': alarm.exact_longitude,
        }
        logger.info('exact_coords_accessed alarm=%s by user=%s role=responder',
                    alarm_id, g.user_id)

    return jsonify({'alarm_id': alarm_id, 'exact_location': location_data})
