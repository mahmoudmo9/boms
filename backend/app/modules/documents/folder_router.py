"""Folder view API (v0.9.0 section 6.1): status for Settings, sync now, «باز کردن پوشه» (local only)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.modules.documents import folders
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api", tags=["folders"])
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def _local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise AppError("local_only", "Folders open only on the PC that runs BOMS", status=403)


def _open(path) -> dict:
    return {"path": str(path), "exists": path.exists(), "opened": folders.open_in_explorer(path)}


@router.get("/folders/status")
def folder_status(_: CurrentUser, db: Db):
    return folders.status(db)


@router.post("/folders/sync")
def folder_sync(_: CurrentUser, db: Db):
    report = folders.sync(db)
    db.commit()
    return report


@router.post("/cases/{case_id}/folder/open")
def open_case_folder(case_id: uuid.UUID, request: Request, _: CurrentUser, db: Db):
    _local(request)
    path = folders.case_folder(db, case_id)
    if not path.exists():
        folders.sync(db, [case_id])
        db.commit()
    return _open(path)


@router.post("/documents/{document_id}/folder/open")
def open_document_folder(document_id: uuid.UUID, request: Request, _: CurrentUser, db: Db):
    _local(request)
    cases = folders.cases_of_document(db, document_id)
    if not cases:
        raise AppError("not_in_a_case", "The document is not linked to a case", status=409)
    path = folders.case_folder(db, cases[0])
    if not path.exists():
        folders.sync(db, [cases[0]])
        db.commit()
    return _open(path)


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Annotated[str | None, Field(max_length=300)] = None
    code: Annotated[str | None, Field(max_length=80)] = None
    verification_code: Annotated[str | None, Field(max_length=20)] = None


@router.post("/verify-document")
def verify_document(body: VerifyIn, _: CurrentUser, db: Db):
    """«تأیید سند»: the QR text, or the code and verification code typed; the record and its current status."""
    from app.modules.documents import control

    return control.verify(db, body.text, code=body.code, vc=body.verification_code)


ROUTERS = [router]
