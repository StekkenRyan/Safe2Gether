"""Geohash endpoint tests — PUT /api/v1/geohash"""

from app.redis_keys import GEO_CELL, GEO_USER

_VALID_H3 = '871f1d48dffffff'   # Level-7 Munich


def test_update_geohash_online(client, auth_user, auth_headers, mock_redis):
    user, _ = auth_user
    resp = client.put('/api/v1/geohash',
                      json={'geohash': _VALID_H3, 'status': 'online'},
                      headers=auth_headers)
    assert resp.status_code == 204
    assert mock_redis.get(f'{GEO_USER}{user.id}') == _VALID_H3
    assert mock_redis.sismember(f'{GEO_CELL}{_VALID_H3}', user.id)


def test_update_geohash_invalid_h3(client, auth_headers):
    resp = client.put('/api/v1/geohash',
                      json={'geohash': 'invalid-cell', 'status': 'online'},
                      headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_GEOHASH'


def test_update_geohash_missing(client, auth_headers):
    resp = client.put('/api/v1/geohash',
                      json={'status': 'online'},
                      headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'MISSING_GEOHASH'


def test_update_geohash_invalid_status(client, auth_headers):
    resp = client.put('/api/v1/geohash',
                      json={'geohash': _VALID_H3, 'status': 'offline'},
                      headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_STATUS'


def test_expected_offline_extends_ttl(client, auth_user, auth_headers, mock_redis):
    user, _ = auth_user
    resp = client.put('/api/v1/geohash', json={
        'geohash': _VALID_H3, 'status': 'expected_offline',
        'offline_duration_seconds': 300,
    }, headers=auth_headers)
    assert resp.status_code == 204
    ttl = mock_redis.ttl(f'{GEO_USER}{user.id}')
    # Should be 600 (base) + 300 = 900 seconds ± small delta
    assert 850 <= ttl <= 910


def test_offline_duration_upper_bound(client, auth_headers):
    """Security: prevent TTL from being set to years."""
    resp = client.put('/api/v1/geohash', json={
        'geohash': _VALID_H3, 'status': 'expected_offline',
        'offline_duration_seconds': 9999999,
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_OFFLINE_DURATION'


def test_offline_duration_negative(client, auth_headers):
    resp = client.put('/api/v1/geohash', json={
        'geohash': _VALID_H3, 'status': 'expected_offline',
        'offline_duration_seconds': -1,
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_update_geohash_removes_from_old_cell(client, auth_user, auth_headers, mock_redis):
    user, _ = auth_user
    cell_a = '871f1d48dffffff'
    cell_b = '871f1d48effffff'

    client.put('/api/v1/geohash', json={'geohash': cell_a, 'status': 'online'},
               headers=auth_headers)
    assert mock_redis.sismember(f'{GEO_CELL}{cell_a}', user.id)

    client.put('/api/v1/geohash', json={'geohash': cell_b, 'status': 'online'},
               headers=auth_headers)
    assert not mock_redis.sismember(f'{GEO_CELL}{cell_a}', user.id)
    assert mock_redis.sismember(f'{GEO_CELL}{cell_b}', user.id)


def test_update_geohash_requires_auth(client):
    resp = client.put('/api/v1/geohash',
                      json={'geohash': _VALID_H3, 'status': 'online'})
    assert resp.status_code == 401
