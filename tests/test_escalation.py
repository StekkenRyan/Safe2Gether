"""Escalation chain endpoint tests — /api/v1/escalation"""


def test_get_returns_default_chain(client, auth_headers):
    resp = client.get('/api/v1/escalation', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['escalation_order'] == ['device_local', 'contacts', 'community']
    assert data['delay_seconds_between_stages'] == 30


def test_patch_reorders_chain(client, auth_headers):
    resp = client.patch(
        '/api/v1/escalation',
        json={'escalation_order': ['device_local', 'community', 'contacts']},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.get_json()['escalation_order'] == ['device_local', 'community', 'contacts']


def test_patch_updates_delay(client, auth_headers):
    resp = client.patch(
        '/api/v1/escalation',
        json={
            'escalation_order': ['device_local', 'contacts+community'],
            'delay_seconds_between_stages': 0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['escalation_order'] == ['device_local', 'contacts+community']
    assert data['delay_seconds_between_stages'] == 0


def test_patch_persists_across_requests(client, auth_headers):
    client.patch(
        '/api/v1/escalation',
        json={'escalation_order': ['device_local', 'community']},
        headers=auth_headers,
    )
    resp = client.get('/api/v1/escalation', headers=auth_headers)
    assert resp.get_json()['escalation_order'] == ['device_local', 'community']


def test_patch_rejects_empty_order(client, auth_headers):
    resp = client.patch(
        '/api/v1/escalation',
        json={'escalation_order': []},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_ESCALATION_ORDER'


def test_patch_rejects_unknown_stage(client, auth_headers):
    resp = client.patch(
        '/api/v1/escalation',
        json={'escalation_order': ['device_local', 'magic_button']},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_ESCALATION_STAGE'


def test_patch_rejects_duplicates(client, auth_headers):
    resp = client.patch(
        '/api/v1/escalation',
        json={'escalation_order': ['contacts', 'contacts']},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'DUPLICATE_ESCALATION_STAGE'


def test_patch_rejects_bad_delay(client, auth_headers):
    resp = client.patch(
        '/api/v1/escalation',
        json={
            'escalation_order': ['device_local', 'contacts'],
            'delay_seconds_between_stages': -5,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_DELAY'


def test_get_requires_auth(client):
    resp = client.get('/api/v1/escalation')
    assert resp.status_code == 401


def test_patch_requires_auth(client):
    resp = client.patch(
        '/api/v1/escalation',
        json={'escalation_order': ['device_local']},
    )
    assert resp.status_code == 401
