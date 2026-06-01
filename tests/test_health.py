def test_health_returns_200(client):
    response = client.get('/api/v1/health')
    assert response.status_code == 200


def test_health_response_structure(client):
    data = client.get('/api/v1/health').get_json()
    assert 'status' in data
    assert 'version' in data
    assert 'db_status' in data
    assert 'redis_status' in data


def test_health_version(client):
    data = client.get('/api/v1/health').get_json()
    assert data['version'] == '1.0.0'
