"""Emergency contacts blueprint — /api/v1/contacts"""
import re
import uuid

from flask import Blueprint, g, jsonify, request

from .db import db
from .models import EmergencyContact, User
from .token import require_auth

bp = Blueprint('contacts', __name__, url_prefix='/api/v1/contacts')

_VALID_TYPES = ('phone', 'email', 'in_app')
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
