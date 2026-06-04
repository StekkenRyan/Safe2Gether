"""Admin dashboard blueprint — /admin."""
import functools
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import redis as redis_lib
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import text

from .db import db
from .redis_keys import CONTACT_INVITE, GEO_CELL, HB

_MIN_USER_CELL_COUNT = 5  # DSGVO: omit cells with fewer active users from the map
_VALID_LEVELS = ('very_low', 'low', 'normal', 'high', 'very_high')
_SESSION_MAX_AGE = timedelta(hours=8)       # absolute session lifetime
_LOGIN_RATE_LIMIT = 5                       # max failed attempts before lockout
_LOGIN_RATE_WINDOW = 900                    # 15-minute window (seconds)

bp = Blueprint('admin', __name__, url_prefix='/admin')

_ENV = os.environ.get('ENV', 'dev')

_ENV_CONFIG = {
    'prod': {'label': 'PROD', 'link_label': '→ DEV', 'link': 'https://dev.safe2gether.de/admin/'},
    'dev':  {'label': 'DEV',  'link_label': '→ PROD', 'link': 'https://api.safe2gether.de/admin/'},
}


@bp.context_processor
def inject_env() -> dict:
    cfg = _ENV_CONFIG.get(_ENV, _ENV_CONFIG['dev'])
    return {'env': _ENV, 'env_cfg': cfg}


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _check_credentials(username: str, password: str) -> bool:
    stored_user = os.environ.get('ADMIN_USERNAME', 'admin')
    stored_pass = os.environ.get('ADMIN_PASSWORD', '')
    # Guard: unconfigured password must never grant access
    if not stored_pass:
        return False
    if not secrets.compare_digest(username.encode(), stored_user.encode()):
        return False
    if stored_pass.startswith('$2b$'):
        return bcrypt.checkpw(password.encode(), stored_pass.encode())
    return secrets.compare_digest(password.encode(), stored_pass.encode())


def _login_rate_key() -> str:
    ip = request.headers.get('CF-Connecting-IP') or request.remote_addr or 'unknown'
    return f'admin:login_fail:{ip}'


def _is_rate_limited() -> bool:
    """Return True when the source IP has exceeded the failed-login threshold."""
    try:
        r = _redis()
        key = _login_rate_key()
        count = r.get(key)
        return int(count or 0) >= _LOGIN_RATE_LIMIT
    except Exception:
        return False  # fail open — never block legitimate access due to Redis outage


def _record_failed_login() -> None:
    try:
        r = _redis()
        key = _login_rate_key()
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOGIN_RATE_WINDOW)
        pipe.execute()
    except Exception:
        pass


def _clear_login_failures() -> None:
    try:
        _redis().delete(_login_rate_key())
    except Exception:
        pass


def require_admin(f):
    @functools.wraps(f)
    def _wrapped(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        # Absolute session timeout: reject sessions older than _SESSION_MAX_AGE
        login_ts = session.get('admin_login_at')
        if login_ts:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(login_ts)
            if age > _SESSION_MAX_AGE:
                session.clear()
                return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return _wrapped


# ── Redis helper ───────────────────────────────────────────────────────────────

def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


# ── Metrics collection ────────────────────────────────────────────────────────

def _q(sql: str, params=None):
    """Execute a scalar SQL query and return the result, or None on error."""
    try:
        return db.session.execute(text(sql), params or {}).scalar()
    except Exception:
        return None


def _q_all(sql: str, params=None):
    """Execute a SQL query and return all rows as mappings, or [] on error."""
    try:
        return db.session.execute(text(sql), params or {}).mappings().all()
    except Exception:
        return []


def _collect_metrics() -> dict:
    m: dict = {}

    # ── Users ─────────────────────────────────────────────────────────────────
    m['users_total'] = _q('SELECT COUNT(*) FROM users')
    m['users_active_7d'] = _q(
        "SELECT COUNT(*) FROM users WHERE updated_at >= NOW() - INTERVAL '7 days'"
    )
    m['users_active_30d'] = _q(
        "SELECT COUNT(*) FROM users WHERE updated_at >= NOW() - INTERVAL '30 days'"
    )
    m['users_nearby_optout'] = _q(
        'SELECT COUNT(*) FROM users WHERE nearby_alerting_enabled = false'
    )
    m['users_no_push'] = _q(
        'SELECT COUNT(*) FROM users WHERE apns_device_token IS NULL'
    )

    total = m['users_total'] or 1
    rows = _q_all(
        'SELECT auth_provider AS provider, COUNT(*) AS count FROM users GROUP BY auth_provider'
    )
    m['auth_providers'] = [
        {'provider': r['provider'], 'count': r['count'], 'pct': r['count'] * 100 / total}
        for r in rows
    ]

    # ── Alarms ────────────────────────────────────────────────────────────────
    m['alarms_total'] = _q('SELECT COUNT(*) FROM alarms')
    m['alarms_today'] = _q(
        "SELECT COUNT(*) FROM alarms WHERE DATE(triggered_at) = CURRENT_DATE"
    )
    m['alarms_active'] = _q("SELECT COUNT(*) FROM alarms WHERE status = 'active'")
    m['alarms_by_status'] = [
        {'status': r['status'], 'count': r['count']}
        for r in _q_all(
            """
            SELECT status, COUNT(*) AS count FROM alarms
            WHERE triggered_at >= NOW() - INTERVAL '30 days'
            GROUP BY status ORDER BY count DESC
            """
        )
    ]
    avg = _q(
        """
        SELECT AVG(c) FROM (
            SELECT COUNT(*) AS c FROM alarm_responders GROUP BY alarm_id
        ) sub
        """
    )
    m['alarms_avg_responders'] = f'{avg:.2f}' if avg is not None else None

    # ── Reputation ────────────────────────────────────────────────────────────
    _level_order = ['very_low', 'low', 'normal', 'high', 'very_high']
    level_rows = _q_all(
        'SELECT reputation_level AS level, COUNT(*) AS count FROM users GROUP BY reputation_level'
    )
    level_map = {r['level']: r['count'] for r in level_rows}
    m['reputation_levels'] = [
        {'level': lvl, 'count': level_map.get(lvl, 0)} for lvl in _level_order
    ]
    m['score_min'] = _q('SELECT MIN(reputation_score) FROM users')
    m['score_max'] = _q('SELECT MAX(reputation_score) FROM users')
    m['score_median'] = _q(
        'SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY reputation_score) FROM users'
    )
    if m['score_median'] is not None:
        m['score_median'] = round(m['score_median'])

    # ── Contacts ──────────────────────────────────────────────────────────────
    m['contacts_total'] = _q('SELECT COUNT(*) FROM emergency_contacts')
    m['contacts_by_type'] = [
        {'type': r['contact_type'], 'count': r['count']}
        for r in _q_all(
            'SELECT contact_type, COUNT(*) AS count FROM emergency_contacts '
            'GROUP BY contact_type ORDER BY count DESC'
        )
    ]

    # Invite tokens in Redis (SCAN to avoid blocking)
    invite_pattern = f'{CONTACT_INVITE}*'
    try:
        r = _redis()
        count = sum(1 for _ in r.scan_iter(invite_pattern, count=500))
        m['invite_token_count'] = count
    except Exception:
        m['invite_token_count'] = None

    # ── Technical ─────────────────────────────────────────────────────────────
    try:
        r = _redis()
        r.ping()
        m['redis_status'] = 'pong'
        info = r.info('memory')
        m['redis_memory'] = info.get('used_memory_human', '?')
    except Exception:
        m['redis_status'] = 'error'
        m['redis_memory'] = None

    try:
        pg_ver = _q('SELECT version()')
        m['db_status'] = 'ok'
        m['pg_version'] = pg_ver.split(' ')[1] if pg_ver else None
    except Exception:
        m['db_status'] = 'error'
        m['pg_version'] = None

    m['db_connections'] = _q('SELECT COUNT(*) FROM pg_stat_activity')

    last_alarm = _q('SELECT MAX(triggered_at) FROM alarms')
    m['last_alarm_at'] = last_alarm.isoformat() + 'Z' if last_alarm else None

    # Last heartbeat: find any active HB key via SCAN
    hb_pattern = f'{HB}*'
    m['last_heartbeat_at'] = None
    try:
        r = _redis()
        for key in r.scan_iter(hb_pattern, count=1):
            m['last_heartbeat_at'] = key  # presence is enough for v1
            break
    except Exception:
        pass

    return m


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.get('/login')
def login():
    return render_template('admin/login.html', error=None)


@bp.post('/login')
def login_post():
    if _is_rate_limited():
        return render_template(
            'admin/login.html',
            error='Zu viele Fehlversuche. Bitte 15 Minuten warten.',
        ), 429

    username = request.form.get('username', '')
    password = request.form.get('password', '')
    if _check_credentials(username, password):
        _clear_login_failures()
        session.clear()
        session['admin_logged_in'] = True
        session['admin_login_at'] = datetime.now(timezone.utc).isoformat()
        session.permanent = False
        return redirect(url_for('admin.dashboard'))

    _record_failed_login()
    return render_template('admin/login.html', error='Ungültige Anmeldedaten.'), 401


@bp.get('/logout')
@require_admin
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))


@bp.get('/')
@require_admin
def dashboard():
    m = _collect_metrics()
    now = datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
    return render_template('admin/dashboard.html', m=m, now=now)


# ── Geo API ───────────────────────────────────────────────────────────────────

@bp.get('/api/geo')
@require_admin
def geo_data():
    """Aggregated H3 cell counts for the dashboard map.

    User cells with fewer than _MIN_USER_CELL_COUNT active members are omitted
    so individual users cannot be identified from a single-occupant cell.
    """
    user_cells: dict[str, int] = {}
    try:
        r = _redis()
        for key in r.scan_iter(f'{GEO_CELL}*', count=500):
            cell = key[len(GEO_CELL):]
            count = r.scard(key)
            if count >= _MIN_USER_CELL_COUNT:
                user_cells[cell] = count
    except Exception:
        pass

    alarm_rows = _q_all(
        'SELECT geohash_snapshot AS cell, COUNT(*) AS cnt FROM alarms '
        'WHERE geohash_snapshot IS NOT NULL GROUP BY geohash_snapshot'
    )

    return jsonify({
        'users': [{'cell': c, 'count': n} for c, n in user_cells.items()],
        'alarms': [{'cell': r['cell'], 'count': r['cnt']} for r in alarm_rows],
    })


# ── User reviewing ────────────────────────────────────────────────────────────

_USER_LIST_SQL = """
    SELECT id, email, auth_provider, reputation_score, reputation_level,
           is_active, nearby_alerting_enabled, created_at, updated_at
    FROM users
    {where}
    ORDER BY reputation_score ASC
    LIMIT 100
"""

_USER_DETAIL_SQL = """
    SELECT id, email, phone_number, auth_provider, apple_sub,
           reputation_score, reputation_level, is_active,
           nearby_alerting_enabled, apns_device_token,
           created_at, updated_at, scheduled_deletion_at
    FROM users WHERE id = :id
"""

_REPUTATION_ACTIONS_SQL = """
    SELECT action_type, score_delta, alarm_id, created_at
    FROM reputation_actions
    WHERE user_id = :id
    ORDER BY created_at DESC
    LIMIT 50
"""


@bp.get('/users')
@require_admin
def user_list():
    level_filter = request.args.get('level', 'all')
    provider_filter = request.args.get('provider', 'all')

    conditions = []
    params: dict = {}
    if level_filter != 'all' and level_filter in _VALID_LEVELS:
        conditions.append('reputation_level = :level')
        params['level'] = level_filter
    if provider_filter != 'all':
        conditions.append('auth_provider = :provider')
        params['provider'] = provider_filter

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    users = _q_all(_USER_LIST_SQL.format(where=where), params)

    providers = [
        r['auth_provider']
        for r in _q_all('SELECT DISTINCT auth_provider FROM users ORDER BY auth_provider')
    ]

    return render_template(
        'admin/users.html',
        users=users,
        level_filter=level_filter,
        provider_filter=provider_filter,
        providers=providers,
        levels=_VALID_LEVELS,
    )


@bp.get('/users/<user_id>')
@require_admin
def user_detail(user_id: str):
    rows = _q_all(_USER_DETAIL_SQL, {'id': user_id})
    if not rows:
        return redirect(url_for('admin.user_list'))
    actions = _q_all(_REPUTATION_ACTIONS_SQL, {'id': user_id})
    return render_template('admin/user_detail.html', user=rows[0], actions=actions)


@bp.post('/users/<user_id>/deactivate')
@require_admin
def user_deactivate(user_id: str):
    try:
        db.session.execute(
            text('UPDATE users SET is_active = false WHERE id = :id'), {'id': user_id}
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin.user_detail', user_id=user_id))


@bp.post('/users/<user_id>/reactivate')
@require_admin
def user_reactivate(user_id: str):
    try:
        db.session.execute(
            text('UPDATE users SET is_active = true WHERE id = :id'), {'id': user_id}
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin.user_detail', user_id=user_id))


@bp.post('/users/<user_id>/reset-score')
@require_admin
def user_reset_score(user_id: str):
    try:
        db.session.execute(
            text("UPDATE users SET reputation_score = 0, reputation_level = 'normal' "
                 'WHERE id = :id'),
            {'id': user_id},
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
    return redirect(url_for('admin.user_detail', user_id=user_id))
