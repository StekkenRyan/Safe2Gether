"""Anonymous error-reporting endpoint tests — POST /api/v1/events/error.

The endpoint takes no auth and stores no PII. Rate limiting is off by default
under TESTING, so the inserts below are never throttled.
"""
from datetime import datetime, timedelta, timezone

from app.db import db
from app.models import ErrorEvent


def test_report_error_inserts_row(client, app):
    resp = client.post('/api/v1/events/error', json={
        'error_code': 'decoding',
        'endpoint': '/api/v1/users/me/reputation',
        'http_status': None,
        'app_version': '1.0.0',
        'os_version': '18.5',
    })
    assert resp.status_code == 204
    with app.app_context():
        ev = ErrorEvent.query.one()
        assert ev.error_code == 'decoding'
        assert ev.endpoint == '/api/v1/users/me/reputation'
        assert ev.http_status is None
        assert ev.app_version == '1.0.0'
        assert ev.os_version == '18.5'
        assert ev.auto_delete_at is not None


def test_unknown_error_code_stored_as_unknown(client, app):
    resp = client.post('/api/v1/events/error', json={'error_code': 'totally_made_up'})
    assert resp.status_code == 204
    with app.app_context():
        assert ErrorEvent.query.one().error_code == 'unknown'


def test_empty_body_accepted(client, app):
    resp = client.post('/api/v1/events/error', json={})
    assert resp.status_code == 204
    with app.app_context():
        ev = ErrorEvent.query.one()
        assert ev.error_code == 'unknown'
        assert ev.endpoint is None


def test_oversized_fields_truncated(client, app):
    resp = client.post('/api/v1/events/error', json={
        'error_code': 'transport',
        'endpoint': 'x' * 500,
        'app_version': 'v' * 50,
        'os_version': 'o' * 50,
    })
    assert resp.status_code == 204
    with app.app_context():
        ev = ErrorEvent.query.one()
        assert len(ev.endpoint) == 200
        assert len(ev.app_version) == 20
        assert len(ev.os_version) == 20


def test_non_int_http_status_becomes_null(client, app):
    resp = client.post('/api/v1/events/error', json={
        'error_code': 'server_5xx',
        'http_status': 'five-hundred',
    })
    assert resp.status_code == 204
    with app.app_context():
        assert ErrorEvent.query.one().http_status is None


def test_cleanup_errors_deletes_expired(app):
    runner = app.test_cli_runner()
    with app.app_context():
        fresh = ErrorEvent(error_code='transport')
        expired = ErrorEvent(error_code='decoding')
        expired.auto_delete_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.session.add_all([fresh, expired])
        db.session.commit()
        assert ErrorEvent.query.count() == 2

    result = runner.invoke(args=['cleanup', 'errors'])
    assert result.exit_code == 0

    with app.app_context():
        remaining = ErrorEvent.query.all()
        assert len(remaining) == 1
        assert remaining[0].error_code == 'transport'
