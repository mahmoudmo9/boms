import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.schemas import ApiModel, Page, page_params
from app.core.web import request_source
from app.modules.documents import service
from app.modules.documents.filetypes import INLINE_TYPES
from app.modules.system.auth import CurrentUser

router = APIRouter(prefix="/api/documents", tags=["documents"])
Db = Annotated[Session, Depends(get_db)]
Language = Literal["fa", "en", "other"]


class DocumentOut(ApiModel):
    id: uuid.UUID
    sha256: str
    original_filename: str
    mime_type: str
    size_bytes: int
    title: str
    notes: str | None
    language: str | None
    text_status: str
    source: str
    uploaded_at: datetime
    updated_at: datetime


class LinkOut(ApiModel):
    id: uuid.UUID
    entity_type: str
    entity_id: str
    role: str
    created_at: datetime


class DocumentDetail(DocumentOut):
    links: list[LinkOut]
    previewable: bool


class DocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=20000)
    language: Language | None = None


class LinkIn(BaseModel):
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_.]{0,63}$")
    entity_id: str = Field(min_length=1, max_length=200)
    role: str = Field(default="attachment", pattern=r"^[a-z][a-z0-9_]{0,63}$")


def _detail(db: Session, doc) -> DocumentDetail:
    base = DocumentOut.model_validate(doc).model_dump()
    return DocumentDetail(**base, links=[LinkOut.model_validate(x) for x in service.links(db, doc.id)],
                          previewable=doc.mime_type in INLINE_TYPES)


@router.post("", status_code=201, response_model=DocumentDetail)
def upload(request: Request, user: CurrentUser, db: Db, file: Annotated[UploadFile, File()],
           title: Annotated[str | None, Form(max_length=500)] = None,
           notes: Annotated[str | None, Form(max_length=20000)] = None,
           language: Annotated[Language | None, Form()] = None):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > service.max_upload_bytes(db) + 1024 * 1024:
        raise AppError("file_too_large", "File is larger than the upload limit",
                       {"max_bytes": service.max_upload_bytes(db)}, status=413)
    doc = service.upload(db, file.file, file.filename or "file", title=title, notes=notes, language=language,
                         source=request_source(request), actor=user.username)
    db.commit()
    return _detail(db, doc)


@router.get("", response_model=Page[DocumentOut])
def list_documents(_: CurrentUser, db: Db, q: str | None = None, mime: str | None = None,
                   entity_type: str | None = None, entity_id: str | None = None,
                   sort: Literal["uploaded_at", "title", "size_bytes", "original_filename"] = "uploaded_at",
                   order: Literal["asc", "desc"] = "desc", page: int = 1,
                   page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    rows, total = service.list_documents(db, q=q, mime=mime, entity_type=entity_type, entity_id=entity_id,
                                         sort=sort, order=order, page=page, page_size=page_size)
    return Page(items=[DocumentOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, _: CurrentUser, db: Db):
    return _detail(db, service.get(db, document_id))


@router.patch("/{document_id}", response_model=DocumentDetail)
def update_document(document_id: uuid.UUID, body: DocumentPatch, request: Request, user: CurrentUser, db: Db):
    changes = body.model_dump(exclude_unset=True)
    if "title" in changes and not changes["title"]:
        changes.pop("title")
    doc = service.update(db, document_id, changes, request_source(request), actor=user.username)
    db.commit()
    return _detail(db, doc)


@router.get("/{document_id}/download")
def download(document_id: uuid.UUID, _: CurrentUser, db: Db):
    doc = service.get(db, document_id)
    return FileResponse(service.file_path(doc), media_type="application/octet-stream",
                        filename=doc.original_filename)


@router.get("/{document_id}/preview")
def preview(document_id: uuid.UUID, _: CurrentUser, db: Db):
    doc = service.get(db, document_id)
    if doc.mime_type not in INLINE_TYPES:
        raise AppError("not_previewable", "This file type cannot be previewed", status=415)
    return FileResponse(service.file_path(doc), media_type=doc.mime_type, filename=doc.original_filename,
                        content_disposition_type="inline")


@router.post("/{document_id}/links", status_code=201, response_model=LinkOut)
def add_link(document_id: uuid.UUID, body: LinkIn, request: Request, user: CurrentUser, db: Db):
    row = service.link(db, document_id, body.entity_type, body.entity_id, body.role,
                       source=request_source(request), actor=user.username)
    db.commit()
    return row


@router.delete("/{document_id}/links/{link_id}", status_code=204)
def remove_link(document_id: uuid.UUID, link_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.unlink(db, document_id, link_id, source=request_source(request), actor=user.username)
    db.commit()
