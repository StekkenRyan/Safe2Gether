"""Lightweight Redis-backed rate limiting for abuse-prone endpoints.

A fixed-window counter (``INCR`` + ``EXPIRE``) keyed on ``<scope>:<client_ip>``.
Deliberately built on the same ``redis.from_url`` idiom as the rest of the app
so it transparently uses the fakeredis instance under test.

Design choices:
- **Fail-open**: a Redis outage never blocks a request. Availability of the
  safety features takes precedence over strict enforcement (same posture as the
  alarm rate-limit in ``alarm.py``).
- **Surgical**: applied only to the abuse-prone auth routes via decorator —
  there is intentionally NO global limit, so the panic-button / location /
  heartbeat paths can never be throttled.
- **Toggle**: disabled when ``app.config['RATELIMIT_ENABLED']`` is False (the
  default under TESTING), so the existing suite is unaffected unless a test
  opts in.
"""
import functools
import os

import redis as redis_lib
from flask import current_app, jsonify, request

from .redis_keys import RATE_LIMIT


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def client_ip() -> str:
    """Best-effort real client IP.

    Behind the Cloudflare tunnel the originating IP is in ``CF-Connecting-IP``;
    ``remote_addr`` is only the tunnel/container address. Falls back defensively.
    """
    return request.headers.get('CF-Connecting-IP') or request.remote_addr or 'unknown'


def rate_limit(limit: int, window_seconds: int, scope: str):
    """Allow at most ``limit`` requests per ``window_seconds`` per client IP for
    ``scope``. Returns 429 (with ``Retry-After``) once exceeded.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            if not current_app.config.get('RATELIMIT_ENABLED', True):
                return f(*args, **kwargs)

            key = f'{RATE_LIMIT}{scope}:{client_ip()}'
            try:
                r = _redis()
                current = r.incr(key)
                if current == 1:
                    r.expire(key, window_seconds)
                if current > limit:
                    ttl = r.ttl(key)
                    retry_after = ttl if (ttl and ttl > 0) else window_seconds
                    resp = jsonify({
                        'error': 'Too Many Requests',
                        'code': 'RATE_LIMITED',
                        'detail': f'Zu viele Anfragen. Bitte in {retry_after}s erneut versuchen.',
                    })
                    resp.status_code = 429
                    resp.headers['Retry-After'] = str(retry_after)
                    return resp
            except redis_lib.RedisError:
                # Fail open — never block a request because Redis is unavailable.
                return f(*args, **kwargs)

            return f(*args, **kwargs)
        return wrapped
    return decorator
