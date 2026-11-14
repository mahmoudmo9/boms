"""Reference imports with a preview (v0.10.1 section 0.2): start → preview job → the owner confirms → import job.

Every step is recorded in ``ref.import_run``; the event stream carries its changes to the page. One import per
dataset at a time (a partial unique index). The uploaded file waits in ``<data folder>/imports/<run>/`` and is removed
when the run ends (done, failed, cancelled or discarded).
"""
from __future__ import annotations

import shutil
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.core.db import new_session
from app.core.errors import AppError, Conflict, NotFound
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.reference import bulk, importer
from app.modules.reference.models import DatasetImport, ImportRun
from app.modules.sourcing.common import jsonable
from app.modules.system import jobs

JOB = "reference.import"
OFFICIAL = ("unlocode", "elf")
ACTIVE = ("previewing", "importing")
MAX_BYTES = 200 * 1024 * 1024


def files_dir() -> Path:
    return get_config().data_dir / "imports"


def run_out(run: ImportRun) -> dict:
    return jsonable({"id": run.id, "dataset": run.dataset, "file_name": run.file_name, "release": run.release,
                     "status": run.status, "stage": run.stage, "rows_read": run.rows_read, "rows_total": run.rows_total,
                     "started_at": run.started_at, "preview": run.preview, "report": run.report, "error": run.error,
                     "cancel_requested": run.cancel_requested, "created_at": run.created_at, "updated_at": run.updated_at})


def get(db: Session, run_id) -> ImportRun:
    run = db.get(ImportRun, run_id)
    if run is None:
        raise NotFound("not_found", "Import not found")
    return run


def _busy(db: Session, dataset: str) -> ImportRun | None:
    return db.scalar(select(ImportRun).where(ImportRun.dataset == dataset, ImportRun.status.in_(ACTIVE)))


def start(db: Session, file_name: str, data: bytes, dataset_hint: str | None, actor: str | None, source: str) -> ImportRun:
    """Keep the file, recognise its format and queue the preview (nothing changes until the owner confirms)."""
    if len(data) > MAX_BYTES:
        raise AppError("file_too_large", "File is larger than the import limit", {"max_bytes": MAX_BYTES}, status=413)
    try:
        parts = bulk.file_parts(file_name, data)
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise AppError("reference_file_invalid", f"The file cannot be read: {exc}", status=422) from exc
    dataset = bulk.detect(parts)
    if dataset is None:
        raise AppError("reference_format_unknown", "This file is neither a UN/LOCODE release nor a GLEIF ELF code list",
                       {"chosen": dataset_hint}, status=422)
    if _busy(db, dataset) is not None:
        raise Conflict("reference_import_running", "An import of this dataset is already running", {"dataset": dataset})
    run = ImportRun(id=uuid.uuid4(), dataset=dataset, file_name=Path(file_name).name, file_path="", file_sha256=bulk.sha256(data),
                    release=bulk.release_from_name(file_name), status="previewing", stage="queued", actor=actor)
    folder = files_dir() / str(run.id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / Path(file_name).name
    path.write_bytes(data)
    run.file_path = str(path)
    db.add(run)
    db.flush()
    run.job_id = jobs.enqueue(db, JOB, {"run_id": str(run.id), "mode": "preview"}, source=source, actor=actor,
                              max_attempts=1).id
    if dataset_hint and dataset_hint != dataset:
        run.preview = {"chosen_other": dataset_hint}
    events.record(db, "reference_import", run.id, "start", {"dataset": dataset, "file": run.file_name}, source, actor=actor)
    db.flush()
    return run


def confirm(db: Session, run_id, release: str | None, actor: str | None, source: str) -> ImportRun:
    run = get(db, run_id)
    if run.status != "preview_ready":
        raise Conflict("reference_import_not_ready", "Only a finished preview can be imported", {"status": run.status})
    if _busy(db, run.dataset) is not None:
        raise Conflict("reference_import_running", "An import of this dataset is already running", {"dataset": run.dataset})
    if release:
        run.release = release
    run.status, run.stage, run.rows_read, run.cancel_requested, run.error = "importing", "queued", 0, False, None
    db.flush()
    run.job_id = jobs.enqueue(db, JOB, {"run_id": str(run.id), "mode": "import"}, source=source, actor=actor, max_attempts=1).id
    events.record(db, "reference_import", run.id, "confirm", {"dataset": run.dataset, "release": run.release}, source, actor=actor)
    db.flush()
    return run


def cancel(db: Session, run_id, actor: str | None, source: str) -> ImportRun:
    """«لغو»: a running preview or import stops at its next check and changes nothing; a finished preview is discarded."""
    run = get(db, run_id)
    if run.status in ACTIVE:
        run.cancel_requested = True
    elif run.status == "preview_ready":
        run.status = "discarded"
        _remove_file(run)
    else:
        raise Conflict("reference_import_finished", "This import has already ended", {"status": run.status})
    events.record(db, "reference_import", run.id, "cancel", {"dataset": run.dataset}, source, actor=actor)
    db.flush()
    return run


def _remove_file(run: ImportRun) -> None:
    if run.file_path:
        shutil.rmtree(Path(run.file_path).parent, ignore_errors=True)


def _set(run_id, **values) -> None:
    """Progress in its own short transaction, so the page sees it while the import's transaction is still open."""
    with new_session() as s:
        s.execute(update(ImportRun).where(ImportRun.id == run_id).values(**values, updated_at=text("now()")))
        s.commit()


def _cancelled(run_id) -> bool:
    with new_session() as s:
        return bool(s.scalar(select(ImportRun.cancel_requested).where(ImportRun.id == run_id)))


def run_job(db: Session, payload: dict) -> dict:
    """The job: ``mode`` preview (rolled back) or import (one transaction). It never raises, so a failure is not
    retried: the run records it and the data is as it was."""
    run_id = uuid.UUID(payload["run_id"])
    mode = payload.get("mode", "preview")
    run = db.get(ImportRun, run_id)
    if run is None:
        return {"skipped": "no such run"}
    dataset, release, path = run.dataset, run.release, Path(run.file_path)
    _set(run_id, stage="reading", started_at=clock.now(), rows_read=0)

    def progress(stage: str, n: int, total: int | None) -> None:
        values = {"stage": stage, "rows_read": n}
        if total is not None:
            values["rows_total"] = total
        _set(run_id, **values)

    cancelled = lambda: _cancelled(run_id)   # noqa: E731
    try:
        parts = bulk.file_parts(path.name, path.read_bytes())
        if mode == "preview":
            out = bulk.preview(db, dataset, parts, release, progress, cancelled)
            db.rollback()                                     # a dry run: only temporary tables were touched
            chosen = (run.preview or {}).get("chosen_other") if run.preview else None
            _set(run_id, status="preview_ready", stage="ready", preview=jsonable({**out, **({"chosen_other": chosen} if chosen else {})}),
                 rows_read=out["rows_read"], rows_total=out["rows_read"])
            return {"preview": {k: out[k] for k in ("insert", "update", "deactivate", "rejected")}}
        out = bulk.apply(db, dataset, parts, release, progress, cancelled)
        restored = importer.restore_archived(db)
        report = {**out, "source": "file", "restored_links": restored,
                  "rejections": out.get("examples", []), "notes": out.get("notes", {})}
        db.add(DatasetImport(dataset=dataset, release=release, source="file", file_sha256=run.file_sha256,
                             report=jsonable(report), imported_at=clock.now()))
        events.record(db, "reference", None, "import", jsonable({k: v for k, v in report.items()
                                                                  if k not in ("rejections", "examples", "notes")}),
                      "worker", actor=run.actor)
        db.execute(update(ImportRun).where(ImportRun.id == run_id).values(
            status="done", stage="done", report=jsonable(report), rows_read=out["rows_read"], updated_at=text("now()")))
        db.commit()
        _remove_file(run)
        return {"import": {k: out[k] for k in ("inserted", "updated", "deactivated", "seconds")}}
    except bulk.Cancelled:
        db.rollback()
        _set(run_id, status="cancelled", stage="cancelled")
        _remove_file(run)
        return {"cancelled": True}
    except Exception as exc:  # noqa: BLE001 - recorded on the run; the data is untouched (rolled back)
        db.rollback()
        _set(run_id, status="preview_failed" if mode == "preview" else "failed", stage="failed", error=str(exc)[:2000])
        if mode != "preview":
            _remove_file(run)
        return {"failed": str(exc)[:500]}


def run_sync(db: Session, dataset: str, path: Path, release: str | None) -> dict:
    """The command line and the shipped data path: preview and import in one go (no job, same set-based merge)."""
    parts = bulk.file_parts(path.name, path.read_bytes())
    detected = bulk.detect(parts)
    if detected != dataset:
        raise ValueError(f"{path.name} is not a {dataset} file" + (f" (it looks like {detected})" if detected else ""))
    return bulk.apply(db, dataset, parts, release or bulk.release_from_name(path.name))
