"""Worker process: ``python -m app.worker``.

Loop: write heartbeat, run the scheduler, run due jobs, sleep.
Only one worker may run; a PostgreSQL advisory lock enforces it.
"""

import logging
import signal
import sys
import time

from sqlalchemy import text

from app.core.db import get_engine, new_session
from app.core.logs import setup_logging
from app.core.time import local_now
from app.modules.system import health, jobs
from app.worker import runner, scheduler
from app.worker.registry import load_handlers

log = logging.getLogger("boms.worker")

WORKER_LOCK = 7_345_000
POLL_SECONDS = 2.0

_stop = False


def _request_stop(*_):
    global _stop
    _stop = True


def main() -> int:
    setup_logging("worker")
    handlers = load_handlers()
    log.info("worker starting; handlers: %s", ", ".join(sorted(handlers)))

    lock_conn = get_engine().connect()
    if not lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": WORKER_LOCK}).scalar():
        log.error("another worker is already running")
        return 1

    with new_session() as db:
        if n := jobs.requeue_stale(db):
            log.info("requeued %d job(s) left running by a previous worker", n)
        db.commit()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    while not _stop:
        try:
            health.write_heartbeat()
            with new_session() as db:
                scheduler.tick(db, local_now())
            runner.run_until_idle(max_jobs=20)
        except Exception:
            log.exception("worker loop error")
        time.sleep(POLL_SECONDS)
    log.info("worker stopped")
    lock_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
