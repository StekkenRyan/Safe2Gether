import os
from flask import Flask
from flask_migrate import Migrate
from dotenv import load_dotenv

from .db import db

load_dotenv()


def create_app():
    app = Flask(__name__)

    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')

    db.init_app(app)
    Migrate(app, db)

    from . import models  # noqa: F401 — registers models with SQLAlchemy

    from .routes import bp
    app.register_blueprint(bp)

    return app
