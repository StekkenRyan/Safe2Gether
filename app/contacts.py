"""Emergency contacts blueprint — /api/v1/contacts"""
import uuid

from flask import Blueprint, g, jsonify, request

from .db import db
from .models import EmergencyContact, User
from .token import require_auth

bp = Blueprint('contacts', __name__, url_prefix='/api/v1/contacts')

_VALID_TYPES = ('phone', 'email', 'in_app')


def _owned_contact(contact_id: str) -> EmergencyContact | None:
    return EmergencyContact.query.filter_by(id=contact_id, user_id=g.user_id).first()


@bp.get('')
@require_auth
def list_contacts():
    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404
    contacts = user.emergency_contacts.all()
    return jsonify([c.to_dict() for c in contacts])


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

    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    # Determine order: append at end if not provided
    order = data.get('order_in_escalation')
    if order is None:
        last = user.emergency_contacts.order_by(
            EmergencyContact.order_in_escalation.desc()
        ).first()
        order = (last.order_in_escalation + 1) if last else 1

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
        contact.contact_value = (data['contact_value'] or '').strip()
    if 'name' in data:
        contact.name = (data['name'] or '').strip()
    if 'order_in_escalation' in data:
        contact.order_in_escalation = int(data['order_in_escalation'])

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
