import os

import redis as redis_lib
from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

bp = Blueprint('api', __name__, url_prefix='/api/v1')

VERSION = '1.0.0'


def _check_db() -> str:
    try:
        from .db import db
        db.session.execute(text('SELECT 1'))
        return 'ok'
    except Exception:
        return 'error'


def _check_redis() -> str:
    try:
        redis_url = current_app.config.get('REDIS_URL') or os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        r = redis_lib.from_url(redis_url, socket_connect_timeout=2)
        r.ping()
        return 'ok'
    except Exception:
        return 'error'


@bp.get('/health')
def health():
    db_status = _check_db()
    redis_status = _check_redis()

    overall = 'ok' if (db_status == 'ok' and redis_status == 'ok') else 'degraded'

    return jsonify({
        'status': overall,
        'node_id': os.environ.get('NODE_ID', 'unknown'),
        'version': VERSION,
        'db_status': db_status,
        'redis_status': redis_status,
    })
