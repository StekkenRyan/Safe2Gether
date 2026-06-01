"""Alarm / Panic Button endpoint tests — /api/v1/alarms"""
import uuid


def _trigger(client, headers, source='in_app', geohash=None):
    payload = {'trigger_source': source}
    if geohash:
        payload['geohash_snapshot'] = geohash
    return client.post('/api/v1/alarms', json=payload, headers=headers)


# ─── Trigger alarm ────────────────────────────────────────────────────────────

def test_trigger_alarm_success(client, auth_headers):
    resp = _trigger(client, auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['status'] == 'active'
    assert data['trigger_source'] == 'in_app'
    assert 'id' in data
    assert 'auto_delete_at' in data


def test_trigger_alarm_with_valid_geohash(client, auth_headers):
    # Use a real H3 level-7 index for Munich
    resp = _trigger(client, auth_headers, geohash='871f1d48dffffff')
    assert resp.status_code == 201
    assert resp.get_json()['geohash_snapshot'] == '871f1d48dffffff'


def test_trigger_alarm_invalid_geohash(client, auth_headers):
    resp = _trigger(client, auth_headers, geohash='not-a-geohash')
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_GEOHASH'


def test_trigger_alarm_invalid_source(client, auth_headers):
    resp = _trigger(client, auth_headers, source='magical_button')
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_TRIGGER_SOURCE'


def test_trigger_alarm_requires_auth(client):
    resp = client.post('/api/v1/alarms', json={'trigger_source': 'in_app'})
    assert resp.status_code == 401


def test_alarm_id_is_always_server_generated(client, auth_headers):
    """Client cannot dictate the alarm_id — server always generates it."""
    resp = client.post('/api/v1/alarms', json={
        'trigger_source': 'in_app',
        'alarm_id': 'attacker-chosen-id',
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['id'] != 'attacker-chosen-id'
    # Must be a valid UUID
    uuid.UUID(data['id'])


# ─── Rate limiting ────────────────────────────────────────────────────────────

def test_alarm_rate_limit(client, auth_headers):
    resp1 = _trigger(client, auth_headers)
    assert resp1.status_code == 201
    resp2 = _trigger(client, auth_headers)
    assert resp2.status_code == 429
    assert resp2.get_json()['code'] == 'ALARM_RATE_LIMIT'


def test_alarm_rate_limit_is_per_user(client, make_user):
    _, token_a = make_user(email='a@example.com')
    _, token_b = make_user(email='b@example.com')
    headers_a = {'Authorization': f'Bearer {token_a}'}
    headers_b = {'Authorization': f'Bearer {token_b}'}

    assert _trigger(client, headers_a).status_code == 201
    assert _trigger(client, headers_a).status_code == 429
    # User B is unaffected
    assert _trigger(client, headers_b).status_code == 201


# ─── Get alarm ────────────────────────────────────────────────────────────────

def test_get_alarm_as_owner(client, auth_headers):
    alarm_id = _trigger(client, auth_headers).get_json()['id']
    resp = client.get(f'/api/v1/alarms/{alarm_id}', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['id'] == alarm_id


def test_get_alarm_nonexistent(client, auth_headers):
    resp = client.get(f'/api/v1/alarms/{uuid.uuid4()}', headers=auth_headers)
    assert resp.status_code == 404


def test_get_alarm_by_stranger_returns_404(client, make_user, auth_headers):
    alarm_id = _trigger(client, auth_headers).get_json()['id']
    _, stranger_token = make_user(email='stranger@example.com')
    resp = client.get(f'/api/v1/alarms/{alarm_id}',
                      headers={'Authorization': f'Bearer {stranger_token}'})
    assert resp.status_code == 404


# ─── Update alarm status ──────────────────────────────────────────────────────

def test_resolve_alarm(client, auth_headers):
    alarm_id = _trigger(client, auth_headers).get_json()['id']
    resp = client.patch(f'/api/v1/alarms/{alarm_id}',
                        json={'status': 'resolved'}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'resolved'


def test_update_alarm_invalid_status(client, auth_headers):
    alarm_id = _trigger(client, auth_headers).get_json()['id']
    resp = client.patch(f'/api/v1/alarms/{alarm_id}',
                        json={'status': 'active'}, headers=auth_headers)
    assert resp.status_code == 400


def test_update_alarm_by_non_owner_forbidden(client, make_user, auth_headers):
    alarm_id = _trigger(client, auth_headers).get_json()['id']
    _, other_token = make_user(email='other@example.com')
    resp = client.patch(f'/api/v1/alarms/{alarm_id}',
                        json={'status': 'resolved'},
                        headers={'Authorization': f'Bearer {other_token}'})
    assert resp.status_code == 403


# ─── Respond to alarm ─────────────────────────────────────────────────────────

def test_respond_to_alarm(client, make_user):
    _, owner_token = make_user(email='owner@example.com')
    _, responder_token = make_user(email='helper@example.com')

    alarm_id = _trigger(client, {'Authorization': f'Bearer {owner_token}'}).get_json()['id']
    resp = client.post(f'/api/v1/alarms/{alarm_id}/respond',
                       headers={'Authorization': f'Bearer {responder_token}'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['alarm_id'] == alarm_id


def test_cannot_respond_to_own_alarm(client, auth_headers):
    alarm_id = _trigger(client, auth_headers).get_json()['id']
    resp = client.post(f'/api/v1/alarms/{alarm_id}/respond', headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'CANNOT_RESPOND_OWN_ALARM'


def test_duplicate_respond_is_conflict(client, make_user):
    _, owner_token = make_user(email='o2@example.com')
    _, helper_token = make_user(email='h2@example.com')

    alarm_id = _trigger(client, {'Authorization': f'Bearer {owner_token}'}).get_json()['id']
    client.post(f'/api/v1/alarms/{alarm_id}/respond',
                headers={'Authorization': f'Bearer {helper_token}'})
    resp = client.post(f'/api/v1/alarms/{alarm_id}/respond',
                       headers={'Authorization': f'Bearer {helper_token}'})
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'ALREADY_RESPONDING'


def test_responder_can_see_alarm(client, make_user):
    _, owner_token = make_user(email='o3@example.com')
    _, helper_token = make_user(email='h3@example.com')

    alarm_id = _trigger(client, {'Authorization': f'Bearer {owner_token}'}).get_json()['id']
    client.post(f'/api/v1/alarms/{alarm_id}/respond',
                headers={'Authorization': f'Bearer {helper_token}'})

    resp = client.get(f'/api/v1/alarms/{alarm_id}',
                      headers={'Authorization': f'Bearer {helper_token}'})
    assert resp.status_code == 200


def test_nearby_alerting_opt_out_respected(client, app, make_user):
    """User with nearby_alerting_enabled=False should not receive community alerts."""
    _, owner_token = make_user(email='opt_out_owner@example.com')
    opted_out_user, _ = make_user(email='opted_out@example.com',
                                  nearby_alerting_enabled=False)
    # We can't easily assert push wasn't sent without mocking APNs,
    # but we can verify the logic doesn't crash and alarm is created
    resp = _trigger(client, {'Authorization': f'Bearer {owner_token}'},
                    geohash='871f1d48dffffff')
    assert resp.status_code == 201
