"""Error-monitoring tests — global error handler, alert throttle, alert gating.

The catch-all error handler and the alert throttle live in ``app.monitoring``.
E-mail delivery is hard-disabled under TESTING, so these tests assert behaviour
without sending anything.
"""
from flask import abort

from app.monitoring import _should_send_alert, send_error_alert
from app.redis_keys import ALERT_THROTTLE


def test_unhandled_exception_returns_json_500(app):
    @app.route('/_test/boom')
    def _boom():
        raise ValueError('kaboom')

    resp = app.test_client().get('/_test/boom')
    assert resp.status_code == 500
    assert resp.get_json()['code'] == 'INTERNAL'


def test_http_exception_passes_through(app):
    @app.route('/_test/forbidden')
    def _forbidden():
        abort(403)

    resp = app.test_client().get('/_test/forbidden')
    # A deliberate HTTP status must survive — not be masked as a generic 500.
    assert resp.status_code == 403
    assert b'INTERNAL' not in resp.data


def test_should_send_alert_throttles(app, mock_redis):
    sig = 'app.foo:bar:42'
    with app.app_context():
        assert _should_send_alert(sig) is True   # first occurrence → send
        assert _should_send_alert(sig) is False  # within window → suppressed
    assert mock_redis.exists(f'{ALERT_THROTTLE}{sig}')


def test_alerts_disabled_under_testing(app, mock_redis):
    # TESTING is True in the fixture → send_error_alert must short-circuit
    # before touching Redis or attempting delivery.
    with app.app_context():
        send_error_alert(app, 'body', signature='app.x:y:1')
    assert [k for k in mock_redis.keys() if ALERT_THROTTLE in k] == []
