import os

from dotenv import load_dotenv
from flask import Flask
from flask_mail import Mail
from flask_migrate import Migrate

from .db import db

mail = Mail()

load_dotenv()

_REQUIRED_ENV = ['JWT_SECRET_KEY', 'DATABASE_URL', 'REDIS_URL']


def _validate_config(app: Flask) -> None:
    """Fail fast in production if critical environment variables are missing."""
    if app.config.get('TESTING'):
        return
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"Required environment variables not set: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill in the values."
        )
    if not os.environ.get('APNS_KEY_PATH'):
        app.logger.warning('APNS_KEY_PATH not set — push notifications will be skipped')


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)

    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///:memory:')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')

    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp-relay.brevo.com')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get(
        'MAIL_DEFAULT_SENDER', 'kontakt@safe2gether.de'
    )

    # Session cookie hardening: SameSite=Strict prevents CSRF on admin POST routes.
    # Secure is only set outside of testing (tests run over plain HTTP).
    app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
    app.config['SESSION_COOKIE_HTTPONLY'] = True

    if test_config:
        app.config.update(test_config)

    testing = app.config.get('TESTING', False)
    app.config.setdefault('SESSION_COOKIE_SECURE', not testing)

    _validate_config(app)

    db.init_app(app)
    Migrate(app, db)
    mail.init_app(app)

    # CSP allows the CDN assets used by admin/landing templates while blocking
    # exfiltration to unknown origins. 'unsafe-inline' for scripts is required
    # because the dashboard uses inline <script> blocks; moving them to
    # external files (and using nonces) is a v2 hardening task.
    _CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.tailwindcss.com unpkg.com; "
        "style-src 'self' 'unsafe-inline' cdn.tailwindcss.com unpkg.com "
        "fonts.googleapis.com; "
        "font-src fonts.gstatic.com; "
        "img-src 'self' data: *.basemaps.cartocdn.com *.tile.openstreetmap.org; "
        "connect-src 'self'"
    )

    @app.after_request
    def _security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = _CSP
        if not testing:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    from . import models  # noqa: F401 — registers models with SQLAlchemy
    from .cleanup import register_commands
    register_commands(app)

    from .routes import bp
    app.register_blueprint(bp)

    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from .users import bp as users_bp
    app.register_blueprint(users_bp)

    from .geo import bp as geo_bp
    app.register_blueprint(geo_bp)

    from .heartbeat import bp as heartbeat_bp
    app.register_blueprint(heartbeat_bp)

    from .contacts import bp as contacts_bp
    app.register_blueprint(contacts_bp)

    from .alarm import bp as alarms_bp
    app.register_blueprint(alarms_bp)

    from .escalation import bp as escalation_bp
    app.register_blueprint(escalation_bp)

    from .escalation_worker import start_worker
    start_worker(app)

    @app.template_filter('dt')
    def _dt_filter(value, fmt: str = '%d.%m.%Y') -> str:
        """Format a datetime or ISO string; returns '—' for None."""
        from datetime import datetime as _dt
        if value is None:
            return '—'
        if isinstance(value, str):
            try:
                value = _dt.fromisoformat(value.replace('Z', '+00:00'))
            except (ValueError, AttributeError):
                return str(value)[:10]
        return value.strftime(fmt)

    from .web import bp as web_bp
    app.register_blueprint(web_bp)

    from .admin import bp as admin_bp
    app.register_blueprint(admin_bp)

    return app
