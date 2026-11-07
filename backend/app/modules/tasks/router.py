"""Tasks API (v0.8.0): «کارهای من» (grouped overdue / today / this week / later / done), the case's tasks, manual
tasks, done / move / cancel / reopen."""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from app.modules.parties import clock
from app.modules.system.auth import CurrentUser
from app.modules.tasks import service
from app.modules.tasks.schemas import CancelIn, DoneIn, MoveIn, TaskIn, TaskPatch

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api", tags=["tasks"])


def _titles(db: Session, rows) -> dict:
    from app.modules.sourcing.models import Case

    ids = {r.case_id for r in rows if r.case_id}
    return {c.id: c.title for c in db.scalars(select(Case).where(Case.id.in_(ids)))} if ids else {}


@router.get("/tasks")
def list_tasks(_: CurrentUser, db: Db, case_id: uuid.UUID | None = None, kind: str | None = None, q: str | None = None,
               include_done: bool = True):
    """Open tasks grouped by when they are due, plus the last 50 done or cancelled ones."""
    open_rows = service.list_tasks(db, case_id=case_id, kind=kind, status="open", q=q)
    done_rows = service.list_tasks(db, case_id=case_id, kind=kind, status="closed", q=q, limit=50) if include_done else []
    titles = _titles(db, open_rows + done_rows)
    groups = service.buckets(open_rows + done_rows, clock.today())
    return {"today": clock.today().isoformat(),
            "groups": {k: [service.task_out(r, titles) for r in v] for k, v in groups.items()},
            "counts": {k: len(v) for k, v in groups.items()}, "kinds": list(service.KINDS)}


@router.get("/cases/{case_id}/tasks")
def case_tasks(case_id: uuid.UUID, _: CurrentUser, db: Db, status: Literal["open", "closed", "all"] = "open"):
    rows = service.list_tasks(db, case_id=case_id, status=None if status == "all" else status)
    return [service.task_out(r) for r in rows]


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, request: Request, user: CurrentUser, db: Db):
    row = service.create(db, {**body.model_dump(), "source": "manual", "source_kind": "manual"}, request_source(request),
                         user.username)
    db.commit()
    return service.task_out(row)


@router.patch("/tasks/{task_id}")
def patch_task(task_id: uuid.UUID, body: TaskPatch, request: Request, user: CurrentUser, db: Db):
    row = service.update(db, task_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return service.task_out(row)


@router.post("/tasks/{task_id}/done")
def done_task(task_id: uuid.UUID, request: Request, user: CurrentUser, db: Db, body: DoneIn | None = None):
    row = service.done(db, task_id, body.note if body else None, request_source(request), user.username)
    db.commit()
    return service.task_out(row)


@router.post("/tasks/{task_id}/move")
def move_task(task_id: uuid.UUID, body: MoveIn, request: Request, user: CurrentUser, db: Db):
    row = service.move(db, task_id, body.due_on, body.note, request_source(request), user.username)
    db.commit()
    return service.task_out(row)


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: uuid.UUID, body: CancelIn, request: Request, user: CurrentUser, db: Db):
    row = service.cancel(db, task_id, body.note, request_source(request), user.username)
    db.commit()
    return service.task_out(row)


@router.post("/tasks/{task_id}/reopen")
def reopen_task(task_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    row = service.reopen(db, task_id, request_source(request), user.username)
    db.commit()
    return service.task_out(row)


ROUTERS = [router]
