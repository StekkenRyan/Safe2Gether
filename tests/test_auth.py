"""Auth endpoint tests — POST /api/v1/auth/*"""



# ─── Email sign-in / register ─────────────────────────────────────────────────

def test_email_signup_creates_account(client):
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'email': 'new@example.com', 'password': 'password123',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['access_token']
    assert data['refresh_token']
    assert data['user']['email'] == 'new@example.com'
    assert data['user']['auth_provider'] == 'email'


def test_email_signin_wrong_password(client):
    # Register first
    client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'email': 'existing@example.com', 'password': 'correctpass',
    })
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'email': 'existing@example.com', 'password': 'wrongpass',
    })
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 'INVALID_CREDENTIALS'


def test_email_signin_existing_account(client):
    payload = {'provider': 'email', 'email': 'user@example.com', 'password': 'password123'}
    client.post('/api/v1/auth/signin', json=payload)
    resp = client.post('/api/v1/auth/signin', json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['user']['email'] == 'user@example.com'


def test_email_signup_password_too_short(client):
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'email': 'short@example.com', 'password': 'abc',
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'PASSWORD_TOO_SHORT'


def test_email_signup_invalid_email_format(client):
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'email': 'notanemail', 'password': 'password123',
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_EMAIL'


def test_email_signup_missing_fields(client):
    resp = client.post('/api/v1/auth/signin', json={'provider': 'email'})
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'MISSING_CREDENTIALS'


# ─── action: register / signin ────────────────────────────────────────────────

def test_register_action_creates_account(client):
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'action': 'register',
        'email': 'fresh@example.com', 'password': 'password123',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['access_token']
    assert data['user']['email'] == 'fresh@example.com'


def test_register_action_conflicts_when_account_exists(client):
    payload = {'provider': 'email', 'action': 'register',
               'email': 'dupe@example.com', 'password': 'password123'}
    assert client.post('/api/v1/auth/signin', json=payload).status_code == 200

    resp = client.post('/api/v1/auth/signin', json=payload)
    assert resp.status_code == 409
    assert resp.get_json()['code'] == 'EMAIL_ALREADY_REGISTERED'


def test_signin_action_unknown_account_returns_401(client):
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'action': 'signin',
        'email': 'ghost@example.com', 'password': 'password123',
    })
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 'INVALID_CREDENTIALS'


def test_signin_action_existing_correct_password(client):
    client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'action': 'register',
        'email': 'member@example.com', 'password': 'correcthorse',
    })
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'action': 'signin',
        'email': 'member@example.com', 'password': 'correcthorse',
    })
    assert resp.status_code == 200
    assert resp.get_json()['user']['email'] == 'member@example.com'


def test_signin_action_existing_wrong_password(client):
    client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'action': 'register',
        'email': 'member2@example.com', 'password': 'correcthorse',
    })
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'action': 'signin',
        'email': 'member2@example.com', 'password': 'wrongpass1',
    })
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 'INVALID_CREDENTIALS'


def test_invalid_action_rejected(client):
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'email', 'action': 'delete',
        'email': 'x@example.com', 'password': 'password123',
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_ACTION'


# ─── Provider validation ──────────────────────────────────────────────────────

def test_invalid_provider_rejected(client):
    resp = client.post('/api/v1/auth/signin', json={
        'provider': 'facebook', 'id_token': 'whatever',
    })
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_PROVIDER'


def test_missing_id_token_for_apple(client):
    resp = client.post('/api/v1/auth/signin', json={'provider': 'apple'})
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'MISSING_ID_TOKEN'


# ─── Token refresh ────────────────────────────────────────────────────────────

def test_refresh_valid_token(client, auth_user):
    user, _ = auth_user
    from app.token import create_refresh_token
    refresh_token = create_refresh_token(user.id)

    resp = client.post('/api/v1/auth/refresh', json={'refresh_token': refresh_token})
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'access_token' in data
    assert data['expires_in'] > 0


def test_refresh_invalid_token(client):
    resp = client.post('/api/v1/auth/refresh', json={'refresh_token': 'garbage.token.here'})
    assert resp.status_code == 401
    assert resp.get_json()['code'] == 'INVALID_REFRESH_TOKEN'


def test_refresh_rotates_token(client, auth_user, mock_redis):
    """A5: each refresh returns a NEW refresh token and the old one stops working."""
    user, _ = auth_user
    from app.token import create_refresh_token
    old = create_refresh_token(user.id)

    resp = client.post('/api/v1/auth/refresh', json={'refresh_token': old})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['access_token']
    assert data['refresh_token'] and data['refresh_token'] != old

    # The rotated-out token is no longer usable.
    reuse = client.post('/api/v1/auth/refresh', json={'refresh_token': old})
    assert reuse.status_code == 401


def test_refresh_reuse_revokes_whole_family(client, auth_user, mock_redis):
    """A5: replaying a rotated-out refresh token revokes every session for the
    user (reuse detection) — including the freshly issued token."""
    user, _ = auth_user
    from app.token import create_refresh_token, decode_refresh_token
    old = create_refresh_token(user.id)

    new = client.post(
        '/api/v1/auth/refresh', json={'refresh_token': old}
    ).get_json()['refresh_token']
    assert decode_refresh_token(new) == user.id  # valid right after rotation

    # Replay the old token → reuse detected → nuke family.
    client.post('/api/v1/auth/refresh', json={'refresh_token': old})

    # The new token is now also dead.
    assert decode_refresh_token(new) is None


def test_refresh_missing_token(client):
    resp = client.post('/api/v1/auth/refresh', json={})
    assert resp.status_code == 401


# ─── Logout ───────────────────────────────────────────────────────────────────

def test_logout_revokes_refresh_token(client, auth_user, mock_redis):
    user, access_token = auth_user
    from app.token import create_refresh_token
    refresh_token = create_refresh_token(user.id)

    resp = client.post(
        '/api/v1/auth/logout',
        json={'refresh_token': refresh_token},
        headers={'Authorization': f'Bearer {access_token}'},
    )
    assert resp.status_code == 204

    # Refresh token should now be invalid
    resp2 = client.post('/api/v1/auth/refresh', json={'refresh_token': refresh_token})
    assert resp2.status_code == 401


def test_logout_without_refresh_token_still_succeeds(client, auth_headers):
    resp = client.post('/api/v1/auth/logout', json={}, headers=auth_headers)
    assert resp.status_code == 204


# ─── Device token ─────────────────────────────────────────────────────────────

def test_update_device_token_valid(client, auth_headers):
    resp = client.put('/api/v1/auth/device-token', json={
        'device_token': 'a' * 64,
        'environment': 'sandbox',
    }, headers=auth_headers)
    assert resp.status_code == 204


def test_update_device_token_invalid_format(client, auth_headers):
    resp = client.put('/api/v1/auth/device-token', json={
        'device_token': 'tooshort',
        'environment': 'sandbox',
    }, headers=auth_headers)
    assert resp.status_code == 400
    assert resp.get_json()['code'] == 'INVALID_DEVICE_TOKEN'


def test_update_device_token_invalid_environment(client, auth_headers):
    resp = client.put('/api/v1/auth/device-token', json={
        'device_token': 'b' * 64,
        'environment': 'invalid',
    }, headers=auth_headers)
    assert resp.status_code == 400


def test_update_device_token_requires_auth(client):
    resp = client.put('/api/v1/auth/device-token', json={
        'device_token': 'c' * 64, 'environment': 'sandbox',
    })
    assert resp.status_code == 401
