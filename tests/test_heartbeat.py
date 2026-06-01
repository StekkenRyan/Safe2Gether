"""Heartbeat endpoint tests — POST /api/v1/heartbeat"""
from app.redis_keys import HB


def test_heartbeat_alive(client, auth_user, auth_headers, mock_redis):
    user, _ = auth_user
    resp = client.post('/api/v1/heartbeat', json={'status': 'alive'}, headers=auth_headers)
    assert resp.status_code == 204
    assert mock_redis.get(f'{HB}{user.id}') == 'alive'


def test_heartbeat_expected_offline(client, auth_user, auth_headers, mock_redis):
    user, _ = auth_user
    resp = client.post('/api/v1/heartbeat', json={
        'status': 'expected_offline', 'offline_duration_seconds': 600,
    }, headers=auth_headers)
    assert resp.status_code == 204
    ttl = mock_redis.ttl(f'{HB}{user.id}')
    assert 1150 <= ttl <= 1210  # base 600 + ext 600 ± delta


def test_heartbeat_invalid_status(client, auth_headers):
    resp = client.post('/api/v1/heartbeat', json={'status': 'dead'}, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_STATUS'


def test_heartbeat_offline_duration_upper_bound(client, auth_headers):
    resp = client.post('/api/v1/heartbeat', json={
        'status': 'expected_offline', 'offline_duration_seconds': 9999999,
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_OFFLINE_DURATION'


def test_heartbeat_offline_duration_negative(client, auth_headers):
    resp = client.post('/api/v1/heartbeat', json={
        'status': 'expected_offline', 'offline_duration_seconds': -10,
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_heartbeat_requires_auth(client):
    resp = client.post('/api/v1/heartbeat', json={'status': 'alive'})
    assert resp.status_code == 401
