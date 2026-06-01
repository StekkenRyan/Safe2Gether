import uuid
from .db import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)

    # Auth fields added in v1.0 Auth session
