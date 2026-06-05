"""Debug endpoint tests — /api/v1/debug/*"""
import uuid

from app.db import db as _db
from app.debug import _TEST_USER_ID
from app.models import Alarm


# ─── inject-nearby-alert ─────────────────────────────────────────────────────

def test_inject_nearby_alert_returns_201_with_expected_shape(client, auth_headers):
    resp = client.post('/api/v1/debug/inject-nearby-alert', headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    uuid.UUID(data['alarm_id'])                          # valid UUID
    assert data['alert_type'] == 'panic'
    assert isinstance(data['bearing_degrees'], (int, float))
    assert isinstance(data['distance_meters'], (int, float))
    assert 'triggered_at' in data


def test_inject_nearby_alert_requires_auth(client):
    resp = client.post('/api/v1/debug/inject-nearby-alert')
    assert resp.status_code == 401


def test_inject_nearby_alert_creates_active_alarm_owned_by_test_user(client, auth_headers):
    resp = client.post('/api/v1/debug/inject-nearby-alert', headers=auth_headers)
    alarm = _db.session.get(Alarm, resp.get_json()['alarm_id'])
    assert alarm is not None
    assert alarm.user_id == _TEST_USER_ID
    assert alarm.status == 'active'
    assert alarm.alert_type == 'panic'
    assert alarm.trigger_source == 'in_app'


# ─── inject-contact-alarm ────────────────────────────────────────────────────

def test_inject_contact_alarm_returns_201_with_alarm_id_only(client, auth_headers):
    resp = client.post('/api/v1/debug/inject-contact-alarm', headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert list(data.keys()) == ['alarm_id']
    uuid.UUID(data['alarm_id'])                          # valid UUID


def test_inject_contact_alarm_requires_auth(client):
    resp = client.post('/api/v1/debug/inject-contact-alarm')
    assert resp.status_code == 401


def test_inject_contact_alarm_creates_active_alarm_owned_by_test_user(client, auth_headers):
    resp = client.post('/api/v1/debug/inject-contact-alarm', headers=auth_headers)
    alarm = _db.session.get(Alarm, resp.get_json()['alarm_id'])
    assert alarm is not None
    assert alarm.user_id == _TEST_USER_ID
    assert alarm.status == 'active'
