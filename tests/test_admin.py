"""Tests for the admin dashboard blueprint."""
import pytest

from app.db import db as _db
from app.models import User


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv('ADMIN_USERNAME', 'testadmin')
    monkeypatch.setenv('ADMIN_PASSWORD', 'testpass')


@pytest.fixture
def logged_in(client, admin_env):
    """Client with an active admin session."""
    client.post('/admin/login', data={'username': 'testadmin', 'password': 'testpass'})
    return client


# ── Login / auth ──────────────────────────────────────────────────────────────

def test_admin_dashboard_unauthenticated_redirects(client):
    resp = client.get('/admin/')
    assert resp.status_code == 302
    assert '/admin/login' in resp.headers['Location']


def test_admin_login_page_renders(client):
    resp = client.get('/admin/login')
    assert resp.status_code == 200
    assert b'Safe2Gether' in resp.data


def test_admin_login_wrong_credentials(client, admin_env):
    resp = client.post('/admin/login', data={'username': 'testadmin', 'password': 'wrong'})
    assert resp.status_code == 401
    assert b'Ung' in resp.data  # 'Ungültige Anmeldedaten'


def test_admin_login_and_dashboard(logged_in):
    resp = logged_in.get('/admin/', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Dashboard' in resp.data


def test_admin_logout_clears_session(logged_in):
    logged_in.get('/admin/logout')
    resp = logged_in.get('/admin/')
    assert resp.status_code == 302


# ── User list ─────────────────────────────────────────────────────────────────

def test_user_list_requires_auth(client):
    resp = client.get('/admin/users')
    assert resp.status_code == 302


def test_user_list_renders(logged_in, make_user):
    make_user(email='alice@example.com')
    resp = logged_in.get('/admin/users')
    assert resp.status_code == 200
    assert b'alice@example.com' in resp.data


def test_user_list_filter_by_level(logged_in, make_user):
    make_user(email='low@example.com')
    resp = logged_in.get('/admin/users?level=very_low')
    assert resp.status_code == 200


def test_geo_api_returns_structure(logged_in):
    resp = logged_in.get('/admin/api/geo')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'users' in data and 'alarms' in data
    assert isinstance(data['users'], list)
    assert isinstance(data['alarms'], list)


# ── User detail ───────────────────────────────────────────────────────────────

def test_user_detail_renders(logged_in, make_user):
    user, _ = make_user(email='detail@example.com')
    resp = logged_in.get(f'/admin/users/{user.id}')
    assert resp.status_code == 200
    assert b'detail@example.com' in resp.data


def test_user_detail_unknown_id_redirects(logged_in):
    resp = logged_in.get('/admin/users/00000000-0000-0000-0000-000000000000')
    assert resp.status_code == 302


# ── User actions ──────────────────────────────────────────────────────────────

def test_user_deactivate(logged_in, make_user):
    user, _ = make_user()
    resp = logged_in.post(f'/admin/users/{user.id}/deactivate', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Deaktiviert' in resp.data
    _db.session.expire_all()
    updated = _db.session.get(User, user.id)
    assert updated.is_active is False


def test_user_reactivate(logged_in, make_user):
    user, _ = make_user()
    logged_in.post(f'/admin/users/{user.id}/deactivate')
    resp = logged_in.post(f'/admin/users/{user.id}/reactivate', follow_redirects=True)
    assert resp.status_code == 200
    assert b'Aktiv' in resp.data
    _db.session.expire_all()
    updated = _db.session.get(User, user.id)
    assert updated.is_active is True


def test_user_reset_score(logged_in, make_user, app):
    user, _ = make_user()
    with app.app_context():
        u = _db.session.get(User, user.id)
        u.reputation_score = -50
        u.reputation_level = 'very_low'
        _db.session.commit()

    resp = logged_in.post(f'/admin/users/{user.id}/reset-score', follow_redirects=True)
    assert resp.status_code == 200
    _db.session.expire_all()
    updated = _db.session.get(User, user.id)
    assert updated.reputation_score == 0
    assert updated.reputation_level == 'normal'
