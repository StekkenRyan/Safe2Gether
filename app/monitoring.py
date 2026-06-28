"""Error monitoring — file logging + e-mail alerts (Flask-Mail / Brevo).

Two layers:
  * a RotatingFileHandler that always captures WARNING+ to logs/safe2gether.log
  * a MailAlertHandler that e-mails the operator on ERROR+ (production only),
    throttled so a stuck dependency can never flood the inbox, and delivered in
    a background thread so the alert never blocks the request cycle (same
    decoupled-outbound invariant as the APNs push path).

DSGVO: only the HTTP method, ``request.path`` (no query string), the exception
type and its traceback are recorded — never a user id, e-mail, coordinates or
the request body.
"""
import logging
import os
import threading
from logging.handlers import RotatingFileHandler

import redis as redis_lib
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .redis_keys import ALERT_THROTTLE

_LOG_FILENAME = 'safe2gether.log'
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5
_LOG_FORMAT = '%(asctime)s %(levelname)s [%(name)s] %(message)s'

_ALERT_SUBJECT = '[Safe2Gether] Server-Fehler'
_ALERT_THROTTLE_TTL = 300  # one e-mail per identical log site / 5 min


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def _alerts_enabled() -> bool:
    return os.environ.get('ERROR_ALERTS_ENABLED', 'true').lower() == 'true'


def _should_send_alert(signature: str) -> bool:
    """Throttle: return True at most once per ``signature`` within the TTL.

    Fail-open — if Redis is unavailable we send rather than risk silently
    dropping an alert.
    """
    try:
        key = f'{ALERT_THROTTLE}{signature}'
        # SET NX returns True only when the key did not already exist.
        return bool(_redis().set(key, '1', nx=True, ex=_ALERT_THROTTLE_TTL))
    except redis_lib.RedisError:
        return True


def send_error_alert(app: Flask, body: str, signature: str | None = None) -> None:
    """E-mail the operator about a server error — throttled and non-blocking.

    Safe to call from anywhere: every error is swallowed so the alert path can
    neither affect the triggering request nor recurse back into logging.
    """
    if app.config.get('TESTING') or not _alerts_enabled():
        return
    recipient = os.environ.get('ERROR_ALERT_EMAIL')
    if not recipient:
        return
    if signature is not None and not _should_send_alert(signature):
        return

    def _deliver() -> None:
        try:
            from flask_mail import Message

            from . import mail
            with app.app_context():
                mail.send(Message(
                    subject=_ALERT_SUBJECT,
                    recipients=[recipient],
                    body=body,
                ))
        except Exception:
            pass  # alerting must never raise

    threading.Thread(target=_deliver, daemon=True).start()


class MailAlertHandler(logging.Handler):
    """Logging handler that forwards ERROR+ records to :func:`send_error_alert`,
    keyed on the originating code site so repeated failures are throttled."""

    def __init__(self, app: Flask):
        super().__init__(level=logging.ERROR)
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            signature = f'{record.name}:{record.funcName}:{record.lineno}'
            send_error_alert(self._app, self.format(record), signature)
        except Exception:
            pass


def configure_logging(app: Flask) -> None:
    """Attach the rotating file handler (always) and, in production with
    ``ERROR_ALERTS_ENABLED``, the e-mail alert handler."""
    log_dir = os.environ.get('LOG_DIR', 'logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, _LOG_FILENAME),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding='utf-8',
        )
        file_handler.setLevel(logging.WARNING)
        file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        app.logger.addHandler(file_handler)
    except OSError:
        app.logger.warning('Could not create log dir %s — file logging disabled', log_dir)

    # Make sure WARNING/ERROR records actually reach the handlers above.
    app.logger.setLevel(logging.WARNING)

    if not app.config.get('TESTING') and _alerts_enabled():
        mail_handler = MailAlertHandler(app)
        mail_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        app.logger.addHandler(mail_handler)


def register_error_handler(app: Flask) -> None:
    """Global catch-all: log unexpected exceptions (no PII) and return a generic
    JSON 500. Known HTTP exceptions keep their intended status and body."""
    @app.errorhandler(Exception)
    def _handle_unhandled(exc):
        if isinstance(exc, HTTPException):
            if exc.code and exc.code >= 500:
                app.logger.error('HTTP %s on %s %s', exc.code, request.method, request.path)
            return exc
        app.logger.error(
            'Unhandled exception on %s %s: %s',
            request.method, request.path, type(exc).__name__,
            exc_info=True,
        )
        return jsonify({'error': 'Internal Server Error', 'code': 'INTERNAL'}), 500
