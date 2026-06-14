"""Dedicated background-worker process entrypoint.

Runs the escalation + Dead-Man's-Switch timer loops in ONE plain-Python process
so they are:
  • not duplicated across the gunicorn web workers (which caused double timer
    notifications under ``-w 2``), and
  • not executed inside the web worker class (no eventlet/greenlet vs. blocking
    psycopg2 hazard).

Run it as a separate service:  ``python -m app.worker``
The web tier is started with ``RUN_WORKERS=0`` so only this process owns the
loops. The atomic timer transitions (see ``timer_worker._claim_timer``) keep
escalation correct even if this is ever accidentally run more than once.
"""
import logging
import os
import threading

from . import create_app
from .escalation_worker import _worker_loop as _escalation_loop
from .timer_worker import _worker_loop as _timer_loop

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # This process owns the worker loops, so make sure create_app does not ALSO
    # spawn its in-process worker threads. Read at create_app() call-time.
    os.environ['RUN_WORKERS'] = '0'
    app = create_app()

    # Timer loop on a daemon thread; escalation loop owns the main thread.
    threading.Thread(target=_timer_loop, args=(app,), daemon=True,
                     name='timer-worker').start()
    logger.info('worker process started (escalation + timer)')
    _escalation_loop(app)


if __name__ == '__main__':
    main()
