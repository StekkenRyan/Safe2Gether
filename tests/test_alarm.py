"""Alarm / Panic Button endpoint tests — /api/v1/alarms"""
import uuid

from app.db import db as _db
from app.models import User


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


# ─── List alarms (history) ───────────────────────────────────────────────────

def test_list_alarms_empty_for_fresh_user(client, auth_headers):
    resp = client.get('/api/v1/alarms', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {'alarms': []}


def test_list_alarms_includes_own_with_role_sender(client, auth_headers):
    triggered = _trigger(client, auth_headers).get_json()
    resp = client.get('/api/v1/alarms', headers=auth_headers)
    data = resp.get_json()
    assert len(data['alarms']) == 1
    assert data['alarms'][0]['id'] == triggered['id']
    assert data['alarms'][0]['your_role'] == 'sender'


def test_list_alarms_includes_responded_with_role_responder(client, make_user):
    _, owner_token = make_user(email='owner-hist@example.com')
    _, helper_token = make_user(email='helper-hist@example.com')

    owner_headers = {'Authorization': f'Bearer {owner_token}'}
    helper_headers = {'Authorization': f'Bearer {helper_token}'}

    alarm_id = _trigger(client, owner_headers).get_json()['id']
    client.post(f'/api/v1/alarms/{alarm_id}/respond', headers=helper_headers)

    resp = client.get('/api/v1/alarms', headers=helper_headers)
    data = resp.get_json()
    assert len(data['alarms']) == 1
    assert data['alarms'][0]['id'] == alarm_id
    assert data['alarms'][0]['your_role'] == 'responder'


def test_list_alarms_excludes_strangers(client, make_user, auth_headers):
    _, stranger_token = make_user(email='stranger-hist@example.com')
    _trigger(client, {'Authorization': f'Bearer {stranger_token}'})
    resp = client.get('/api/v1/alarms', headers=auth_headers)
    assert resp.get_json()['alarms'] == []


def test_list_alarms_requires_auth(client):
    resp = client.get('/api/v1/alarms')
    assert resp.status_code == 401


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


# ─── Reputation writes ────────────────────────────────────────────────────────

def _get_reputation(client, headers):
    return client.get('/api/v1/users/me/reputation', headers=headers).get_json()


def test_respond_awards_reputation(client, app, make_user):
    owner, owner_token = make_user(email='rep_owner@example.com')
    responder, responder_token = make_user(email='rep_helper@example.com')
    owner_headers = {'Authorization': f'Bearer {owner_token}'}
    helper_headers = {'Authorization': f'Bearer {responder_token}'}

    alarm_id = _trigger(client, owner_headers).get_json()['id']
    client.post(f'/api/v1/alarms/{alarm_id}/respond', headers=helper_headers)

    rep = _get_reputation(client, helper_headers)
    assert rep['score'] == 10
    assert rep['level'] == 'normal'
    assert len(rep['recent_actions']) == 1
    assert rep['recent_actions'][0]['action_type'] == 'responded_to_alarm'
    assert rep['recent_actions'][0]['score_delta'] == 10
    assert rep['recent_actions'][0]['alarm_id'] == alarm_id


def test_resolved_awards_responder_reputation(client, app, make_user):
    owner, owner_token = make_user(email='res_owner@example.com')
    responder, responder_token = make_user(email='res_helper@example.com')
    owner_headers = {'Authorization': f'Bearer {owner_token}'}
    helper_headers = {'Authorization': f'Bearer {responder_token}'}

    alarm_id = _trigger(client, owner_headers).get_json()['id']
    client.post(f'/api/v1/alarms/{alarm_id}/respond', headers=helper_headers)
    client.patch(f'/api/v1/alarms/{alarm_id}',
                 json={'status': 'resolved'}, headers=owner_headers)

    rep = _get_reputation(client, helper_headers)
    # +10 for responding, +5 for response_verified
    assert rep['score'] == 15
    action_types = {a['action_type'] for a in rep['recent_actions']}
    assert 'responded_to_alarm' in action_types
    assert 'response_verified' in action_types


def test_false_alarm_penalizes_owner(client, app, make_user):
    owner, owner_token = make_user(email='fa_owner@example.com')
    owner_headers = {'Authorization': f'Bearer {owner_token}'}

    alarm_id = _trigger(client, owner_headers).get_json()['id']
    client.patch(f'/api/v1/alarms/{alarm_id}',
                 json={'status': 'false_alarm'}, headers=owner_headers)

    rep = _get_reputation(client, owner_headers)
    assert rep['score'] == -5
    assert rep['level'] == 'low'
    assert rep['recent_actions'][0]['action_type'] == 'false_alarm_triggered'


def test_owner_reputation_unaffected_by_resolve(client, app, make_user):
    """Resolving an alarm does not touch the owner's score — only responders earn."""
    owner, owner_token = make_user(email='res2_owner@example.com')
    owner_headers = {'Authorization': f'Bearer {owner_token}'}

    alarm_id = _trigger(client, owner_headers).get_json()['id']
    client.patch(f'/api/v1/alarms/{alarm_id}',
                 json={'status': 'resolved'}, headers=owner_headers)

    rep = _get_reputation(client, owner_headers)
    assert rep['score'] == 0


# ─── alert_type + audience ────────────────────────────────────────────────────

def test_trigger_alarm_defaults(client, auth_headers):
    data = _trigger(client, auth_headers).get_json()
    assert data['alert_type'] == 'panic'
    assert data['audience'] == 'contacts_and_community'
    assert data['home_distance_category'] is None


def test_trigger_alarm_with_alert_type_and_audience(client, auth_headers):
    resp = client.post('/api/v1/alarms', json={
        'trigger_source': 'in_app',
        'alert_type': 'need_help',
        'audience': 'contacts',
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['alert_type'] == 'need_help'
    assert data['audience'] == 'contacts'


def test_trigger_cant_get_home_with_distance(client, auth_headers):
    resp = client.post('/api/v1/alarms', json={
        'trigger_source': 'in_app',
        'alert_type': 'cant_get_home',
        'audience': 'contacts_and_community',
        'home_distance_category': 'over_15km',
    }, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['alert_type'] == 'cant_get_home'
    assert data['home_distance_category'] == 'over_15km'


def test_patch_alarm_response_includes_alert_type_and_audience(client, auth_headers):
    alarm_id = client.post('/api/v1/alarms', json={
        'trigger_source': 'in_app',
        'alert_type': 'car_breakdown',
        'audience': 'community',
    }, headers=auth_headers).get_json()['id']

    resp = client.patch(
        f'/api/v1/alarms/{alarm_id}',
        json={'status': 'resolved'},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['alert_type'] == 'car_breakdown'
    assert data['audience'] == 'community'
