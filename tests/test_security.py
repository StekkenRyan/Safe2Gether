"""Security-focused tests — cross-cutting concerns."""
import time

import jwt
import pytest

# ─── Authentication enforcement ───────────────────────────────────────────────

PROTECTED_ENDPOINTS = [
    ('GET', '/api/v1/users/me'),
    ('PATCH', '/api/v1/users/me'),
    ('DELETE', '/api/v1/users/me'),
    ('GET', '/api/v1/users/me/reputation'),
    ('GET', '/api/v1/contacts'),
    ('POST', '/api/v1/contacts'),
    ('POST', '/api/v1/alarms'),
    ('PUT', '/api/v1/geohash'),
    ('POST', '/api/v1/heartbeat'),
    ('PUT', '/api/v1/auth/device-token'),
    ('POST', '/api/v1/auth/logout'),
]


@pytest.mark.parametrize('method,path', PROTECTED_ENDPOINTS)
def test_protected_endpoint_rejects_unauthenticated(client, method, path):
    resp = getattr(client, method.lower())(path, json={})
    assert resp.status_code == 401, f'{method} {path} must require auth'


def test_expired_token_returns_401(client, auth_user):
    user, _ = auth_user
    # Forge a token that is already expired
    expired = jwt.encode(
        {'sub': user.id, 'type': 'access', 'exp': int(time.time()) - 10},
        'test-jwt-secret-do-not-use-in-production',
        algorithm='HS256',
    )
    resp = client.get('/api/v1/users/me', headers={'Authorization': f'Bearer {expired}'})
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 'TOKEN_EXPIRED'


def test_tampered_token_rejected(client, auth_user):
    _, token = auth_user
    # Flip a character in the signature
    parts = token.split('.')
    parts[-1] = parts[-1][:-1] + ('A' if parts[-1][-1] != 'A' else 'B')
    bad_token = '.'.join(parts)
    resp = client.get('/api/v1/users/me', headers={'Authorization': f'Bearer {bad_token}'})
    assert resp.status_code == 401


def test_refresh_token_used_as_access_token_rejected(client, auth_user):
    user, _ = auth_user
    from app.token import create_refresh_token
    refresh = create_refresh_token(user.id)
    resp = client.get('/api/v1/users/me', headers={'Authorization': f'Bearer {refresh}'})
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 'WRONG_TOKEN_TYPE'


def test_missing_bearer_prefix_rejected(client, auth_user):
    _, token = auth_user
    resp = client.get('/api/v1/users/me', headers={'Authorization': token})
    assert resp.status_code == 401


# ─── Input validation ─────────────────────────────────────────────────────────

def test_alarm_rejects_client_alarm_id(client, auth_headers):
    """Server must never use a client-supplied alarm_id."""
    attacker_id = 'ffffffff-ffff-ffff-ffff-ffffffffffff'
    resp = client.post('/api/v1/alarms', json={
        'trigger_source': 'in_app', 'alarm_id': attacker_id,
    }, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.get_json()['id'] != attacker_id


def test_geohash_offline_duration_max(client, auth_headers):
    """604800 (7 days) is accepted; 604801 is not."""
    resp_ok = client.put('/api/v1/geohash', json={
        'geohash': '871f1d48dffffff', 'status': 'expected_offline',
        'offline_duration_seconds': 604800,
    }, headers=auth_headers)
    assert resp_ok.status_code == 204

    resp_bad = client.put('/api/v1/geohash', json={
        'geohash': '871f1d48dffffff', 'status': 'expected_offline',
        'offline_duration_seconds': 604801,
    }, headers=auth_headers)
    assert resp_bad.status_code == 400


def test_contact_order_boundary(client, auth_headers):
    """order_in_escalation must be 1–100."""
    resp_low = client.post('/api/v1/contacts', json={
        'contact_type': 'phone', 'contact_value': '+4915112345678',
        'name': 'x', 'order_in_escalation': 0,
    }, headers=auth_headers)
    assert resp_low.status_code == 400

    resp_high = client.post('/api/v1/contacts', json={
        'contact_type': 'phone', 'contact_value': '+4915112345678',
        'name': 'x', 'order_in_escalation': 101,
    }, headers=auth_headers)
    assert resp_high.status_code == 400


# ─── Security headers ─────────────────────────────────────────────────────────

def test_security_headers_present(client):
    resp = client.get('/api/v1/health')
    assert resp.headers.get('X-Content-Type-Options') == 'nosniff'
    assert resp.headers.get('X-Frame-Options') == 'DENY'
    assert resp.headers.get('Referrer-Policy') == 'no-referrer'


# ─── Access control ───────────────────────────────────────────────────────────

def test_user_cannot_access_other_users_alarm(client, make_user):
    _, token_a = make_user(email='sec_a@example.com')
    _, token_b = make_user(email='sec_b@example.com')

    alarm_id = client.post(
        '/api/v1/alarms', json={'trigger_source': 'in_app'},
        headers={'Authorization': f'Bearer {token_a}'},
    ).get_json()['id']

    resp = client.get(
        f'/api/v1/alarms/{alarm_id}',
        headers={'Authorization': f'Bearer {token_b}'},
    )
    assert resp.status_code == 404


def test_deleted_user_cannot_authenticate(client, auth_user, auth_headers):
    """After deletion, even a valid JWT should not return profile data."""
    client.delete('/api/v1/users/me', headers=auth_headers)
    resp = client.get('/api/v1/users/me', headers=auth_headers)
    assert resp.status_code == 404


# ─── DSGVO — PII erasure ──────────────────────────────────────────────────────

def test_deletion_anonymises_pii_immediately(client, app, auth_user, auth_headers):
    from app.db import db
    from app.models import User

    user, _ = auth_user
    client.delete('/api/v1/users/me', headers=auth_headers)

    with app.app_context():
        u = db.session.get(User, user.id)
        assert u.email is None
        assert u.password_hash is None
        assert u.apple_sub is None
        assert u.google_sub is None
        assert u.phone_number is None
        assert u.apns_device_token is None
        assert u.scheduled_deletion_at is not None


def test_nearby_alerting_opt_out_field(client, auth_headers):
    """Users can opt out of community alerts (Art. 21 DSGVO)."""
    resp = client.patch('/api/v1/users/me', json={'nearby_alerting_enabled': False},
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['nearby_alerting_enabled'] is False

    # Confirm it persists
    profile = client.get('/api/v1/users/me', headers=auth_headers).get_json()
    assert profile['nearby_alerting_enabled'] is False
