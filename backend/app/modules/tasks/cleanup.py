"""Case cascade delete (test data): the case's tasks are deleted (events and audit keep them)."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.sourcing.common import flush, row_snapshot
from app.modules.tasks.models import Task


def cleanup_case(db: Session, case_id: uuid.UUID, note: str, source: str, actor: str | None) -> dict:
    rows = list(db.scalars(select(Task).where(Task.case_id == case_id)))
    snapshot = [row_snapshot(r) for r in rows]
    for r in rows:
        db.delete(r)
    flush(db, "in_use")
    return {"counts": {"tasks": len(rows)} if rows else {}, "rows": snapshot}
