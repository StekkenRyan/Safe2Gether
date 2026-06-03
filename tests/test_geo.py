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
    assert resp.get_json()['code'] == 'MISSING_LOCATION'


# ─── lat/lng input (server-side H3 conversion) ────────────────────────────────

def test_update_geohash_accepts_latlng(client, auth_user, auth_headers, mock_redis):
    """Server converts lat/lng to H3 at res 7 and stores only the cell."""
    user, _ = auth_user
    # Munich Marienplatz
    resp = client.put('/api/v1/geohash', json={
        'latitude': 48.1374, 'longitude': 11.5755, 'status': 'online',
    }, headers=auth_headers)
    assert resp.status_code == 204

    stored = mock_redis.get(f'{GEO_USER}{user.id}')
    assert stored is not None
    # Cell must be a valid H3 index — exact value tied to h3-py's res-7 grid
    import h3
    assert h3.is_valid_cell(stored)
    assert h3.get_resolution(stored) == 7


def test_latlng_out_of_range_lat(client, auth_headers):
    resp = client.put('/api/v1/geohash', json={
        'latitude': 95.0, 'longitude': 11.5, 'status': 'online',
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_COORDINATES'


def test_latlng_out_of_range_lng(client, auth_headers):
    resp = client.put('/api/v1/geohash', json={
        'latitude': 48.0, 'longitude': 200.0, 'status': 'online',
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_COORDINATES'


def test_latlng_non_numeric(client, auth_headers):
    resp = client.put('/api/v1/geohash', json={
        'latitude': 'forty-eight', 'longitude': 11.5, 'status': 'online',
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_COORDINATES'


def test_latlng_rejects_booleans(client, auth_headers):
    """JSON booleans must not be silently treated as 0/1."""
    resp = client.put('/api/v1/geohash', json={
        'latitude': True, 'longitude': False, 'status': 'online',
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_COORDINATES'


def test_explicit_geohash_takes_priority(client, auth_user, auth_headers, mock_redis):
    """When both geohash and lat/lng are sent, geohash wins (client has authority)."""
    user, _ = auth_user
    resp = client.put('/api/v1/geohash', json={
        'geohash': _VALID_H3,
        'latitude': 48.1374, 'longitude': 11.5755,
        'status': 'online',
    }, headers=auth_headers)
    assert resp.status_code == 204
    assert mock_redis.get(f'{GEO_USER}{user.id}') == _VALID_H3


def test_latlng_with_expected_offline(client, auth_user, auth_headers, mock_redis):
    user, _ = auth_user
    resp = client.put('/api/v1/geohash', json={
        'latitude': 48.1374, 'longitude': 11.5755,
        'status': 'expected_offline',
        'offline_duration_seconds': 120,
    }, headers=auth_headers)
    assert resp.status_code == 204
    ttl = mock_redis.ttl(f'{GEO_USER}{user.id}')
    assert 700 <= ttl <= 730


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
