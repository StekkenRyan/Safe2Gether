import uuid
from datetime import datetime, timedelta, timezone

from .db import db

_ALARM_RETENTION_DAYS = 30
_REPUTATION_RETENTION_DAYS = 30


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Auth
    auth_provider = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    apple_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)

    # Phone (OTP reputation, optional — requires explicit consent)
    phone_number = db.Column(db.String(30), nullable=True)
    phone_verified = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    # APNs push token
    apns_device_token = db.Column(db.String(200), nullable=True)
    apns_environment = db.Column(db.String(20), nullable=True)

    # Reputation
    reputation_score = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    reputation_level = db.Column(
        db.String(20), nullable=False, default='normal', server_default='normal'
    )

    # Privacy preferences (Art. 21 DSGVO — right to object)
    nearby_alerting_enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default='true'
    )

    # Last known H3 cell — persisted as a DB fallback when the Redis TTL has
    # expired (e.g. device was offline). Written on every PUT /geohash.
    last_geohash = db.Column(db.String(20), nullable=True)

    # Optional home address — used to pre-fill cantGetHome alerts on the client
    home_address_label = db.Column(db.String(100), nullable=True)
    home_address = db.Column(db.String(300), nullable=True)

    # User-configurable escalation chain. Stored as comma-separated stage names
    # (small ordered list; trade-off vs. JSON column is negligible for v1.0).
    escalation_order = db.Column(
        db.Text, nullable=False,
        default='device_local,contacts,community',
        server_default='device_local,contacts,community',
    )
    escalation_delay_seconds = db.Column(
        db.Integer, nullable=False, default=30, server_default='30',
    )

    # Account state
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    scheduled_deletion_at = db.Column(db.DateTime, nullable=True)  # GDPR Art. 17

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now()
    )

    reputation_actions = db.relationship(
        'ReputationAction', back_populates='user', lazy='dynamic',
        order_by='ReputationAction.created_at.desc()',
    )
    emergency_contacts = db.relationship(
        'EmergencyContact', back_populates='user', lazy='dynamic',
        order_by='EmergencyContact.order_in_escalation',
    )

    __table_args__ = (
        db.Index('uq_users_email_provider', 'email',
                 postgresql_where=db.text("auth_provider = 'email'"),
                 unique=True),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'email': self.email,
            'phone_number': self.phone_number,
            'phone_verified': self.phone_verified,
            'auth_provider': self.auth_provider,
            'reputation_score': self.reputation_score,
            'reputation_level': self.reputation_level,
            'nearby_alerting_enabled': self.nearby_alerting_enabled,
            'home_address_label': self.home_address_label,
            'home_address': self.home_address,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'updated_at': self.updated_at.isoformat() + 'Z' if self.updated_at else None,
        }

    def escalation_to_dict(self) -> dict:
        return {
            'escalation_order': [
                s for s in (self.escalation_order or '').split(',') if s
            ],
            'delay_seconds_between_stages': self.escalation_delay_seconds,
        }


class ReputationAction(db.Model):
    __tablename__ = 'reputation_actions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True
    )
    action_type = db.Column(db.String(40), nullable=False)
    score_delta = db.Column(db.Integer, nullable=False)
    alarm_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    # DSGVO Art. 5: retention limited to 30 days
    auto_delete_at = db.Column(db.DateTime, nullable=False)

    user = db.relationship('User', back_populates='reputation_actions')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.auto_delete_at is None:
            self.auto_delete_at = (
                datetime.now(timezone.utc) + timedelta(days=_REPUTATION_RETENTION_DAYS)
            )

    def to_dict(self) -> dict:
        return {
            'action_type': self.action_type,
            'score_delta': self.score_delta,
            'alarm_id': self.alarm_id,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
        }


class EmergencyContact(db.Model):
    __tablename__ = 'emergency_contacts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True
    )
    contact_type = db.Column(db.String(20), nullable=False)
    contact_value = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    order_in_escalation = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    user = db.relationship('User', back_populates='emergency_contacts')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'contact_type': self.contact_type,
            'contact_value': self.contact_value,
            'name': self.name,
            'order_in_escalation': self.order_in_escalation,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
        }


class Alarm(db.Model):
    __tablename__ = 'alarms'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(
        db.String(36), db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True
    )
    triggered_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    trigger_source = db.Column(db.String(30), nullable=False)
    alert_type = db.Column(
        db.String(30), nullable=False, default='panic', server_default='panic'
    )
    # contacts | community | contacts_and_community — overrides escalation chain when set
    audience = db.Column(
        db.String(30), nullable=False,
        default='contacts_and_community', server_default='contacts_and_community',
    )
    status = db.Column(db.String(20), nullable=False, default='active', server_default='active')
    escalation_stage = db.Column(db.String(20), nullable=False, default='device_local')
    geohash_snapshot = db.Column(db.String(20), nullable=True)
    exact_latitude = db.Column(db.Float, nullable=True)
    exact_longitude = db.Column(db.Float, nullable=True)
    # Only set for cant_get_home alerts — coarse distance category to home
    home_distance_category = db.Column(db.String(20), nullable=True)

    # DSGVO: auto-delete after 30 days
    auto_delete_at = db.Column(db.DateTime, nullable=False)

    responders = db.relationship('AlarmResponder', back_populates='alarm', lazy='dynamic')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.auto_delete_at is None:
            self.auto_delete_at = (
                datetime.now(timezone.utc) + timedelta(days=_ALARM_RETENTION_DAYS)
            )

    def to_dict(self, include_exact_location: bool = False) -> dict:
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'triggered_at': self.triggered_at.isoformat() + 'Z' if self.triggered_at else None,
            'trigger_source': self.trigger_source,
            'alert_type': self.alert_type,
            'audience': self.audience,
            'home_distance_category': self.home_distance_category,
            'status': self.status,
            'escalation_stage': self.escalation_stage,
            'geohash_snapshot': self.geohash_snapshot,
            'responders': [r.user_id for r in self.responders.all()],
            'auto_delete_at': (
                self.auto_delete_at.isoformat() + 'Z' if self.auto_delete_at else None
            ),
        }
        if include_exact_location and self.exact_latitude is not None:
            data['exact_location'] = {
                'latitude': self.exact_latitude,
                'longitude': self.exact_longitude,
            }
        return data


class AlarmResponder(db.Model):
    """Users who pressed 'Ich helfe' for an alarm."""
    __tablename__ = 'alarm_responders'

    alarm_id = db.Column(
        db.String(36), db.ForeignKey('alarms.id', ondelete='CASCADE'),
        primary_key=True, nullable=False,
    )
    user_id = db.Column(db.String(36), nullable=False, primary_key=True)
    responded_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    alarm = db.relationship('Alarm', back_populates='responders')


class PasswordReset(db.Model):
    __tablename__ = 'password_resets'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True
    )
    token_hash = db.Column(db.Text, nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)


class SafetyTimer(db.Model):
    """Dead Man's Switch timer. Escalates to contacts (and optionally community)
    if the owner does not check in before expires_at + GRACE_PERIOD_SECONDS."""
    __tablename__ = 'safety_timers'

    GRACE_PERIOD_SECONDS = 300  # 5 minutes to respond after expiry before contacts are notified

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    duration_seconds = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    # active | checkin_requested | triggered | cancelled | checked_in
    status = db.Column(db.String(30), nullable=False, default='active', server_default='active')
    # Comma-separated user IDs to notify when timer triggers (in_app contacts)
    notify_contact_ids = db.Column(db.Text, nullable=True)
    notify_community = db.Column(
        db.Boolean, nullable=False, default=False, server_default='false'
    )
    note = db.Column(db.String(200), nullable=True)
    checkin_requested_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'duration_seconds': self.duration_seconds,
            'expires_at': self.expires_at.isoformat() + 'Z' if self.expires_at else None,
            'status': self.status,
            'notify_contact_ids': [c for c in (self.notify_contact_ids or '').split(',') if c],
            'notify_community': self.notify_community,
            'note': self.note,
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
        }
