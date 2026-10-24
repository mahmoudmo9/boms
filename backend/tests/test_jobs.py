import threading
import time
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select, text

from app.core.db import new_session
from app.modules.system import jobs
from app.modules.system.models import Job, Setting
from app.worker import runner, scheduler
from app.worker.registry import HANDLERS, job_handler


@pytest.fixture
def clean_queue():
    """Keep unrelated queued jobs from interfering; restore nothing (jobs are test data)."""
    with new_session() as db:
        db.execute(text("UPDATE sys.job SET status = 'done' WHERE status IN ('queued', 'running')"))
        db.commit()
    yield
    with new_session() as db:
        db.execute(text("UPDATE sys.job SET status = 'done' WHERE status IN ('queued', 'running')"))
        db.commit()


def _enqueue(job_type, payload=None, max_attempts=5):
    with new_session() as db:
        job = jobs.enqueue(db, job_type, payload or {}, max_attempts=max_attempts, source="script")
        db.commit()
        return job.id


def _job(job_id) -> Job:
    with new_session() as db:
        return db.get(Job, job_id)


def test_fails_twice_then_succeeds(clean_queue):
    calls = Counter()

    @job_handler("test.flaky")
    def flaky(db, payload):
        calls[payload["key"]] += 1
        if calls[payload["key"]] < 3:
            raise RuntimeError(f"boom {calls[payload['key']]}")
        return {"ok": True}

    job_id = _enqueue("test.flaky", {"key": "a"})
    runner.run_until_idle(backoff_base=0)
    job = _job(job_id)
    assert (job.status, job.attempts, job.last_error) == ("done", 3, None)
    with new_session() as db:
        actions = db.execute(text("SELECT action FROM core.event WHERE entity_type = 'job' AND entity_id = :i "
                                  "ORDER BY id"), {"i": str(job_id)}).scalars().all()
    assert actions == ["enqueue", "retry", "retry", "done"]


def test_exponential_backoff(clean_queue):
    @job_handler("test.always_fails")
    def always(db, payload):
        raise ValueError("nope")

    job_id = _enqueue("test.always_fails", max_attempts=3)
    before = datetime.now().astimezone()
    runner.run_one(backoff_base=10)
    job = _job(job_id)
    assert job.status == "queued" and job.attempts == 1
    assert timedelta(seconds=9) < job.run_after - before < timedelta(seconds=12)
    assert runner.run_one(backoff_base=10) is False  # not due yet
    with new_session() as db:
        db.execute(text("UPDATE sys.job SET run_after = now() WHERE id = :i"), {"i": job_id})
        db.commit()
    runner.run_one(backoff_base=10)
    job = _job(job_id)
    assert job.attempts == 2
    assert timedelta(seconds=19) < job.run_after - datetime.now().astimezone() < timedelta(seconds=21)


def test_gives_up_after_max_attempts(clean_queue):
    @job_handler("test.broken")
    def broken(db, payload):
        db.execute(text("INSERT INTO sys.setting (key, value) VALUES ('test.never', '1')"))
        raise ValueError("permanent failure")

    job_id = _enqueue("test.broken", max_attempts=2)
    runner.run_until_idle(backoff_base=0)
    job = _job(job_id)
    assert job.status == "failed" and job.attempts == 2 and "permanent failure" in job.last_error
    with new_session() as db:
        assert db.get(Setting, "test.never") is None  # handler writes rolled back


def test_unknown_job_type_fails(clean_queue):
    job_id = _enqueue("test.no_such_handler", max_attempts=1)
    runner.run_until_idle(backoff_base=0)
    job = _job(job_id)
    assert job.status == "failed" and "no handler" in job.last_error


def test_concurrent_workers_never_run_a_job_twice(clean_queue):
    seen = []
    lock = threading.Lock()

    @job_handler("test.count")
    def count(db, payload):
        time.sleep(0.005)
        with lock:
            seen.append(payload["n"])

    ids = [_enqueue("test.count", {"n": n}) for n in range(60)]
    threads = [threading.Thread(target=runner.run_until_idle) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(seen) == list(range(60))
    with new_session() as db:
        rows = db.execute(select(Job.status, Job.attempts).where(Job.id.in_(ids))).all()
    assert all(r == ("done", 1) for r in rows)


def test_requeue_stale(clean_queue):
    job_id = _enqueue("test.count", {"n": -1})
    with new_session() as db:
        db.execute(text("UPDATE sys.job SET status = 'running' WHERE id = :i"), {"i": job_id})
        assert jobs.requeue_stale(db) >= 1
        db.commit()
    assert _job(job_id).status == "queued"


TZ = ZoneInfo("Asia/Tehran")


@pytest.fixture
def fresh_scheduler(clean_queue):
    with new_session() as db:
        db.execute(delete(Setting).where(Setting.key.like("scheduler.%")))
        db.commit()
    yield
    with new_session() as db:
        db.execute(delete(Setting).where(Setting.key.like("scheduler.%")))
        db.execute(text("UPDATE sys.job SET status = 'done' WHERE status = 'queued'"))
        db.commit()


def _tick(at: datetime) -> list[str]:
    with new_session() as db:
        return scheduler.tick(db, at)


def test_due_time_calculation():
    with new_session() as db:
        assert scheduler.nightly_due(db, datetime(2026, 10, 24, 1, 0, tzinfo=TZ)) == datetime(2026, 10, 23, 2, 0, tzinfo=TZ)
        assert scheduler.nightly_due(db, datetime(2026, 10, 24, 2, 0, tzinfo=TZ)) == datetime(2026, 10, 24, 2, 0, tzinfo=TZ)
        assert scheduler.monthly_due(db, datetime(2026, 10, 24, 1, 0, tzinfo=TZ)) == datetime(2026, 10, 1, 3, 0, tzinfo=TZ)
        assert scheduler.monthly_due(db, datetime(2026, 10, 1, 2, 59, tzinfo=TZ)) == datetime(2026, 9, 1, 3, 0, tzinfo=TZ)
        assert scheduler.monthly_due(db, datetime(2026, 1, 1, 0, 0, tzinfo=TZ)) == datetime(2025, 12, 1, 3, 0, tzinfo=TZ)


def test_scheduler_runs_each_due_slot_once_and_catches_up(fresh_scheduler):
    # first start ever: both are "missed", each enqueued once
    assert _tick(datetime(2026, 10, 24, 10, 0, tzinfo=TZ)) == ["backup_nightly", "restore_test_monthly"]
    assert _tick(datetime(2026, 10, 24, 10, 0, 5, tzinfo=TZ)) == []
    assert _tick(datetime(2026, 10, 25, 1, 59, tzinfo=TZ)) == []
    assert _tick(datetime(2026, 10, 25, 2, 0, tzinfo=TZ)) == ["backup_nightly"]
    assert _tick(datetime(2026, 10, 25, 2, 1, tzinfo=TZ)) == []
    # PC off for three days: one catch-up run at the next start, not three
    assert _tick(datetime(2026, 10, 28, 9, 0, tzinfo=TZ)) == ["backup_nightly"]
    assert _tick(datetime(2026, 10, 28, 9, 1, tzinfo=TZ)) == []
    # new month
    assert _tick(datetime(2026, 11, 1, 3, 0, tzinfo=TZ)) == ["backup_nightly", "restore_test_monthly"]
    with new_session() as db:
        queued = db.execute(select(Job.type).where(Job.status == "queued")).scalars().all()
    assert Counter(queued) == {"backup.run": 4, "backup.restore_test": 2}


def test_backup_time_setting_is_used(client, fresh_scheduler):
    client.patch("/api/settings", json={"backup.time": "23:30"})
    try:
        with new_session() as db:
            assert scheduler.nightly_due(db, datetime(2026, 10, 24, 23, 0, tzinfo=TZ)) == \
                datetime(2026, 10, 23, 23, 30, tzinfo=TZ)
    finally:
        client.patch("/api/settings", json={"backup.time": "02:00"})


def test_handlers_registered_from_modules():
    from app.worker.registry import load_handlers

    assert {"backup.run", "backup.restore_test", "documents.extract_text"} <= set(load_handlers())
    assert HANDLERS
