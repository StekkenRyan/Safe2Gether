"""End-to-end tests for the escalation-chain scheduler.

Verifies that triggering an alarm enqueues the user-configured chain into
the Redis sorted set, that the worker's `drain_due` honours alarm state
mid-flight, and that the `contacts+community` parallel stage dispatches
both fanouts.
"""
import time

from app.escalation_worker import drain_due, pop_due_items
from app.redis_keys import ESCALATION_QUEUE


def _trigger(client, headers, geohash=None):
    payload = {'trigger_source': 'in_app'}
    if geohash:
        payload['geohash_snapshot'] = geohash
    return client.post('/api/v1/alarms', json=payload, headers=headers)


# ─── Default chain enqueue ────────────────────────────────────────────────────

def test_default_chain_runs_stage_zero_inline_and_queues_rest(
    client, auth_headers, mock_redis
):
    resp = _trigger(client, auth_headers)
    assert resp.status_code == 201
    alarm_id = resp.get_json()['id']
    # Default chain: device_local → contacts → community
    assert resp.get_json()['escalation_stage'] == 'device_local'

    # Stages 1 and 2 must be queued
    members = mock_redis.zrange(ESCALATION_QUEUE, 0, -1, withscores=True)
    queued = {m for m, _ in members}
    assert f'{alarm_id}:1' in queued
    assert f'{alarm_id}:2' in queued


def test_queued_stage_delays_match_user_config(client, auth_headers, mock_redis):
    """Default delay is 30 s — stage 1 should be scheduled ≈30 s out,
    stage 2 ≈60 s out, both relative to trigger time."""
    before = time.time()
    resp = _trigger(client, auth_headers)
    after = time.time()
    alarm_id = resp.get_json()['id']

    members = dict(mock_redis.zrange(ESCALATION_QUEUE, 0, -1, withscores=True))
    stage1 = members[f'{alarm_id}:1']
    stage2 = members[f'{alarm_id}:2']

    assert before + 30 <= stage1 <= after + 30
    assert before + 60 <= stage2 <= after + 60


# ─── Worker drain behaviour ───────────────────────────────────────────────────

def test_drain_due_advances_escalation_stage(client, app, auth_headers, mock_redis):
    resp = _trigger(client, auth_headers)
    alarm_id = resp.get_json()['id']

    # Fast-forward: pull every queued item regardless of scheduled time.
    items = pop_due_items(now_ts=time.time() + 3600)
    assert f'{alarm_id}:1' in items
    assert f'{alarm_id}:2' in items

    # Re-enqueue at past-due timestamps so drain_due picks them up.
    mock_redis.zadd(ESCALATION_QUEUE, {item: time.time() - 1 for item in items})

    processed = drain_due(app)
    assert processed == 2

    # Final stage should now be 'community' (last of the default chain).
    refreshed = client.get(f'/api/v1/alarms/{alarm_id}', headers=auth_headers)
    assert refreshed.get_json()['escalation_stage'] == 'community'


def test_resolved_alarm_skips_pending_stages(
    client, app, auth_headers, mock_redis
):
    resp = _trigger(client, auth_headers)
    alarm_id = resp.get_json()['id']

    # User taps "Bin in Sicherheit" before stage 1 was due
    client.patch(f'/api/v1/alarms/{alarm_id}',
                 json={'status': 'resolved'}, headers=auth_headers)

    # Force the queued stages to be due
    items = pop_due_items(now_ts=time.time() + 3600)
    mock_redis.zadd(ESCALATION_QUEUE, {item: time.time() - 1 for item in items})
    drain_due(app)

    # Stage must not have advanced past whatever it was at resolve time
    refreshed = client.get(f'/api/v1/alarms/{alarm_id}', headers=auth_headers)
    assert refreshed.get_json()['escalation_stage'] == 'device_local'
    assert refreshed.get_json()['status'] == 'resolved'


# ─── User-configured chain ────────────────────────────────────────────────────

def test_custom_chain_first_stage_runs_inline(client, auth_headers, mock_redis):
    """Reordering to start with `community` means the inline stage is community."""
    client.patch('/api/v1/escalation', json={
        'escalation_order': ['community', 'contacts', 'device_local'],
        'delay_seconds_between_stages': 10,
    }, headers=auth_headers)

    resp = _trigger(client, auth_headers)
    assert resp.get_json()['escalation_stage'] == 'community'


def test_contacts_plus_community_stage_persists(
    client, app, auth_headers, mock_redis
):
    """`contacts+community` is a valid stage on the wire and the escalation_stage
    field after the worker runs."""
    client.patch('/api/v1/escalation', json={
        'escalation_order': ['device_local', 'contacts+community'],
        'delay_seconds_between_stages': 5,
    }, headers=auth_headers)

    resp = _trigger(client, auth_headers)
    alarm_id = resp.get_json()['id']

    # Pull queued items, re-enqueue overdue, drain
    items = pop_due_items(now_ts=time.time() + 3600)
    mock_redis.zadd(ESCALATION_QUEUE, {item: time.time() - 1 for item in items})
    drain_due(app)

    refreshed = client.get(f'/api/v1/alarms/{alarm_id}', headers=auth_headers)
    assert refreshed.get_json()['escalation_stage'] == 'contacts+community'


def test_short_chain_queues_nothing_extra(client, auth_headers, mock_redis):
    """A single-stage chain runs inline and leaves the queue empty."""
    client.patch('/api/v1/escalation', json={
        'escalation_order': ['device_local'],
    }, headers=auth_headers)

    resp = _trigger(client, auth_headers)
    alarm_id = resp.get_json()['id']

    members = mock_redis.zrange(ESCALATION_QUEUE, 0, -1)
    assert not any(m.startswith(alarm_id) for m in members)


# ─── Defensive: malformed queue items ─────────────────────────────────────────

def test_drain_handles_malformed_queue_member(app, mock_redis):
    """A corrupt member must not break the worker — just gets dropped."""
    mock_redis.zadd(ESCALATION_QUEUE, {'no-colon-here': time.time() - 1})
    processed = drain_due(app)
    assert processed == 1  # popped & swallowed without raising


def test_drain_handles_unknown_alarm_id(app, mock_redis):
    """Stage queued for an alarm that no longer exists must self-skip."""
    mock_redis.zadd(ESCALATION_QUEUE,
                    {'00000000-0000-0000-0000-000000000000:0': time.time() - 1})
    processed = drain_due(app)
    assert processed == 1  # popped & skipped silently
