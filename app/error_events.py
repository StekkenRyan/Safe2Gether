"""Anonymous error-reporting endpoint — POST /api/v1/events/error.

The iOS client fires a non-blocking report when it cannot decode a response or
hits a 5xx. No bearer token is required, but the route is IP rate-limited
(Cloudflare forwards the real IP via CF-Connecting-IP, read by ``client_ip``).

DSGVO: the stored row contains no user id and no IP — only a coarse error code,
endpoint path, HTTP status and client/OS version. See ``models.ErrorEvent``.
"""
from flask import Blueprint, current_app, request

from .db import db
from .models import ErrorEvent
from .monitoring import send_error_alert
from .ratelimit import rate_limit

bp = Blueprint('errors', __name__, url_prefix='/api/v1')

ALLOWED_CODES = {'decoding', 'server_5xx', 'transport', 'auth_failure'}
# Codes worth an immediate operator alert (API-contract break / server fault).
_ALERT_CODES = {'decoding', 'server_5xx'}


@bp.post('/events/error')
@rate_limit(limit=10, window_seconds=60, scope='error_report')
def report_error():
    data = request.get_json(silent=True) or {}

    code = data.get('error_code')
    if code not in ALLOWED_CODES:
        code = 'unknown'

    http_status = data.get('http_status')
    if not isinstance(http_status, int):
        http_status = None

    endpoint = (data.get('endpoint') or '')[:200] or None
    app_version = (data.get('app_version') or '')[:20] or None
    os_version = (data.get('os_version') or '')[:20] or None

    event = ErrorEvent(
        error_code=code,
        endpoint=endpoint,
        http_status=http_status,
        app_version=app_version,
        os_version=os_version,
    )
    db.session.add(event)
    db.session.commit()

    if code in _ALERT_CODES:
        send_error_alert(
            current_app._get_current_object(),
            f'Client-Error: {code}\nEndpoint: {endpoint or "–"}\nApp: {app_version or "–"}',
            signature=f'client_error:{code}:{endpoint}',
        )

    return '', 204
