"""Admin dashboard blueprint — /admin."""
import base64
import functools
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pyotp
import qrcode
import redis as redis_lib
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import text

from .db import db
from .notifications import send_push_sync
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


# ── 2FA (TOTP) ────────────────────────────────────────────────────────────────

_TOTP_SECRET = os.environ.get('ADMIN_TOTP_SECRET', '')


def _totp_qr_png_b64(secret: str) -> str:
    uri = pyotp.TOTP(secret).provisioning_uri(
        name='Safe2Gether Admin', issuer_name='Safe2Gether'
    )
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def _totp_code_fresh(code: str) -> bool:
    """Return True if the code is valid and not replayed within the last 90 s."""
    if not _TOTP_SECRET or not code:
        return False
    if not pyotp.TOTP(_TOTP_SECRET).verify(code, valid_window=1):
        return False
    try:
        r = _redis()
        key = f'admin:totp_used:{code}'
        if r.exists(key):
            return False  # replay attempt
        r.setex(key, 90, '1')
    except Exception:
        pass  # Redis outage: skip replay check rather than locking out admin
    return True


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
            if session.get('admin_2fa_pending'):
                return redirect(url_for('admin.totp_verify'))
            return redirect(url_for('admin.login'))
        login_ts = session.get('admin_login_at')
        if login_ts:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(login_ts)
            if age > _SESSION_MAX_AGE:
                session.clear()
                return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return _wrapped


def _require_2fa_pending(f):
    @functools.wraps(f)
    def _wrapped(*args, **kwargs):
        if not session.get('admin_2fa_pending'):
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
        session['admin_login_at'] = datetime.now(timezone.utc).isoformat()
        session.permanent = False
        if _TOTP_SECRET:
            session['admin_2fa_pending'] = True
            return redirect(url_for('admin.totp_verify'))
        session['admin_logged_in'] = True
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


@bp.post('/users/<user_id>/delete')
@require_admin
def user_delete(user_id: str):
    """Hard-delete a user. Guard: only allowed when is_active = false."""
    try:
        result = db.session.execute(
            text('DELETE FROM users WHERE id = :id AND is_active = false'),
            {'id': user_id},
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        return redirect(url_for('admin.user_detail', user_id=user_id))
    if result.rowcount == 0:
        return redirect(url_for('admin.user_detail', user_id=user_id))
    return redirect(url_for('admin.user_list'))


# ── 2FA routes ────────────────────────────────────────────────────────────────

@bp.get('/2fa/verify')
@_require_2fa_pending
def totp_verify():
    return render_template('admin/2fa_verify.html', error=None)


@bp.post('/2fa/verify')
@_require_2fa_pending
def totp_verify_post():
    code = request.form.get('code', '').strip().replace(' ', '')
    if _totp_code_fresh(code):
        session.pop('admin_2fa_pending', None)
        session['admin_logged_in'] = True
        return redirect(url_for('admin.dashboard'))
    return render_template('admin/2fa_verify.html', error='Ungültiger oder abgelaufener Code.'), 401


@bp.get('/2fa/setup')
@require_admin
def totp_setup():
    if _TOTP_SECRET:
        secret = _TOTP_SECRET
        session.pop('totp_setup_secret', None)
    else:
        secret = session.get('totp_setup_secret') or pyotp.random_base32()
        session['totp_setup_secret'] = secret
    return render_template(
        'admin/2fa_setup.html',
        secret=secret,
        qr_b64=_totp_qr_png_b64(secret),
        already_configured=bool(_TOTP_SECRET),
        verified=False,
        error=None,
    )


@bp.post('/2fa/setup')
@require_admin
def totp_setup_post():
    secret = _TOTP_SECRET or session.get('totp_setup_secret', '')
    code = request.form.get('code', '').strip().replace(' ', '')
    if secret and pyotp.TOTP(secret).verify(code, valid_window=1):
        session.pop('totp_setup_secret', None)
        return render_template(
            'admin/2fa_setup.html',
            secret=secret,
            qr_b64=_totp_qr_png_b64(secret),
            already_configured=bool(_TOTP_SECRET),
            verified=True,
            error=None,
        )
    return render_template(
        'admin/2fa_setup.html',
        secret=secret,
        qr_b64=_totp_qr_png_b64(secret),
        already_configured=bool(_TOTP_SECRET),
        verified=False,
        error='Ungültiger Code — bitte erneut versuchen.',
    ), 400


# ── Test-Push dashboard ───────────────────────────────────────────────────────

_PUSH_TYPES = ('nearby_alert', 'contact_alarm', 'timer_checkin_request', 'responder_added')


def _build_push_payload(push_type: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    rand_id = str(uuid.uuid4())
    if push_type == 'nearby_alert':
        return {
            'aps': {
                'alert': {'title': '⚠️ Test-Alarm', 'body': 'Dies ist ein Test-Nearby-Alert.'},
                'sound': 'default',
                'category': 'NEARBY_ALERT',
            },
            'type': 'nearby_alert',
            'alarm_id': rand_id,
            'triggered_at': now,
            'bearing_degrees': 45.0,
            'distance_meters': 350.0,
            'responder_count': 0,
            'alert_type': 'panic',
        }
    if push_type == 'contact_alarm':
        return {
            'aps': {
                'alert': {
                    'title': 'Kontakt braucht Hilfe',
                    'body': 'Ein Kontakt hat einen Alarm ausgelöst.',
                },
                'sound': 'default',
                'category': 'CONTACT_ALERT',
            },
            'type': 'alarm_update',
            'event': 'contact_alarm_triggered',
            'alarm_id': rand_id,
        }
    if push_type == 'timer_checkin_request':
        return {
            'aps': {
                'alert': {
                    'title': 'Alles okay?',
                    'body': 'Bitte melde dich — dein Timer läuft bald ab.',
                },
                'sound': 'default',
            },
            'type': 'timer_checkin_request',
            'timer_id': rand_id,
        }
    # responder_added — silent background push
    return {
        'aps': {'content-available': 1},
        'type': 'alarm_update',
        'event': 'responder_added',
        'alarm_id': rand_id,
    }


_DEVICE_LIST_SQL = """
    SELECT id, email, apns_device_token, apns_environment, created_at
    FROM users
    WHERE apns_device_token IS NOT NULL
    ORDER BY created_at DESC
    LIMIT 200
"""


def _push_env_guard():
    """Return a 403 response if running in production, else None."""
    if _ENV == 'prod':
        return (
            '<h1>403 — Nicht verfügbar</h1>'
            '<p>Test-Pushes sind in der Produktionsumgebung deaktiviert (DSGVO).<br>'
            'Nur in <code>ENV=dev</code> nutzbar.</p>'
        ), 403
    return None


@bp.get('/push')
@require_admin
def push_dashboard():
    if (guard := _push_env_guard()):
        return guard
    devices = _q_all(_DEVICE_LIST_SQL)
    push_result = session.pop('push_result', None)
    return render_template(
        'admin/push.html',
        devices=devices,
        push_types=_PUSH_TYPES,
        push_result=push_result,
    )


@bp.post('/push')
@require_admin
def push_send():
    if (guard := _push_env_guard()):
        return guard

    user_id = request.form.get('user_id', '').strip()
    push_type = request.form.get('push_type', 'nearby_alert')
    custom_json = request.form.get('custom_json', '').strip()

    if not user_id:
        session['push_result'] = {'ok': False, 'status': 0, 'body': 'Kein Gerät ausgewählt.'}
        return redirect(url_for('admin.push_dashboard'))

    # Token-Lookup server-seitig — Token verlässt nie den Browser
    rows = _q_all(
        'SELECT apns_device_token, apns_environment FROM users '
        'WHERE id = :id AND apns_device_token IS NOT NULL',
        {'id': user_id},
    )
    if not rows:
        session['push_result'] = {'ok': False, 'status': 0, 'body': 'Gerät nicht gefunden'}
        return redirect(url_for('admin.push_dashboard'))

    device_token = rows[0]['apns_device_token']
    environment = rows[0]['apns_environment'] or 'sandbox'

    if push_type not in _PUSH_TYPES:
        push_type = 'nearby_alert'

    if custom_json:
        try:
            payload = json.loads(custom_json)
        except json.JSONDecodeError as exc:
            session['push_result'] = {'ok': False, 'status': 0, 'body': f'Ungültiges JSON: {exc}'}
            return redirect(url_for('admin.push_dashboard'))
    else:
        payload = _build_push_payload(push_type)

    status, body = send_push_sync(device_token, payload, environment)
    session['push_result'] = {'ok': status == 200, 'status': status, 'body': body}
    return redirect(url_for('admin.push_dashboard'))
