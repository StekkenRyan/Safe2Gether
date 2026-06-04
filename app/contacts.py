"""Emergency contacts blueprint — /api/v1/contacts"""
import os
import re
import secrets
import uuid

import redis as redis_lib
from flask import Blueprint, g, jsonify, request

from .db import db
from .models import EmergencyContact, User
from .redis_keys import CONTACT_INVITE
from .token import require_auth

bp = Blueprint('contacts', __name__, url_prefix='/api/v1/contacts')

_VALID_TYPES = ('phone', 'email', 'in_app')
_INVITE_TTL_SECS = 86_400  # 24 hours


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def _next_order(user_id: str) -> int:
    last = EmergencyContact.query.filter_by(user_id=user_id).order_by(
        EmergencyContact.order_in_escalation.desc()
    ).first()
    return (last.order_in_escalation + 1) if last else 1
_MAX_ORDER = 100
_PHONE_RE = re.compile(r'^\+?[0-9]{7,15}$')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE
)


def _validate_contact_value(contact_type: str, value: str) -> str | None:
    """Return an error message if invalid, else None."""
    if contact_type == 'phone' and not _PHONE_RE.match(value):
        return 'contact_value must be a valid phone number (E.164 format, 7–15 digits)'
    if contact_type == 'email' and not _EMAIL_RE.match(value):
        return 'contact_value must be a valid email address'
    if contact_type == 'in_app' and not _UUID_RE.match(value):
        return 'contact_value must be a valid user UUID for in_app contacts'
    return None


def _owned_contact(contact_id: str) -> EmergencyContact | None:
    return EmergencyContact.query.filter_by(id=contact_id, user_id=g.user_id).first()


@bp.get('')
@require_auth
def list_contacts():
    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404
    return jsonify([c.to_dict() for c in user.emergency_contacts.all()])


@bp.post('')
@require_auth
def create_contact():
    data = request.get_json(silent=True) or {}
    contact_type = data.get('contact_type')
    contact_value = (data.get('contact_value') or '').strip()
    name = (data.get('name') or '').strip()

    if contact_type not in _VALID_TYPES or not contact_value or not name:
        return jsonify({'error': 'Bad Request', 'code': 'MISSING_FIELDS',
                        'detail': 'contact_type, contact_value and name are required'}), 400

    err = _validate_contact_value(contact_type, contact_value)
    if err:
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_CONTACT_VALUE',
                        'detail': err}), 400

    # Verify in_app target exists and is active before storing a dangling reference
    if contact_type == 'in_app':
        target = db.session.get(User, contact_value)
        if not target or not target.is_active:
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_CONTACT_VALUE',
                            'detail': 'contact_value must be a valid active user id'}), 400

    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    order = data.get('order_in_escalation')
    if order is None:
        last = user.emergency_contacts.order_by(
            EmergencyContact.order_in_escalation.desc()
        ).first()
        order = (last.order_in_escalation + 1) if last else 1
    else:
        order = int(order)
        if not (1 <= order <= _MAX_ORDER):
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_ORDER',
                            'detail': f'order_in_escalation must be 1–{_MAX_ORDER}'}), 400

    contact = EmergencyContact(
        id=str(uuid.uuid4()),
        user_id=g.user_id,
        contact_type=contact_type,
        contact_value=contact_value,
        name=name,
        order_in_escalation=order,
    )
    db.session.add(contact)
    db.session.commit()
    db.session.refresh(contact)
    return jsonify(contact.to_dict()), 201


@bp.patch('/<contact_id>')
@require_auth
def update_contact(contact_id: str):
    contact = _owned_contact(contact_id)
    if not contact:
        return jsonify({'error': 'Not Found', 'code': 'CONTACT_NOT_FOUND'}), 404

    data = request.get_json(silent=True) or {}
    if 'contact_value' in data:
        val = (data['contact_value'] or '').strip()
        err = _validate_contact_value(contact.contact_type, val)
        if err:
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_CONTACT_VALUE',
                            'detail': err}), 400
        contact.contact_value = val
    if 'name' in data:
        contact.name = (data['name'] or '').strip()
    if 'order_in_escalation' in data:
        order = int(data['order_in_escalation'])
        if not (1 <= order <= _MAX_ORDER):
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_ORDER',
                            'detail': f'order_in_escalation must be 1–{_MAX_ORDER}'}), 400
        contact.order_in_escalation = order

    db.session.commit()
    return jsonify(contact.to_dict())


@bp.delete('/<contact_id>')
@require_auth
def delete_contact(contact_id: str):
    contact = _owned_contact(contact_id)
    if not contact:
        return jsonify({'error': 'Not Found', 'code': 'CONTACT_NOT_FOUND'}), 404
    db.session.delete(contact)
    db.session.commit()
    return '', 204


# ─── Invite flow ──────────────────────────────────────────────────────────────

@bp.post('/invite')
@require_auth
def create_invite():
    """Generate a one-time invite token valid for 24 h.

    Returns a deep-link the sender shares via iOS share sheet or QR code.
    The recipient opens the link → app calls POST /contacts/accept → both
    parties get an in_app contact entry pointing at each other.
    """
    token = secrets.token_urlsafe(16)
    try:
        _redis().setex(f'{CONTACT_INVITE}{token}', _INVITE_TTL_SECS, g.user_id)
    except redis_lib.RedisError:
        return jsonify({'error': 'Service Unavailable', 'code': 'REDIS_UNAVAILABLE'}), 503
    return jsonify({
        'token': token,
        'deep_link': f'safe2gether://invite?token={token}',
    }), 201


@bp.post('/accept')
@require_auth
def accept_invite():
    """Accept a contact invite token. Creates a bidirectional in_app contact pair."""
    data = request.get_json(silent=True) or {}
    token = (data.get('token') or '').strip()
    if not token:
        return jsonify({'error': 'Bad Request', 'code': 'MISSING_TOKEN'}), 400

    try:
        # GETDEL is atomic (Redis 6.2+): eliminates the race where two concurrent
        # requests both read the key before either deletes it.
        inviter_id = _redis().getdel(f'{CONTACT_INVITE}{token}')
    except redis_lib.RedisError:
        return jsonify({'error': 'Service Unavailable', 'code': 'REDIS_UNAVAILABLE'}), 503

    if not inviter_id:
        return jsonify({'error': 'Not Found', 'code': 'INVALID_OR_EXPIRED_TOKEN'}), 404

    accepter_id = g.user_id
    if inviter_id == accepter_id:
        return jsonify({'error': 'Bad Request', 'code': 'CANNOT_INVITE_YOURSELF'}), 400

    inviter = db.session.get(User, inviter_id)
    accepter = db.session.get(User, accepter_id)
    if not inviter or not accepter:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    # Inviter gets accepter as contact (skip if duplicate)
    if not EmergencyContact.query.filter_by(
            user_id=inviter_id, contact_type='in_app', contact_value=accepter_id).first():
        db.session.add(EmergencyContact(
            id=str(uuid.uuid4()),
            user_id=inviter_id,
            contact_type='in_app',
            contact_value=accepter_id,
            name=accepter.email or 'Kontakt',
            order_in_escalation=_next_order(inviter_id),
        ))

    # Accepter gets inviter as contact (skip if duplicate)
    if not EmergencyContact.query.filter_by(
            user_id=accepter_id, contact_type='in_app', contact_value=inviter_id).first():
        db.session.add(EmergencyContact(
            id=str(uuid.uuid4()),
            user_id=accepter_id,
            contact_type='in_app',
            contact_value=inviter_id,
            name=inviter.email or 'Kontakt',
            order_in_escalation=_next_order(accepter_id),
        ))

    db.session.commit()
    return '', 204
