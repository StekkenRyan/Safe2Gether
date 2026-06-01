"""Authentication blueprint — POST /api/v1/auth/*

Single sign-in endpoint for all three providers (Apple / Google / Email).
First call creates the account; subsequent calls return the existing one.
"""
import json
import os

import bcrypt
import httpx
import jwt as pyjwt
import redis as redis_lib
from flask import Blueprint, g, jsonify, request
from jwt.algorithms import RSAAlgorithm

from .db import db
from .models import User
from .token import (
    ACCESS_TTL,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    require_auth,
    revoke_refresh_token,
)

bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')

# ─── JWKS helpers ─────────────────────────────────────────────────────────────

_APPLE_JWKS_URL = 'https://appleid.apple.com/auth/keys'
_APPLE_ISSUER = 'https://appleid.apple.com'
_GOOGLE_JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
_GOOGLE_ISSUER = 'https://accounts.google.com'
_JWKS_CACHE_TTL = 43200  # 12 hours


def _redis_client() -> redis_lib.Redis:
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    return redis_lib.from_url(url, socket_connect_timeout=2, decode_responses=True)


def _get_jwks(url: str, cache_key: str) -> dict:
    """Fetch JWKS from URL, caching the result in Redis."""
    try:
        r = _redis_client()
        cached = r.get(cache_key)
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
    """Find and deserialize the RSA public key matching `kid`."""
    for key_data in jwks.get('keys', []):
        if key_data.get('kid') == kid:
            return RSAAlgorithm.from_jwk(key_data)
    return None


def _verify_apple_token(id_token: str) -> dict:
    """Verify Apple identity token; return verified claims."""
    bundle_id = os.environ.get('APNS_BUNDLE_ID', 'com.safe2gether.app')
    header = pyjwt.get_unverified_header(id_token)
    kid = header.get('kid')

    jwks = _get_jwks(_APPLE_JWKS_URL, 'jwks:apple')
    public_key = _public_key_for(jwks, kid)

    if public_key is None:
        # Key may have rotated — bust the cache and retry once
        try:
            _redis_client().delete('jwks:apple')
        except redis_lib.RedisError:
            pass
        jwks = _get_jwks(_APPLE_JWKS_URL, 'jwks:apple')
        public_key = _public_key_for(jwks, kid)

    if public_key is None:
        raise ValueError('Apple public key not found for kid: ' + str(kid))

    return pyjwt.decode(
        id_token,
        public_key,
        algorithms=['RS256'],
        audience=bundle_id,
        issuer=_APPLE_ISSUER,
    )


def _verify_google_token(id_token: str) -> dict:
    """Verify Google ID token; return verified claims."""
    client_id = os.environ.get('GOOGLE_CLIENT_ID', '')
    header = pyjwt.get_unverified_header(id_token)
    kid = header.get('kid')

    jwks = _get_jwks(_GOOGLE_JWKS_URL, 'jwks:google')
    public_key = _public_key_for(jwks, kid)

    if public_key is None:
        try:
            _redis_client().delete('jwks:google')
        except redis_lib.RedisError:
            pass
        jwks = _get_jwks(_GOOGLE_JWKS_URL, 'jwks:google')
        public_key = _public_key_for(jwks, kid)

    if public_key is None:
        raise ValueError('Google public key not found for kid: ' + str(kid))

    return pyjwt.decode(
        id_token,
        public_key,
        algorithms=['RS256'],
        audience=client_id,
        issuer=_GOOGLE_ISSUER,
    )


# ─── Auth response helper ─────────────────────────────────────────────────────

def _auth_response(user: User) -> tuple:
    db.session.refresh(user)  # ensure server_default timestamps are loaded
    return jsonify({
        'access_token': create_access_token(user.id),
        'refresh_token': create_refresh_token(user.id),
        'token_type': 'Bearer',
        'expires_in': ACCESS_TTL,
        'user': user.to_dict(),
    }), 200


# ─── Endpoints ────────────────────────────────────────────────────────────────

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
        except (pyjwt.PyJWTError, ValueError, httpx.HTTPError) as exc:
            return jsonify({'error': 'Unauthorized', 'code': 'INVALID_ID_TOKEN',
                            'detail': str(exc)}), 401

        apple_sub = claims['sub']
        user = User.query.filter_by(apple_sub=apple_sub).first()
        if user is None:
            user = User(
                apple_sub=apple_sub,
                email=claims.get('email'),
                auth_provider='apple',
            )
            db.session.add(user)
            db.session.commit()

    # ── Google ─────────────────────────────────────────────────────────────────
    elif provider == 'google':
        id_token = data.get('id_token')
        if not id_token:
            return jsonify({'error': 'Bad Request', 'code': 'MISSING_ID_TOKEN'}), 400

        try:
            claims = _verify_google_token(id_token)
        except (pyjwt.PyJWTError, ValueError, httpx.HTTPError) as exc:
            return jsonify({'error': 'Unauthorized', 'code': 'INVALID_ID_TOKEN',
                            'detail': str(exc)}), 401

        google_sub = claims['sub']
        user = User.query.filter_by(google_sub=google_sub).first()
        if user is None:
            user = User(
                google_sub=google_sub,
                email=claims.get('email'),
                auth_provider='google',
            )
            db.session.add(user)
            db.session.commit()

    # ── Email / Password ───────────────────────────────────────────────────────
    else:
        email = (data.get('email') or '').lower().strip()
        password = data.get('password') or ''

        if not email or not password:
            return jsonify({'error': 'Bad Request', 'code': 'MISSING_CREDENTIALS'}), 400
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
    """Issue a new access token using a valid refresh token."""
    data = request.get_json(silent=True) or {}
    refresh_token = data.get('refresh_token')

    if not refresh_token:
        return jsonify({'error': 'Unauthorized', 'code': 'MISSING_REFRESH_TOKEN'}), 401

    user_id = decode_refresh_token(refresh_token)
    if not user_id:
        return jsonify({'error': 'Unauthorized', 'code': 'INVALID_REFRESH_TOKEN'}), 401

    return jsonify({
        'access_token': create_access_token(user_id),
        'expires_in': ACCESS_TTL,
    }), 200


@bp.post('/logout')
@require_auth
def logout():
    """Revoke the refresh token. The short-lived access token expires naturally."""
    data = request.get_json(silent=True) or {}
    refresh_token = data.get('refresh_token')
    if refresh_token:
        revoke_refresh_token(refresh_token)
    return '', 204


@bp.put('/device-token')
@require_auth
def update_device_token():
    """Register or update the APNs device token for push notifications."""
    data = request.get_json(silent=True) or {}
    device_token = data.get('device_token')
    environment = data.get('environment')

    if not device_token or environment not in ('sandbox', 'production'):
        return jsonify({
            'error': 'Bad Request', 'code': 'INVALID_REQUEST',
            'detail': 'device_token and environment (sandbox|production) required.',
        }), 400

    user = db.session.get(User, g.user_id)
    if not user:
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
