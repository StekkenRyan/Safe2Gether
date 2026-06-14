"""Background scheduler for the alarm escalation chain.

Persistent Redis sorted set holds pending stage executions. Each worker
process spawns a daemon thread that polls the queue once per second and
atomically pops due items via a Lua script (so multi-worker deployments
don't double-execute).

Queue member format: ``"<alarm_id>:<stage_index>"`` — both are server-generated
and cannot collide.

Survival semantics: items live in Redis until popped, so an api restart
mid-escalation re-picks the backlog from where it left off. Resolved alarms
self-skip on the next poll because `_execute_item` checks `alarm.status`
before fanning out.
"""
import logging
import os
import threading
import time
from typing import Optional

import redis as redis_lib
from flask import Flask

from . import alarm as alarm_module
from .db import db
from .models import Alarm, User
from .redis_keys import ESCALATION_QUEUE

logger = logging.getLogger(__name__)

_POLL_INTERVAL_SECS = 1.0
_POP_BATCH_LIMIT = 100  # safety cap so a flooded queue can't block the loop


def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379/0'),
        socket_connect_timeout=2,
        decode_responses=True,
    )


def pop_due_items(now_ts: Optional[float] = None) -> list[str]:
    """Pop every queue item with score <= now_ts.

    Implemented as a `ZPOPMIN` loop because it's atomic per item and is
    supported by every Redis-compatible (including the fakeredis we use in
    tests). The worst-case interleaving with another worker is that one of
    them pops an item whose scheduled time is still in the future and pushes
    it back — idempotent at worst.
    """
    if now_ts is None:
        now_ts = time.time()
    items: list[str] = []
    try:
        r = _redis()
        for _ in range(_POP_BATCH_LIMIT):
            popped = r.zpopmin(ESCALATION_QUEUE, 1)
            if not popped:
                break
            member, score = popped[0]
            if score > now_ts:
                # Not due — restore and stop scanning (sorted-set order means
                # anything left has score >= this one).
                r.zadd(ESCALATION_QUEUE, {member: score})
                break
            items.append(member)
    except redis_lib.RedisError:
        logger.exception('escalation pop failed')
    return items


def execute_item(item: str) -> None:
    """Execute a single queued escalation item. Skips silently when the alarm
    is no longer active or the user has been deleted.
    """
    try:
        alarm_id, raw_index = item.split(':', 1)
        stage_index = int(raw_index)
    except (ValueError, AttributeError):
        logger.warning('escalation queue ignoring malformed item %r', item)
        return

    alarm = db.session.get(Alarm, alarm_id)
    if not alarm or alarm.status != 'active':
        return

    user = db.session.get(User, alarm.user_id)
    if not user:
        return

    # Re-derive the SAME stage list the trigger path used (chain + audience
    # override) so the queued stage_index maps to the intended stage. Using the
    # alarm's persisted audience is essential — see alarm.resolved_stages.
    stages = alarm_module.resolved_stages(user, alarm.audience)
    if stage_index >= len(stages):
        return

    stage = stages[stage_index]
    try:
        alarm_module.run_stage(alarm, user, stage)
    except Exception:
        logger.exception('escalation stage %s failed for alarm %s', stage, alarm_id)
        return

    alarm.escalation_stage = stage
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('escalation commit failed for alarm %s', alarm_id)


def drain_due(app: Flask) -> int:
    """Pop + execute every due item once. Returns how many were processed.
    Used by tests to advance the queue deterministically.
    """
    processed = 0
    with app.app_context():
        for item in pop_due_items():
            execute_item(item)
            processed += 1
    return processed


def _worker_loop(app: Flask) -> None:
    logger.info('escalation worker starting (poll=%.1fs)', _POLL_INTERVAL_SECS)
    while True:
        try:
            drain_due(app)
        except Exception:
            # Belt-and-suspenders: drain_due already swallows item-level errors,
            # but if anything bubbles, keep the loop alive.
            logger.exception('escalation worker iteration crashed')
        time.sleep(_POLL_INTERVAL_SECS)


def start_worker(app: Flask) -> None:
    """Spawn the daemon polling thread. No-op in TESTING mode — tests call
    `drain_due` explicitly instead.
    """
    if app.config.get('TESTING'):
        return
    thread = threading.Thread(target=_worker_loop, args=(app,), daemon=True,
                              name='escalation-worker')
    thread.start()
