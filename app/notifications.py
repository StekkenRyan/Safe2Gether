"""APNs push notifications — non-blocking, decoupled from the request cycle.

Sending is fire-and-forget via a background thread so the alarm endpoint
returns immediately. Failures are logged but never bubble up to the caller.
"""
import logging
import os
import threading
import time

import httpx

logger = logging.getLogger(__name__)

_APNS_SANDBOX_HOST = 'https://api.sandbox.push.apple.com'
_APNS_PROD_HOST = 'https://api.push.apple.com'
_APNS_PORT = 443


def _apns_host() -> str:
    sandbox = os.environ.get('APNS_SANDBOX', 'true').lower() == 'true'
    return _APNS_SANDBOX_HOST if sandbox else _APNS_PROD_HOST


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
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        with open(key_path, 'rb') as f:
            private_key = load_pem_private_key(f.read(), password=None)

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


def send_nearby_alert(device_token: str, environment: str,
                      alarm_id: str, direction: str, distance_m: int) -> None:
    """Non-blocking: notify a nearby user that an alarm was triggered."""
    payload = {
        'aps': {
            'alert': {
                'title': 'Hilferuf in deiner Nähe',
                'body': f'{direction}, ca. {distance_m} m entfernt',
            },
            'sound': 'default',
            'badge': 1,
        },
        'alarm_id': alarm_id,
        'type': 'nearby_alert',
    }
    threading.Thread(
        target=_send_apns, args=(device_token, payload, environment), daemon=True
    ).start()


def send_alarm_update(device_token: str, environment: str,
                      alarm_id: str, event: str) -> None:
    """Non-blocking: notify alarm owner or responder of a status change."""
    payload = {
        'aps': {
            'alert': {'title': 'Alarm-Update', 'body': event},
            'sound': 'default',
        },
        'alarm_id': alarm_id,
        'type': 'alarm_update',
    }
    threading.Thread(
        target=_send_apns, args=(device_token, payload, environment), daemon=True
    ).start()
