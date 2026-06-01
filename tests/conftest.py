"""Shared pytest fixtures for all test modules."""
import os

# Set test env vars BEFORE importing the app, so load_dotenv() doesn't
# overwrite them with values from the .env file.
os.environ['JWT_SECRET_KEY'] = 'test-jwt-secret-do-not-use-in-production'
os.environ['ENV'] = 'test'

import uuid  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402
import redis  # noqa: E402

from app import create_app  # noqa: E402
from app.db import db as _db  # noqa: E402
from app.models import User  # noqa: E402
from app.token import create_access_token  # noqa: E402

# ─── App + DB fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def _fake_redis_server():
    return fakeredis.FakeServer()


@pytest.fixture(autouse=True)
def mock_redis(_fake_redis_server, monkeypatch):
    """Redirect all redis.from_url() calls to a shared FakeRedis instance."""
    server = _fake_redis_server

    def _fake_from_url(url, **kwargs):
        return fakeredis.FakeRedis(
            server=server,
            decode_responses=kwargs.get('decode_responses', True),
        )

    monkeypatch.setattr(redis, 'from_url', _fake_from_url)

    # Yield the shared fake instance for direct inspection in tests
    fake = fakeredis.FakeRedis(server=server, decode_responses=True)
    yield fake
    # Flush between tests so state doesn't bleed over
    fake.flushall()


@pytest.fixture
def app(_fake_redis_server):
    test_cfg = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-flask-secret',
        'JWT_SECRET_KEY': 'test-jwt-secret-do-not-use-in-production',
    }
    application = create_app(test_cfg)
    with application.app_context():
        _db.create_all()
        yield application
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


# ─── User + token helpers ─────────────────────────────────────────────────────

@pytest.fixture
def make_user(app):
    """Factory: create and persist a User, return (user, access_token)."""
    def _make(email: str = None, auth_provider: str = 'email',
              apple_sub: str = None, google_sub: str = None,
              nearby_alerting_enabled: bool = True) -> tuple[User, str]:
        with app.app_context():
            user = User(
                id=str(uuid.uuid4()),
                auth_provider=auth_provider,
                email=email or f'{uuid.uuid4().hex[:8]}@test.example',
                apple_sub=apple_sub,
                google_sub=google_sub,
                nearby_alerting_enabled=nearby_alerting_enabled,
            )
            _db.session.add(user)
            _db.session.commit()
            token = create_access_token(user.id)
            return user, token
    return _make


@pytest.fixture
def auth_user(make_user):
    """A single pre-created email user with an access token."""
    return make_user(email='alice@example.com')


@pytest.fixture
def auth_headers(auth_user):
    _, token = auth_user
    return {'Authorization': f'Bearer {token}'}
