"""Job handlers of the system module."""

import uuid

from app.modules.system import backup
from app.worker.registry import job_handler


@job_handler("backup.run")
def run_backup(_db, payload: dict) -> dict:
    run_id = backup.run_backup(payload.get("kind", "manual"), source="worker")
    return {"backup_run_id": str(run_id)}


@job_handler("backup.restore_test")
def run_restore_test(_db, payload: dict) -> dict:
    run_id = uuid.UUID(payload["backup_run_id"]) if payload.get("backup_run_id") else None
    result = backup.restore_test(run_id, source="worker")
    return {"backup_run_id": result["backup_run_id"], "status": result["status"]}
