"""Dead Man's Switch — safety-timer endpoint tests."""


def _create(client, headers, duration=600, **kwargs):
    payload = {'duration_seconds': duration, **kwargs}
    return client.post('/api/v1/safety-timers', json=payload, headers=headers)


# ─── Create ───────────────────────────────────────────────────────────────────

def test_create_timer_success(client, auth_headers):
    resp = _create(client, auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['status'] == 'active'
    assert data['duration_seconds'] == 600
    assert 'expires_at' in data
    assert 'id' in data


def test_create_timer_with_note(client, auth_headers):
    resp = _create(client, auth_headers, note='Bin auf Wanderung')
    assert resp.status_code == 201
    assert resp.get_json()['note'] == 'Bin auf Wanderung'


def test_create_timer_with_notify_community(client, auth_headers):
    resp = _create(client, auth_headers, notify_community=True)
    assert resp.status_code == 201
    assert resp.get_json()['notify_community'] is True


def test_create_timer_cancels_previous(client, auth_headers):
    first = _create(client, auth_headers).get_json()
    second = _create(client, auth_headers).get_json()
    assert second['status'] == 'active'

    # Old timer no longer returned as active
    active = client.get('/api/v1/safety-timers/active', headers=auth_headers).get_json()
    assert active['timer']['id'] == second['id']

    # First timer is cancelled in DB (verify via export)
    export = client.get('/api/v1/users/me/export', headers=auth_headers).get_json()
    statuses = {t['id']: t['status'] for t in export['safety_timer_history']}
    assert statuses[first['id']] == 'cancelled'
    assert statuses[second['id']] == 'active'


def test_create_timer_invalid_duration_too_short(client, auth_headers):
    resp = _create(client, auth_headers, duration=60)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_DURATION'


def test_create_timer_invalid_duration_too_long(client, auth_headers):
    resp = _create(client, auth_headers, duration=90_000)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_DURATION'


def test_create_timer_missing_duration(client, auth_headers):
    resp = client.post('/api/v1/safety-timers', json={}, headers=auth_headers)
    assert resp.status_code == 400


def test_create_timer_requires_auth(client):
    assert _create(client, {}).status_code == 401


# ─── Get active ───────────────────────────────────────────────────────────────

def test_get_active_timer_none(client, auth_headers):
    resp = client.get('/api/v1/safety-timers/active', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['timer'] is None


def test_get_active_timer_returns_timer(client, auth_headers):
    created = _create(client, auth_headers).get_json()
    resp = client.get('/api/v1/safety-timers/active', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['timer']['id'] == created['id']


def test_get_active_timer_requires_auth(client):
    assert client.get('/api/v1/safety-timers/active').status_code == 401


# ─── Check in ─────────────────────────────────────────────────────────────────

def test_checkin_marks_checked_in(client, auth_headers):
    timer_id = _create(client, auth_headers).get_json()['id']
    resp = client.post(f'/api/v1/safety-timers/{timer_id}/checkin', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'ok'

    # No longer active
    active = client.get('/api/v1/safety-timers/active', headers=auth_headers).get_json()
    assert active['timer'] is None


def test_checkin_nonexistent_timer(client, auth_headers):
    resp = client.post('/api/v1/safety-timers/does-not-exist/checkin', headers=auth_headers)
    assert resp.status_code == 404


def test_checkin_another_users_timer(client, make_user, auth_headers):
    other_user, other_token = make_user()
    other_headers = {'Authorization': f'Bearer {other_token}'}
    timer_id = _create(client, other_headers).get_json()['id']

    resp = client.post(f'/api/v1/safety-timers/{timer_id}/checkin', headers=auth_headers)
    assert resp.status_code == 404


def test_checkin_requires_auth(client, auth_headers):
    timer_id = _create(client, auth_headers).get_json()['id']
    assert client.post(f'/api/v1/safety-timers/{timer_id}/checkin').status_code == 401


# ─── Cancel ───────────────────────────────────────────────────────────────────

def test_cancel_timer(client, auth_headers):
    timer_id = _create(client, auth_headers).get_json()['id']
    resp = client.delete(f'/api/v1/safety-timers/{timer_id}', headers=auth_headers)
    assert resp.status_code == 204

    active = client.get('/api/v1/safety-timers/active', headers=auth_headers).get_json()
    assert active['timer'] is None


def test_cancel_nonexistent_timer(client, auth_headers):
    resp = client.delete('/api/v1/safety-timers/does-not-exist', headers=auth_headers)
    assert resp.status_code == 404


def test_cancel_another_users_timer(client, make_user, auth_headers):
    other_user, other_token = make_user()
    other_headers = {'Authorization': f'Bearer {other_token}'}
    timer_id = _create(client, other_headers).get_json()['id']

    resp = client.delete(f'/api/v1/safety-timers/{timer_id}', headers=auth_headers)
    assert resp.status_code == 404


def test_cancel_already_cancelled_timer(client, auth_headers):
    timer_id = _create(client, auth_headers).get_json()['id']
    client.delete(f'/api/v1/safety-timers/{timer_id}', headers=auth_headers)
    resp = client.delete(f'/api/v1/safety-timers/{timer_id}', headers=auth_headers)
    assert resp.status_code == 409


def test_cancel_requires_auth(client, auth_headers):
    timer_id = _create(client, auth_headers).get_json()['id']
    assert client.delete(f'/api/v1/safety-timers/{timer_id}').status_code == 401
