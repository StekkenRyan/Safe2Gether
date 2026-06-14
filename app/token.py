"""JWT token utilities and the require_auth request decorator."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import redis as redis_lib
from flask import g, jsonify, request

from .redis_keys import REFRESH_JTI, REFRESH_USER_JTIS

_ALGORITHM = 'HS256'
ACCESS_TTL = int(os.environ.get('JWT_ACCESS_TOKEN_EXPIRES', 3600))
_REFRESH_TTL = int(os.environ.get('JWT_REFRESH_TOKEN_EXPIRES', 2592000))


def _secret() -> str:
    secret = os.environ.get('JWT_SECRET_KEY') or ''
    if not secret:
        raise RuntimeError(
            'JWT_SECRET_KEY environment variable is not set. '
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    return secret


def _redis() -> redis_lib.Redis:
    url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    return redis_lib.from_url(url, socket_connect_timeout=2, decode_responses=True)


# ─── Token creation ───────────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        'sub': user_id,
        'type': 'access',
        'iat': now,
        'exp': now + timedelta(seconds=ACCESS_TTL),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    payload = {
        'sub': user_id,
        'type': 'refresh',
        'jti': jti,
        'iat': now,
        'exp': now + timedelta(seconds=_REFRESH_TTL),
    }
    token = jwt.encode(payload, _secret(), algorithm=_ALGORITHM)
    try:
        r = _redis()
        pipe = r.pipeline()
        pipe.setex(f'{REFRESH_JTI}{jti}', _REFRESH_TTL, user_id)
        # Track the JTI in a per-user set so every session can be revoked at
        # once (account deletion / refresh-token reuse detection).
        pipe.sadd(f'{REFRESH_USER_JTIS}{user_id}', jti)
        pipe.expire(f'{REFRESH_USER_JTIS}{user_id}', _REFRESH_TTL)
        pipe.execute()
    except redis_lib.RedisError:
        # If Redis is temporarily unavailable, the token still works until it's
        # used — at that point the missing JTI will cause a 401, forcing re-login.
        pass
    return token


# ─── Token validation ─────────────────────────────────────────────────────────

def decode_refresh_token(token: str) -> str | None:
    """Return user_id if the refresh token is valid and not revoked, else None."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None

    if payload.get('type') != 'refresh':
        return None

    jti = payload.get('jti')
    if not jti:
        return None

    try:
        stored_user_id = _redis().get(f'{REFRESH_JTI}{jti}')
    except redis_lib.RedisError:
        return None

    if stored_user_id != payload['sub']:
        return None

    return payload['sub']


def verify_refresh_signature(token: str) -> dict | None:
    """Return the decoded payload if the token is a structurally-valid,
    non-expired refresh token — WITHOUT checking the JTI store.

    Used for reuse detection: a validly-signed refresh token whose JTI is no
    longer active indicates a rotated/revoked token being replayed.
    """
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get('type') != 'refresh':
        return None
    return payload


def revoke_refresh_token(token: str) -> None:
    """Delete the refresh token's JTI from Redis (logout / rotation)."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM],
                             options={'verify_exp': False})
        jti = payload.get('jti')
        if jti and payload.get('type') == 'refresh':
            r = _redis()
            pipe = r.pipeline()
            pipe.delete(f'{REFRESH_JTI}{jti}')
            sub = payload.get('sub')
            if sub:
                pipe.srem(f'{REFRESH_USER_JTIS}{sub}', jti)
            pipe.execute()
    except (jwt.PyJWTError, redis_lib.RedisError):
        pass


def revoke_all_refresh_tokens(user_id: str) -> None:
    """Invalidate every refresh token issued to a user (account deletion or
    suspected token reuse). Idempotent and fail-safe on Redis errors."""
    try:
        r = _redis()
        set_key = f'{REFRESH_USER_JTIS}{user_id}'
        jtis = r.smembers(set_key)
        pipe = r.pipeline()
        for jti in jtis:
            pipe.delete(f'{REFRESH_JTI}{jti}')
        pipe.delete(set_key)
        pipe.execute()
    except redis_lib.RedisError:
        pass


# ─── Auth decorator ───────────────────────────────────────────────────────────

def require_auth(f):
    """Validate Bearer JWT and set g.user_id. Returns 401 on failure."""
    @wraps(f)
    def decorated(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized', 'code': 'MISSING_TOKEN'}), 401
        raw = header[7:]
        try:
            payload = jwt.decode(raw, _secret(), algorithms=[_ALGORITHM])
        except jwt.ExpiredSignatureError:
            return jsonify({
                'error': 'Unauthorized',
                'code': 'TOKEN_EXPIRED',
                'detail': 'Use /api/v1/auth/refresh to obtain a new token.',
            }), 401
        except jwt.PyJWTError:
            return jsonify({'error': 'Unauthorized', 'code': 'INVALID_TOKEN'}), 401

        if payload.get('type') != 'access':
            return jsonify({'error': 'Unauthorized', 'code': 'WRONG_TOKEN_TYPE'}), 401

        user_id = payload['sub']

        # Centralised account-state enforcement. A valid signature alone is not
        # enough — the account must still exist and be active. This closes the
        # gap where endpoints that don't separately load the user (e.g.
        # PUT /geohash) would otherwise honour tokens belonging to a deleted or
        # deactivated account until the short-lived access token expired.
        # Returns 404 (USER_NOT_FOUND) to match the convention already used by
        # the per-endpoint checks and the existing test-suite contract.
        from .db import db
        from .models import User
        user = db.session.get(User, user_id)
        if user is None or not user.is_active:
            return jsonify({'error': 'Not Found', 'code': 'USER_NOT_FOUND'}), 404

        g.user_id = user_id
        g.user = user
        return f(*args, **kwargs)
    return decorated
