import os

from dotenv import load_dotenv
from flask import Flask
from flask_migrate import Migrate

from .db import db

load_dotenv()


def create_app(test_config=None):
    app = Flask(__name__)

    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///:memory:')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')

    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    Migrate(app, db)

    from . import models  # noqa: F401 — registers models with SQLAlchemy
    from .routes import bp
    app.register_blueprint(bp)

    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from .users import bp as users_bp
    app.register_blueprint(users_bp)

    return app
