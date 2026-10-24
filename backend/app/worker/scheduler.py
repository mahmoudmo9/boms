"""Scheduler that runs inside the worker.

Each schedule computes its most recent due time (in the PC's local time zone).
If the last enqueue is older than that, the job is enqueued once. A run missed
while the PC was off therefore happens once at the next worker start.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.system import jobs, settings

log = logging.getLogger("boms.worker")

SCHEDULER_LOCK = 7_345_001  # pg advisory lock key


def _backup_time(db: Session) -> tuple[int, int]:
    hour, minute = settings.get(db, "backup.time").split(":")
    return int(hour), int(minute)


def nightly_due(db: Session, now: datetime) -> datetime:
    hour, minute = _backup_time(db)
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return due if due <= now else due - timedelta(days=1)


def monthly_due(db: Session, now: datetime) -> datetime:
    """First day of the month, one hour after the backup time."""
    hour, minute = _backup_time(db)
    due = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0) + timedelta(hours=1)
    if due > now:
        previous = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        due = previous.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(hours=1)
    return due


@dataclass(frozen=True)
class Schedule:
    name: str
    job_type: str
    payload: dict
    due: Callable[[Session, datetime], datetime]
    max_attempts: int = 2


SCHEDULES = [
    Schedule("backup_nightly", "backup.run", {"kind": "nightly"}, nightly_due),
    Schedule("restore_test_monthly", "backup.restore_test", {}, monthly_due),
]


def tick(db: Session, now: datetime) -> list[str]:
    """Enqueue every schedule that is due. ``now`` must be timezone-aware local time."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SCHEDULER_LOCK})
    enqueued = []
    for schedule in SCHEDULES:
        key = f"scheduler.{schedule.name}"
        due = schedule.due(db, now)
        last = settings.get_internal(db, key)
        if last is not None and datetime.fromisoformat(last) >= due:
            continue
        jobs.enqueue(db, schedule.job_type, schedule.payload, max_attempts=schedule.max_attempts,
                     source="worker", actor="scheduler")
        settings.set_internal(db, key, now.isoformat())
        enqueued.append(schedule.name)
        log.info("scheduled %s (due %s)", schedule.name, due.isoformat())
    db.commit()
    return enqueued
