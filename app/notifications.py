"""APNs push notifications — non-blocking, decoupled from the request cycle.

Sending is fire-and-forget via a background thread so the alarm endpoint
returns immediately. Failures are logged but never bubble up to the caller.

Payload contract (consumed by iOS `Core/Notifications/PushPayload.swift`):
  Common:    type, alarm_id, aps.category (for action-button display)
  nearby_alert: triggered_at (ISO 8601), bearing_degrees, distance_meters,
                responder_count
  alarm_update: event (discriminator), body text in aps.alert.body
"""
import functools
import logging
import os
import threading
import time

import httpx

logger = logging.getLogger(__name__)

_APNS_SANDBOX_HOST = 'https://api.sandbox.push.apple.com'
_APNS_PROD_HOST = 'https://api.push.apple.com'
_APNS_PORT = 443

# iOS-side categories (see Safe2Gether/Core/Notifications/NotificationCategory.swift).
# Setting these is what makes the "Ich helfe" / "Ablehnen" action buttons
# show up on the lock-screen banner.
_CATEGORY_NEARBY = 'NEARBY_ALERT'
_CATEGORY_CONTACT = 'CONTACT_ALERT'

# Structured event discriminators in alarm_update payloads.
EVENT_CONTACT_ALARM_TRIGGERED = 'contact_alarm_triggered'
EVENT_RESPONDER_ADDED = 'responder_added'
EVENT_ALARM_RESOLVED = 'alarm_resolved'
EVENT_ALARM_FALSE_ALARM = 'alarm_false_alarm'

# Dead Man's Switch
EVENT_TIMER_CHECKIN_REQUEST = 'timer_checkin_request'


def _apns_host() -> str:
    sandbox = os.environ.get('APNS_SANDBOX', 'true').lower() == 'true'
    return _APNS_SANDBOX_HOST if sandbox else _APNS_PROD_HOST


@functools.lru_cache(maxsize=2)
def _load_private_key(key_path: str):
    """Load the APNs .p8 signing key from disk, cached per path.

    lru_cache is thread-safe (GIL + internal lock). maxsize=2 covers the
    uncommon case of running sandbox and production keys side by side.
    Key rotation requires a process restart to pick up the new file.
    """
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    with open(key_path, 'rb') as f:
        return load_pem_private_key(f.read(), password=None)


def _send_apns(device_token: str, payload: dict, environment: str = 'sandbox') -> None:
    """Send a single APNs push. Called in a background thread."""
    key_path = os.environ.get('APNS_KEY_PATH', '')
    key_id = os.environ.get('APNS_KEY_ID', '')
    team_id = os.environ.get('APNS_TEAM_ID', '')
    bundle_id = os.environ.get('APNS_BUNDLE_ID', 'com.safe2gether.app')

    if not all([key_path, key_id, team_id]):
        logger.warning('APNs not configured — skipping push to %s', device_token[:8] + '...')
        return

    try:
        import jwt as pyjwt

        private_key = _load_private_key(key_path)
        token = pyjwt.encode(
            {'iss': team_id, 'iat': int(time.time())},
            private_key,
            algorithm='ES256',
            headers={'kid': key_id},
        )

        host = _APNS_SANDBOX_HOST if environment == 'sandbox' else _APNS_PROD_HOST
        url = f'{host}/3/device/{device_token}'

        with httpx.Client(http2=True) as client:
            resp = client.post(
                url,
                json=payload,
                headers={
                    'authorization': f'bearer {token}',
                    'apns-topic': bundle_id,
                    'apns-push-type': 'alert',
                    'apns-priority': '10',
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.error('APNs error %s for token %s: %s',
                             resp.status_code, device_token[:8], resp.text)
    except Exception:
        logger.exception('APNs send failed for token %s', device_token[:8] + '...')


_ALERT_TYPE_TITLES = {
    'panic': 'Notruf in deiner Nähe',
    'need_help': 'Jemand braucht Hilfe in deiner Nähe',
    'car_breakdown': 'Auto liegengeblieben in deiner Nähe',
    'cant_get_home': 'Jemand kommt nicht nach Hause — in deiner Nähe',
}


def send_nearby_alert(
    device_token: str,
    environment: str,
    alarm_id: str,
    triggered_at_iso: str,
    bearing_degrees: float,
    distance_meters: int,
    responder_count: int = 0,
    alert_type: str = 'panic',
    home_distance_category: str | None = None,
) -> None:
    """Non-blocking: notify a nearby user that an alarm was triggered.

    Sets `aps.category = NEARBY_ALERT` so iOS attaches the registered
    "Ich helfe" / "Ablehnen" action buttons to the banner.
    """
    title = _ALERT_TYPE_TITLES.get(alert_type, _ALERT_TYPE_TITLES['panic'])
    body = f'{_distance_label(distance_meters)} · {_compass_label(bearing_degrees)}'
    payload = {
        'aps': {
            'alert': {
                'title': title,
                'body': body,
            },
            'sound': 'default',
            'badge': 1,
            'category': _CATEGORY_NEARBY,
        },
        'type': 'nearby_alert',
        'alarm_id': alarm_id,
        'alert_type': alert_type,
        'triggered_at': triggered_at_iso,
        'bearing_degrees': bearing_degrees,
        'distance_meters': distance_meters,
        'responder_count': responder_count,
        'home_distance_category': home_distance_category,
    }
    threading.Thread(
        target=_send_apns, args=(device_token, payload, environment), daemon=True
    ).start()


def send_timer_checkin_request(
    device_token: str,
    environment: str,
    timer_id: str,
    note: str | None = None,
) -> None:
    """Non-blocking: ask the timer owner to check in (Dead Man's Switch)."""
    body = note or 'Bitte melde dich — dein Sicherheits-Timer läuft ab.'
    payload = {
        'aps': {
            'alert': {
                'title': 'Bist du okay?',
                'body': body,
            },
            'sound': 'default',
            'badge': 1,
        },
        'type': 'timer_checkin_request',
        'timer_id': timer_id,
        'event': EVENT_TIMER_CHECKIN_REQUEST,
    }
    threading.Thread(
        target=_send_apns, args=(device_token, payload, environment), daemon=True
    ).start()


def send_alarm_update(
    device_token: str,
    environment: str,
    alarm_id: str,
    event: str,
    body: str,
) -> None:
    """Non-blocking: notify alarm owner or responder of a status change.

    `event` is a stable discriminator the iOS client can switch on without
    parsing the localized banner body. Use the EVENT_* constants in this
    module.
    """
    payload = {
        'aps': {
            'alert': {'title': 'Alarm-Update', 'body': body},
            'sound': 'default',
            'category': _CATEGORY_CONTACT,
        },
        'type': 'alarm_update',
        'alarm_id': alarm_id,
        'event': event,
    }
    threading.Thread(
        target=_send_apns, args=(device_token, payload, environment), daemon=True
    ).start()


# ─── Banner formatting helpers ───────────────────────────────────────────────

def _compass_label(bearing_degrees: float) -> str:
    """8-point compass label for an absolute bearing (0=N, clockwise)."""
    d = bearing_degrees % 360
    labels = ('N', 'NO', 'O', 'SO', 'S', 'SW', 'W', 'NW')
    return labels[int((d + 22.5) // 45) % 8]


def _distance_label(meters: int) -> str:
    if meters < 1000:
        return f'ca. {meters} m'
    return f'ca. {meters / 1000:.1f} km'
