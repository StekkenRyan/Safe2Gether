import os

from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate

from .db import db

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

    if test_config:
        app.config.update(test_config)

    _validate_config(app)

    db.init_app(app)
    Migrate(app, db)

    @app.after_request
    def _security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if not app.config.get('TESTING'):
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

    return app
