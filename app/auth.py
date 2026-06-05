"""Authentication blueprint — POST /api/v1/auth/*

Single sign-in endpoint for all three providers (Apple / Google / Email).
First call creates the account; subsequent calls return the existing one.
"""
import hashlib
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta

import bcrypt
import httpx
import jwt as pyjwt
import redis as redis_lib
from flask import Blueprint, g, jsonify, render_template, request
from flask_mail import Message
from jwt.algorithms import RSAAlgorithm

from . import mail
from .db import db
from .models import PasswordReset, User
from .redis_keys import JWKS_APPLE, JWKS_GOOGLE
from .token import (
    ACCESS_TTL,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    require_auth,
    revoke_refresh_token,
)

logger = logging.getLogger(__name__)
bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')

_APPLE_JWKS_URL = 'https://appleid.apple.com/auth/keys'
_APPLE_ISSUER = 'https://appleid.apple.com'
_GOOGLE_JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
_GOOGLE_ISSUER = 'https://accounts.google.com'
_JWKS_CACHE_TTL = 43200  # 12 hours

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')
_APNS_TOKEN_RE = re.compile(r'^[a-f0-9]{64}$', re.IGNORECASE)


def _redis_client() -> redis_lib.Redis:
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    return redis_lib.from_url(url, socket_connect_timeout=2, decode_responses=True)


def _get_jwks(url: str, cache_key: str) -> dict:
    """Fetch JWKS from URL, caching the result in Redis."""
    try:
        cached = _redis_client().get(cache_key)
        if cached:
            return json.loads(cached)
    except (redis_lib.RedisError, json.JSONDecodeError):
        pass

    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    jwks = resp.json()

    try:
        _redis_client().setex(cache_key, _JWKS_CACHE_TTL, json.dumps(jwks))
    except redis_lib.RedisError:
        pass

    return jwks


def _public_key_for(jwks: dict, kid: str):
    for key_data in jwks.get('keys', []):
        if key_data.get('kid') == kid:
            return RSAAlgorithm.from_jwk(key_data)
    return None


def _verify_apple_token(id_token: str) -> dict:
    bundle_id = os.environ.get('APNS_BUNDLE_ID', 'com.safe2gether.app')
    header = pyjwt.get_unverified_header(id_token)
    kid = header.get('kid')

    jwks = _get_jwks(_APPLE_JWKS_URL, JWKS_APPLE)
    public_key = _public_key_for(jwks, kid)
    if public_key is None:
        # Key may have rotated — bust cache and retry once
        try:
            _redis_client().delete(JWKS_APPLE)
        except redis_lib.RedisError:
            pass
        jwks = _get_jwks(_APPLE_JWKS_URL, JWKS_APPLE)
        public_key = _public_key_for(jwks, kid)
    if public_key is None:
        raise ValueError('Apple public key not found')

    return pyjwt.decode(
        id_token, public_key, algorithms=['RS256'],
        audience=bundle_id, issuer=_APPLE_ISSUER,
    )


def _verify_google_token(id_token: str) -> dict:
    client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    header = pyjwt.get_unverified_header(id_token)
    kid = header.get('kid')

    jwks = _get_jwks(_GOOGLE_JWKS_URL, JWKS_GOOGLE)
    public_key = _public_key_for(jwks, kid)
    if public_key is None:
        try:
            _redis_client().delete(JWKS_GOOGLE)
        except redis_lib.RedisError:
            pass
        jwks = _get_jwks(_GOOGLE_JWKS_URL, JWKS_GOOGLE)
        public_key = _public_key_for(jwks, kid)
    if public_key is None:
        raise ValueError('Google public key not found')

    return pyjwt.decode(
        id_token, public_key, algorithms=['RS256'],
        audience=client_id, issuer=_GOOGLE_ISSUER,
    )


def _auth_response(user: User) -> tuple:
    db.session.refresh(user)
    return jsonify({
        'access_token': create_access_token(user.id),
        'refresh_token': create_refresh_token(user.id),
        'token_type': 'Bearer',
        'expires_in': ACCESS_TTL,
        'user': user.to_dict(),
    }), 200


@bp.post('/signin')
def signin():
    """Sign in or create account with Apple, Google, or email/password."""
    data = request.get_json(silent=True) or {}
    provider = data.get('provider')

    if provider not in ('apple', 'google', 'email'):
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_PROVIDER',
                        'detail': 'provider must be one of: apple, google, email'}), 400

    # ── Apple ──────────────────────────────────────────────────────────────────
    if provider == 'apple':
        id_token = data.get('id_token')
        if not id_token:
            return jsonify({'error': 'Bad Request', 'code': 'MISSING_ID_TOKEN'}), 400
        try:
            claims = _verify_apple_token(id_token)
        except (pyjwt.PyJWTError, ValueError, httpx.HTTPError):
            logger.warning('Apple token verification failed')
            return jsonify({'error': 'Unauthorized', 'code': 'INVALID_ID_TOKEN'}), 401

        apple_sub = claims['sub']
        user = User.query.filter_by(apple_sub=apple_sub).first()
        if user is None:
            user = User(apple_sub=apple_sub, email=claims.get('email'), auth_provider='apple')
            db.session.add(user)
            db.session.commit()

    # ── Google ─────────────────────────────────────────────────────────────────
    elif provider == 'google':
        id_token = data.get('id_token')
        if not id_token:
            return jsonify({'error': 'Bad Request', 'code': 'MISSING_ID_TOKEN'}), 400
        try:
            claims = _verify_google_token(id_token)
        except (pyjwt.PyJWTError, ValueError, httpx.HTTPError):
            logger.warning('Google token verification failed')
            return jsonify({'error': 'Unauthorized', 'code': 'INVALID_ID_TOKEN'}), 401

        google_sub = claims['sub']
        user = User.query.filter_by(google_sub=google_sub).first()
        if user is None:
            user = User(google_sub=google_sub, email=claims.get('email'), auth_provider='google')
            db.session.add(user)
            db.session.commit()

    # ── Email / Password ───────────────────────────────────────────────────────
    else:
        email = (data.get('email') or '').lower().strip()
        password = data.get('password') or ''

        if not email or not password:
            return jsonify({'error': 'Bad Request', 'code': 'MISSING_CREDENTIALS'}), 400
        if not _EMAIL_RE.match(email):
            return jsonify({'error': 'Bad Request', 'code': 'INVALID_EMAIL'}), 400
        if len(password) < 8:
            return jsonify({'error': 'Bad Request', 'code': 'PASSWORD_TOO_SHORT',
                            'detail': 'Password must be at least 8 characters.'}), 400

        user = User.query.filter_by(email=email, auth_provider='email').first()
        if user is None:
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            user = User(email=email, password_hash=pw_hash, auth_provider='email')
            db.session.add(user)
            db.session.commit()
        else:
            if not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
                return jsonify({'error': 'Unauthorized', 'code': 'INVALID_CREDENTIALS'}), 401

    if not user.is_active:
        return jsonify({'error': 'Forbidden', 'code': 'ACCOUNT_DEACTIVATED'}), 403

    return _auth_response(user)


@bp.post('/refresh')
def refresh():
    data = request.get_json(silent=True) or {}
    refresh_token = data.get('refresh_token')
    if not refresh_token:
        return jsonify({'error': 'Unauthorized', 'code': 'MISSING_REFRESH_TOKEN'}), 401

    user_id = decode_refresh_token(refresh_token)
    if not user_id:
        return jsonify({'error': 'Unauthorized', 'code': 'INVALID_REFRESH_TOKEN'}), 401

    return jsonify({'access_token': create_access_token(user_id), 'expires_in': ACCESS_TTL}), 200


@bp.post('/logout')
@require_auth
def logout():
    data = request.get_json(silent=True) or {}
    refresh_token = data.get('refresh_token')
    if refresh_token:
        revoke_refresh_token(refresh_token)
    return '', 204


@bp.put('/device-token')
@require_auth
def update_device_token():
    data = request.get_json(silent=True) or {}
    device_token = data.get('device_token') or ''
    environment = data.get('environment')

    if not _APNS_TOKEN_RE.match(device_token):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_DEVICE_TOKEN',
            'detail': 'device_token must be a 64-character hex string',
        }), 400
    if environment not in ('sandbox', 'production'):
        return jsonify({'error': 'Bad Request', 'code': 'INVALID_ENVIRONMENT'}), 400

    user = db.session.get(User, g.user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

    user.apns_device_token = device_token
    user.apns_environment = environment
    db.session.commit()
    return '', 204


@bp.post('/verify-phone')
@require_auth
def verify_phone():
    """Phone OTP verification — not yet implemented (requires SMS provider)."""
    return jsonify({
        'error': 'Not Implemented', 'code': 'NOT_IMPLEMENTED',
        'detail': 'Phone verification will be available once an SMS provider is configured.',
    }), 501


# ── Password Reset ─────────────────────────────────────────────────────────────

_RESET_TOKEN_TTL_HOURS = 24


def _send_password_reset_email(to_email: str, reset_link: str) -> None:
    subject = 'Dein Safe2Gether Passwort zurücksetzen'
    html_body = render_template('email/password_reset.html', reset_link=reset_link)
    msg = Message(subject=subject, recipients=[to_email], html=html_body)
    try:
        mail.send(msg)
    except Exception:
        logger.exception('Failed to send password reset email to %s', to_email)


@bp.post('/password-reset/request')
def password_reset_request():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').lower().strip()

    user = User.query.filter_by(email=email, auth_provider='email').first()
    if user and user.is_active:
        # Invalidate any existing open tokens for this user
        now = datetime.utcnow()
        PasswordReset.query.filter_by(user_id=user.id).filter(
            PasswordReset.used_at.is_(None)
        ).update({'used_at': now})

        token = secrets.token_hex(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        reset = PasswordReset(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(hours=_RESET_TOKEN_TTL_HOURS),
        )
        db.session.add(reset)
        db.session.commit()

        reset_link = f'safe2gether://reset-password?token={token}'
        _send_password_reset_email(user.email, reset_link)

    # Always 204 — never reveal whether the email exists
    return '', 204


@bp.post('/password-reset/confirm')
def password_reset_confirm():
    data = request.get_json(silent=True) or {}
    token = data.get('token') or ''
    new_password = data.get('new_password') or ''

    if len(new_password) < 8:
        return jsonify({'error': 'new_password muss mindestens 8 Zeichen lang sein'}), 400

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset = PasswordReset.query.filter_by(token_hash=token_hash).first()

    now = datetime.utcnow()
    if reset is None or reset.used_at is not None or reset.expires_at < now:
        return jsonify({'error': 'Token ungültig oder abgelaufen'}), 400

    reset.used_at = now

    user = db.session.get(User, reset.user_id)
    user.password_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    db.session.commit()

    return '', 204
