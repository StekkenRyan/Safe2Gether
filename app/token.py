"""JWT token utilities and the require_auth request decorator."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import redis as redis_lib
from flask import g, jsonify, request

from .redis_keys import REFRESH_JTI

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
        _redis().setex(f'{REFRESH_JTI}{jti}', _REFRESH_TTL, user_id)
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


def revoke_refresh_token(token: str) -> None:
    """Delete the refresh token's JTI from Redis (logout)."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM],
                             options={'verify_exp': False})
        jti = payload.get('jti')
        if jti and payload.get('type') == 'refresh':
            _redis().delete(f'{REFRESH_JTI}{jti}')
    except (jwt.PyJWTError, redis_lib.RedisError):
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

        g.user_id = payload['sub']
        return f(*args, **kwargs)
    return decorated
