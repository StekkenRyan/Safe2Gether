"""Emergency contacts endpoint tests — /api/v1/contacts"""
import uuid


def _create(client, headers, **kwargs):
    payload = {
        'contact_type': 'phone',
        'contact_value': '+4915112345678',
        'name': 'Test Person',
        **kwargs,
    }
    return client.post('/api/v1/contacts', json=payload, headers=headers)


def test_list_contacts_empty(client, auth_headers):
    resp = client.get('/api/v1/contacts', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_create_phone_contact(client, auth_headers):
    resp = _create(client, auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['contact_type'] == 'phone'
    assert data['contact_value'] == '+4915112345678'
    assert data['order_in_escalation'] == 1


def test_create_email_contact(client, auth_headers):
    resp = _create(client, auth_headers,
                   contact_type='email', contact_value='emergency@example.com')
    assert resp.status_code == 201
    assert resp.get_json()['contact_type'] == 'email'


def test_create_in_app_contact(client, auth_headers):
    resp = _create(client, auth_headers,
                   contact_type='in_app', contact_value=str(uuid.uuid4()))
    assert resp.status_code == 201


def test_create_contact_invalid_type(client, auth_headers):
    resp = _create(client, auth_headers, contact_type='telegram')
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'MISSING_FIELDS'


def test_create_phone_invalid_format(client, auth_headers):
    resp = _create(client, auth_headers, contact_value='not-a-phone')
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_CONTACT_VALUE'


def test_create_email_invalid_format(client, auth_headers):
    resp = _create(client, auth_headers,
                   contact_type='email', contact_value='notanemail')
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_CONTACT_VALUE'


def test_create_in_app_invalid_uuid(client, auth_headers):
    resp = _create(client, auth_headers,
                   contact_type='in_app', contact_value='not-a-uuid')
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_CONTACT_VALUE'


def test_create_order_auto_increments(client, auth_headers):
    _create(client, auth_headers, name='First')
    resp2 = _create(client, auth_headers, name='Second')
    assert resp2.get_json()['order_in_escalation'] == 2


def test_create_order_bounds(client, auth_headers):
    resp = _create(client, auth_headers, order_in_escalation=0)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_ORDER'

    resp2 = _create(client, auth_headers, order_in_escalation=101)
    assert resp2.status_code == 400


def test_update_contact(client, auth_headers):
    contact_id = _create(client, auth_headers).get_json()['id']
    resp = client.patch(f'/api/v1/contacts/{contact_id}',
                        json={'name': 'Updated Name'}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['name'] == 'Updated Name'


def test_update_contact_invalid_value(client, auth_headers):
    contact_id = _create(client, auth_headers).get_json()['id']
    resp = client.patch(f'/api/v1/contacts/{contact_id}',
                        json={'contact_value': 'bad-phone'}, headers=auth_headers)
    assert resp.status_code == 400


def test_update_order_bounds(client, auth_headers):
    contact_id = _create(client, auth_headers).get_json()['id']
    resp = client.patch(f'/api/v1/contacts/{contact_id}',
                        json={'order_in_escalation': -5}, headers=auth_headers)
    assert resp.status_code == 400


def test_delete_contact(client, auth_headers):
    contact_id = _create(client, auth_headers).get_json()['id']
    resp = client.delete(f'/api/v1/contacts/{contact_id}', headers=auth_headers)
    assert resp.status_code == 204
    assert client.get('/api/v1/contacts', headers=auth_headers).get_json() == []


def test_cannot_access_other_users_contact(client, make_user, auth_headers):
    _, token_b = make_user(email='b@example.com')
    contact_id = _create(client, auth_headers).get_json()['id']

    resp = client.delete(f'/api/v1/contacts/{contact_id}',
                         headers={'Authorization': f'Bearer {token_b}'})
    assert resp.status_code == 404


def test_contacts_requires_auth(client):
    assert client.get('/api/v1/contacts').status_code == 401
    assert client.post('/api/v1/contacts', json={}).status_code == 401
