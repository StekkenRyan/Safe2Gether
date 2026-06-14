"""Rate-limiting tests for the abuse-prone auth endpoints.

Limiting is disabled by default under TESTING; these tests opt in by flipping
``RATELIMIT_ENABLED`` on the app. The limiter runs against the shared fakeredis
instance (see conftest) which is flushed between tests.
"""
import pytest


@pytest.fixture
def rl_app(app):
    app.config['RATELIMIT_ENABLED'] = True
    return app


@pytest.fixture
def rl_client(rl_app):
    return rl_app.test_client()


def test_signin_rate_limited_after_threshold(rl_client, mock_redis):
    """11th sign-in attempt within the window is rejected with 429."""
    # Invalid (too-short) password → 400, but every attempt still counts.
    payload = {'provider': 'email', 'email': 'rl@example.com', 'password': 'short'}
    for _ in range(10):
        resp = rl_client.post('/api/v1/auth/signin', json=payload)
        assert resp.status_code != 429

    blocked = rl_client.post('/api/v1/auth/signin', json=payload)
    assert blocked.status_code == 429
    assert blocked.get_json()['code'] == 'RATE_LIMITED'
    assert 'Retry-After' in blocked.headers


def test_password_reset_request_rate_limited(rl_client, mock_redis):
    """6th reset request within the hour window is rejected (email-bomb guard)."""
    for _ in range(5):
        resp = rl_client.post('/api/v1/auth/password-reset/request',
                              json={'email': 'victim@example.com'})
        assert resp.status_code == 204

    blocked = rl_client.post('/api/v1/auth/password-reset/request',
                            json={'email': 'victim@example.com'})
    assert blocked.status_code == 429


def test_safety_endpoints_not_rate_limited(rl_client):
    """The health/alarm paths must never be throttled — only auth is limited."""
    for _ in range(40):
        assert rl_client.get('/api/v1/health').status_code == 200


def test_rate_limit_disabled_by_default(client):
    """With the default test config the limiter is off — no 429s."""
    payload = {'provider': 'email', 'email': 'nolimit@example.com', 'password': 'password123'}
    statuses = {client.post('/api/v1/auth/signin', json=payload).status_code for _ in range(15)}
    assert 429 not in statuses
