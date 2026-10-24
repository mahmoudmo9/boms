"""Job runner: claims jobs from sys.job and runs their handlers."""

import logging
import traceback

from app.core.db import new_session
from app.modules.system import jobs
from app.worker.registry import HANDLERS

log = logging.getLogger("boms.worker")

# Retry delay = BACKOFF_BASE * 2 ** (attempt - 1) seconds, capped at one hour.
BACKOFF_BASE = 30.0


def run_one(backoff_base: float | None = None) -> bool:
    """Run one due job. Returns False when the queue has nothing due."""
    with new_session() as db:
        job = jobs.claim_next(db)
        if job is None:
            return False
        job_id, job_type, payload = job.id, job.type, dict(job.payload)

    log.info("running job %s (%s)", job_id, job_type)
    with new_session() as db:
        try:
            handler = HANDLERS.get(job_type)
            if handler is None:
                raise LookupError(f"no handler registered for job type {job_type!r}")
            result = handler(db, payload)
            jobs.mark_done(db, job_id, result)
            db.commit()
        except Exception:
            db.rollback()
            error = traceback.format_exc()
            log.warning("job %s (%s) failed: %s", job_id, job_type, error.strip().splitlines()[-1])
            jobs.mark_failed(db, job_id, error, BACKOFF_BASE if backoff_base is None else backoff_base)
            db.commit()
    return True


def run_until_idle(max_jobs: int | None = None, backoff_base: float | None = None) -> int:
    count = 0
    while (max_jobs is None or count < max_jobs) and run_one(backoff_base):
        count += 1
    return count
