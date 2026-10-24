"""Public service for background jobs (``sys.job``).

Any module can enqueue a job. Handlers are registered by type in
``app.worker.registry`` from each module's ``handlers.py``.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.modules.events import service as events
from app.modules.system.models import Job

MAX_BACKOFF_SECONDS = 3600


def enqueue(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    *,
    run_after: datetime | None = None,
    max_attempts: int = 5,
    source: str = "api",
    actor: str | None = None,
) -> Job:
    job = Job(type=job_type, payload=payload or {}, max_attempts=max_attempts)
    if run_after is not None:
        job.run_after = run_after
    db.add(job)
    db.flush()
    events.record(db, "job", job.id, "enqueue", {"type": job_type, "payload": job.payload}, source, actor=actor)
    return job


def claim_next(db: Session) -> Job | None:
    """Atomically take the next due job. Safe with several concurrent workers."""
    row = db.execute(
        text(
            """
            UPDATE sys.job SET status = 'running', attempts = attempts + 1, locked_at = now()
            WHERE id = (
              SELECT id FROM sys.job
              WHERE status = 'queued' AND run_after <= now()
              ORDER BY run_after, id
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            RETURNING id
            """
        )
    ).scalar()
    db.commit()
    return db.get(Job, row) if row else None


def mark_done(db: Session, job_id: uuid.UUID, result: dict | None = None) -> None:
    job = db.get(Job, job_id)
    job.status = "done"
    job.finished_at = utcnow()
    job.last_error = None
    db.flush()
    events.record(db, "job", job.id, "done", {"type": job.type, "attempts": job.attempts, "result": result or {}},
                  "worker")


def mark_failed(db: Session, job_id: uuid.UUID, error: str, backoff_base: float) -> None:
    job = db.get(Job, job_id)
    job.last_error = error[-4000:]
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = utcnow()
        action = "failed"
    else:
        delay = min(backoff_base * 2 ** (job.attempts - 1), MAX_BACKOFF_SECONDS)
        job.status = "queued"
        job.locked_at = None
        job.run_after = utcnow() + timedelta(seconds=delay)
        action = "retry"
    db.flush()
    events.record(db, "job", job.id, action, {"type": job.type, "attempts": job.attempts,
                                              "error": error.strip().splitlines()[-1][:500] if error.strip() else ""},
                  "worker")


def requeue_stale(db: Session) -> int:
    """Return jobs left 'running' by a stopped worker to the queue (single-worker startup)."""
    result = db.execute(text("UPDATE sys.job SET status = 'queued', locked_at = NULL WHERE status = 'running'"))
    return result.rowcount


def counts(db: Session) -> dict[str, int]:
    rows = db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    result = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    result.update({status: n for status, n in rows})
    return result


def list_jobs(db: Session, status: str | None, page: int, page_size: int) -> tuple[list[Job], int]:
    query = select(Job)
    if status:
        query = query.where(Job.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return list(rows), total
