"""User profile endpoint tests — GET/PATCH/DELETE /api/v1/users/me"""

from app.db import db
from app.models import User


def test_get_me(client, auth_user, auth_headers):
    user, _ = auth_user
    resp = client.get('/api/v1/users/me', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['id'] == user.id
    assert data['email'] == user.email
    assert 'auth_provider' in data
    assert 'reputation_score' in data
    assert 'nearby_alerting_enabled' in data


def test_get_me_unauthenticated(client):
    resp = client.get('/api/v1/users/me')
    assert resp.status_code == 401


def test_patch_email(client, auth_headers):
    resp = client.patch('/api/v1/users/me', json={'email': 'new@example.com'},
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['email'] == 'new@example.com'


def test_patch_email_invalid_format(client, auth_headers):
    resp = client.patch('/api/v1/users/me', json={'email': 'notanemail'}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_EMAIL'


def test_patch_email_in_use(client, make_user, auth_headers):
    # Create another user with the target email
    make_user(email='taken@example.com', auth_provider='email')
    resp = client.patch('/api/v1/users/me', json={'email': 'taken@example.com'},
                        headers=auth_headers)
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'EMAIL_IN_USE'


def test_patch_phone_valid(client, auth_headers):
    resp = client.patch('/api/v1/users/me', json={'phone_number': '+4915112345678'},
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['phone_number'] == '+4915112345678'


def test_patch_phone_invalid(client, auth_headers):
    resp = client.patch('/api/v1/users/me', json={'phone_number': 'abc'},
                        headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_PHONE'


def test_patch_phone_clears_verification(client, app, auth_user, auth_headers):
    user, _ = auth_user
    # Manually mark phone verified
    with app.app_context():
        u = db.session.get(User, user.id)
        u.phone_verified = True
        db.session.commit()

    resp = client.patch('/api/v1/users/me', json={'phone_number': '+4917712345678'},
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['phone_verified'] is False


def test_patch_nearby_alerting_opt_out(client, auth_headers):
    resp = client.patch('/api/v1/users/me', json={'nearby_alerting_enabled': False},
                        headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['nearby_alerting_enabled'] is False


def test_patch_nearby_alerting_invalid_type(client, auth_headers):
    resp = client.patch('/api/v1/users/me', json={'nearby_alerting_enabled': 'yes'},
                        headers=auth_headers)
    assert resp.status_code == 400


def test_patch_no_updatable_fields(client, auth_headers):
    resp = client.patch('/api/v1/users/me', json={'unknown_field': 'value'},
                        headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'NO_UPDATABLE_FIELDS'


def test_delete_me(client, auth_user, auth_headers, app):
    user, _ = auth_user
    resp = client.delete('/api/v1/users/me', headers=auth_headers)
    assert resp.status_code == 202
    assert 'scheduled_deletion_at' in resp.get_json()

    # User is no longer accessible
    resp2 = client.get('/api/v1/users/me', headers=auth_headers)
    assert resp2.status_code == 404

    # PII is gone
    with app.app_context():
        u = db.session.get(User, user.id)
        assert u.email is None
        assert u.password_hash is None
        assert u.phone_number is None
        assert u.apns_device_token is None
        assert u.is_active is False


def test_get_reputation_empty(client, auth_headers):
    resp = client.get('/api/v1/users/me/reputation', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['score'] == 0
    assert data['level'] == 'normal'
    assert data['recent_actions'] == []


def test_get_reputation_unauthenticated(client):
    assert client.get('/api/v1/users/me/reputation').status_code == 401


# ─── GDPR Art. 15 — data export ───────────────────────────────────────────────

def test_export_requires_auth(client):
    assert client.get('/api/v1/users/me/export').status_code == 401


def test_export_structure(client, auth_user, auth_headers):
    user, _ = auth_user
    resp = client.get('/api/v1/users/me/export', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()

    assert 'exported_at' in data
    assert data['user']['id'] == user.id
    assert isinstance(data['contacts'], list)
    assert isinstance(data['alarm_history'], list)
    assert isinstance(data['reputation_history'], list)
    assert isinstance(data['safety_timer_history'], list)
    assert 'escalation_order' in data['escalation_chain']
    assert 'delay_seconds_between_stages' in data['escalation_chain']


def test_export_includes_alarm_history(client, auth_headers):
    client.post('/api/v1/alarms', json={'trigger_source': 'in_app'}, headers=auth_headers)
    resp = client.get('/api/v1/users/me/export', headers=auth_headers)
    assert resp.status_code == 200
    alarms = resp.get_json()['alarm_history']
    assert len(alarms) == 1
    assert alarms[0]['trigger_source'] == 'in_app'
    assert 'alert_type' in alarms[0]
    assert 'audience' in alarms[0]


def test_export_includes_safety_timer_history(client, auth_headers):
    # Create and immediately cancel a timer so it lands in history
    resp = client.post(
        '/api/v1/safety-timers',
        json={'duration_seconds': 600},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    timer_id = resp.get_json()['id']
    client.delete(f'/api/v1/safety-timers/{timer_id}', headers=auth_headers)

    export = client.get('/api/v1/users/me/export', headers=auth_headers).get_json()
    timers = export['safety_timer_history']
    assert len(timers) == 1
    assert timers[0]['id'] == timer_id
    assert timers[0]['status'] == 'cancelled'
