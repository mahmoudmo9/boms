"""System & Backup page API: health, backup history, run backup / restore test, jobs."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.schemas import ApiModel, Page, page_params
from app.core.web import request_source
from app.modules.system import health, jobs
from app.modules.system.auth import CurrentUser
from app.modules.system.models import BackupRun

router = APIRouter(prefix="/api/system", tags=["system"])
Db = Annotated[Session, Depends(get_db)]


class BackupRunOut(ApiModel):
    id: uuid.UUID
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    db_dump_path: str | None
    db_dump_sha256: str | None
    db_dump_bytes: int | None
    files_copied: int | None
    files_bytes: int | None
    secondary_status: str | None
    restore_test_at: datetime | None
    restore_test_status: str | None
    restore_test_details: dict[str, Any] | None
    details: dict[str, Any]


class JobOut(ApiModel):
    id: uuid.UUID
    type: str
    status: str
    attempts: int
    max_attempts: int
    run_after: datetime
    last_error: str | None
    created_at: datetime
    finished_at: datetime | None


class RestoreTestIn(BaseModel):
    backup_run_id: uuid.UUID | None = None


@router.get("/health")
def get_health(_: CurrentUser, db: Db):
    return health.summary(db)


@router.get("/backups", response_model=Page[BackupRunOut])
def list_backups(_: CurrentUser, db: Db, page: int = 1, page_size: Annotated[int, Query(le=200)] = 20):
    page, page_size = page_params(page, page_size, 200)
    total = db.scalar(select(func.count()).select_from(BackupRun)) or 0
    rows = db.scalars(select(BackupRun).order_by(BackupRun.started_at.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return Page(items=[BackupRunOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("/backups", status_code=202)
def backup_now(request: Request, user: CurrentUser, db: Db):
    job = jobs.enqueue(db, "backup.run", {"kind": "manual"}, max_attempts=1,
                       source=request_source(request), actor=user.username)
    db.commit()
    return {"job_id": str(job.id)}


@router.post("/restore-test", status_code=202)
def restore_test_now(body: RestoreTestIn, request: Request, user: CurrentUser, db: Db):
    payload = {"backup_run_id": str(body.backup_run_id)} if body.backup_run_id else {}
    job = jobs.enqueue(db, "backup.restore_test", payload, max_attempts=1,
                       source=request_source(request), actor=user.username)
    db.commit()
    return {"job_id": str(job.id)}


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(_: CurrentUser, db: Db, status: str | None = None, page: int = 1,
              page_size: Annotated[int, Query(le=200)] = 20):
    page, page_size = page_params(page, page_size, 200)
    rows, total = jobs.list_jobs(db, status, page, page_size)
    return Page(items=[JobOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, _: CurrentUser, db: Db):
    from app.core.errors import NotFound
    from app.modules.system.models import Job

    job = db.get(Job, job_id)
    if job is None:
        raise NotFound("not_found", "Job not found")
    return job
