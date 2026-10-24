"""Worker heartbeat and the System page health summary."""

import json
import os
import shutil
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.core.time import utcnow
from app.modules.system import jobs
from app.modules.system.models import BackupRun

HEARTBEAT_STALE_SECONDS = 60


def _heartbeat_path():
    return get_config().logs_dir / "worker.heartbeat"


def write_heartbeat() -> None:
    path = _heartbeat_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"at": utcnow().isoformat(), "pid": os.getpid()}), encoding="utf-8")
    tmp.replace(path)


def read_heartbeat() -> datetime | None:
    try:
        return datetime.fromisoformat(json.loads(_heartbeat_path().read_text(encoding="utf-8"))["at"])
    except (OSError, ValueError, KeyError):
        return None


def _run_summary(run: BackupRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": str(run.id), "kind": run.kind, "status": run.status,
        "started_at": run.started_at.isoformat(), "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "db_dump_bytes": run.db_dump_bytes, "secondary_status": run.secondary_status,
        "restore_test_at": run.restore_test_at.isoformat() if run.restore_test_at else None,
        "restore_test_status": run.restore_test_status,
    }


def summary(db: Session) -> dict:
    config = get_config()
    last_seen = read_heartbeat()
    try:
        usage = shutil.disk_usage(config.data_dir)
        disk = {"path": str(config.data_dir), "free_bytes": usage.free, "total_bytes": usage.total}
    except OSError:
        disk = {"path": str(config.data_dir), "free_bytes": None, "total_bytes": None}
    last_backup = db.scalar(select(BackupRun).order_by(BackupRun.started_at.desc()).limit(1))
    last_success = db.scalar(select(BackupRun).where(BackupRun.status == "succeeded")
                             .order_by(BackupRun.started_at.desc()).limit(1))
    last_restore = db.scalar(select(BackupRun).where(BackupRun.restore_test_at.is_not(None))
                             .order_by(BackupRun.restore_test_at.desc()).limit(1))
    return {
        "worker": {
            "last_seen": last_seen.isoformat() if last_seen else None,
            "alive": bool(last_seen and (utcnow() - last_seen).total_seconds() < HEARTBEAT_STALE_SECONDS),
        },
        "jobs": jobs.counts(db),
        "disk": disk,
        "last_backup": _run_summary(last_backup),
        "last_successful_backup": _run_summary(last_success),
        "last_restore_test": _run_summary(last_restore),
    }
