import uuid

from .db import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # Auth
    auth_provider = db.Column(db.String(20), nullable=False)       # apple | google | email
    email = db.Column(db.String(255), nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)       # only for email provider
    apple_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)
    google_sub = db.Column(db.String(255), unique=True, nullable=True, index=True)

    # Phone (OTP reputation, optional)
    phone_number = db.Column(db.String(30), nullable=True)
    phone_verified = db.Column(db.Boolean, nullable=False, default=False, server_default='false')

    # APNs push token (updated by client after every sign-in)
    apns_device_token = db.Column(db.String(200), nullable=True)
    apns_environment = db.Column(db.String(20), nullable=True)     # sandbox | production

    # Reputation
    reputation_score = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    reputation_level = db.Column(
        db.String(20), nullable=False, default='normal', server_default='normal'
    )

    # Account state
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default='true')
    scheduled_deletion_at = db.Column(db.DateTime, nullable=True)  # GDPR Art. 17

    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime, nullable=False, server_default=db.func.now(), onupdate=db.func.now()
    )

    # Partial unique index: email must be unique within the email provider
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
            'created_at': self.created_at.isoformat() + 'Z' if self.created_at else None,
            'updated_at': self.updated_at.isoformat() + 'Z' if self.updated_at else None,
        }
