"""Public service of the documents module."""

import hashlib
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import Select, and_, func, literal_column, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.core.errors import AppError, Conflict, NotFound
from app.core.files import CHUNK, make_read_only, sha256_file, store_relpath
from app.core.text import WORD_SIMILARITY, normalize_fa
from app.modules.documents.filetypes import blocked_reason, detect_mime
from app.modules.documents.models import Document, DocumentLink
from app.modules.events import service as events
from app.modules.system import jobs, settings

SORTS = {"uploaded_at": Document.uploaded_at, "title": Document.title, "size_bytes": Document.size_bytes,
         "original_filename": Document.original_filename}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def max_upload_bytes(db: Session) -> int:
    return int(settings.get(db, "upload.max_mb")) * 1024 * 1024


def clean_filename(name: str) -> str:
    name = _CONTROL.sub("", Path(name.replace("\\", "/")).name).strip()
    return name[:255] or "file"


def _receive(stream: BinaryIO, max_bytes: int) -> tuple[Path, str, int]:
    """Stream the upload to a temporary file, hashing as it goes."""
    incoming = get_config().files_dir / ".incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    tmp = incoming / f"{uuid.uuid4().hex}.part"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise AppError("file_too_large", "File is larger than the upload limit",
                                   {"max_bytes": max_bytes}, status=413)
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, digest.hexdigest(), size


def _duplicate(db: Session, sha: str) -> Conflict | None:
    existing = db.scalar(select(Document).where(Document.sha256 == sha))
    if existing is None:
        return None
    return Conflict("duplicate_document", "This document is already registered",
                    {"id": str(existing.id), "title": existing.title})


def _place(tmp: Path, sha: str) -> str:
    relpath = store_relpath(sha)
    dest = get_config().files_dir / relpath
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and sha256_file(dest) == sha:
        tmp.unlink()  # left over from an earlier attempt; same content
    else:
        if dest.exists():
            dest.chmod(0o600)
        tmp.replace(dest)
        make_read_only(dest)
    return relpath


def upload(db: Session, stream: BinaryIO, filename: str, *, title: str | None = None, notes: str | None = None,
           language: str | None = None, source: str = "api", actor: str | None = None) -> Document:
    filename = clean_filename(filename)
    tmp, sha, size = _receive(stream, max_upload_bytes(db))
    try:
        reason = blocked_reason(filename, tmp)
        if reason:
            raise AppError("blocked_file_type", f"File type not allowed ({reason})", {"reason": reason}, status=415)
        if conflict := _duplicate(db, sha):
            raise conflict
        mime = detect_mime(filename, tmp)
        relpath = _place(tmp, sha)
    finally:
        tmp.unlink(missing_ok=True)

    doc = Document(
        sha256=sha, original_filename=filename, mime_type=mime, size_bytes=size, storage_relpath=relpath,
        title=(title or "").strip() or Path(filename).stem or filename, notes=notes or None, language=language,
        text_status="pending" if mime == "application/pdf" else "none", source=source,
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if conflict := _duplicate(db, sha):
            raise conflict from None
        raise
    events.record(db, "document", doc.id, "create",
                  {"title": doc.title, "filename": filename, "sha256": sha, "bytes": size}, source, actor=actor)
    if doc.text_status == "pending":
        jobs.enqueue(db, "documents.extract_text", {"document_id": str(doc.id)}, max_attempts=3,
                     source=source, actor=actor)
    return doc


def get(db: Session, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise NotFound("not_found", "Document not found")
    return doc


def file_path(doc: Document) -> Path:
    path = get_config().files_dir / doc.storage_relpath
    if not path.is_file():
        raise NotFound("file_missing", "The stored file is missing")
    return path


def update(db: Session, document_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Document:
    doc = get(db, document_id)
    diff = {}
    for field in ("title", "notes", "language"):
        if field in changes and getattr(doc, field) != changes[field]:
            diff[field] = {"old": getattr(doc, field), "new": changes[field]}
            setattr(doc, field, changes[field])
    if diff:
        db.flush()
        events.record(db, "document", doc.id, "update", {"changes": diff}, source, actor=actor)
    return doc


def match_condition(q: str):
    """Full-text (prefix) OR fuzzy trigram match on title/filename. ``q`` is raw user input."""
    needle = normalize_fa(q) or ""
    tokens = re.findall(r"\w+", needle)
    conditions = []
    if tokens:
        tsquery = " & ".join(f"{t}:*" for t in tokens)
        conditions.append(text("core.document.search_vector @@ to_tsquery('simple', :tsq)").bindparams(tsq=tsquery))
    if needle:
        conditions.append(
            text("core.normalize_fa(core.document.title || ' ' || core.document.original_filename) %> :needle")
            .bindparams(needle=needle)
        )
    return or_(*conditions) if conditions else None


def set_similarity_threshold(db: Session) -> None:
    db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"),
               {"v": str(WORD_SIMILARITY)})


def rank_expression(q: str):
    needle = normalize_fa(q) or ""
    tokens = re.findall(r"\w+", needle)
    tsquery = " & ".join(f"{t}:*" for t in tokens) or "''"
    name = func.core.normalize_fa(Document.title + " " + Document.original_filename)
    return func.greatest(
        func.ts_rank(literal_column("core.document.search_vector"), func.to_tsquery("simple", tsquery)),
        func.word_similarity(needle, name),
    )


def list_documents(db: Session, *, q: str | None = None, mime: str | None = None, entity_type: str | None = None,
                   entity_id: str | None = None, sort: str = "uploaded_at", order: str = "desc",
                   page: int = 1, page_size: int = 50) -> tuple[list[Document], int]:
    query: Select = select(Document)
    if q and (cond := match_condition(q)) is not None:
        set_similarity_threshold(db)
        query = query.where(cond)
    if mime:
        query = query.where(Document.mime_type.startswith(mime))
    if entity_type:
        link = select(DocumentLink.document_id).where(DocumentLink.entity_type == entity_type)
        if entity_id:
            link = link.where(DocumentLink.entity_id == entity_id)
        query = query.where(Document.id.in_(link))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    column = SORTS.get(sort, Document.uploaded_at)
    ordering = column.asc() if order == "asc" else column.desc()
    rows = db.scalars(query.order_by(ordering, Document.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return list(rows), total


def links(db: Session, document_id: uuid.UUID) -> list[DocumentLink]:
    return list(db.scalars(select(DocumentLink).where(DocumentLink.document_id == document_id)
                           .order_by(DocumentLink.created_at)))


def link(db: Session, document_id: uuid.UUID, entity_type: str, entity_id: str, role: str = "attachment",
         source: str = "api", actor: str | None = None) -> DocumentLink:
    get(db, document_id)
    existing = db.scalar(select(DocumentLink).where(and_(
        DocumentLink.document_id == document_id, DocumentLink.entity_type == entity_type,
        DocumentLink.entity_id == entity_id, DocumentLink.role == role)))
    if existing is not None:
        return existing
    row = DocumentLink(document_id=document_id, entity_type=entity_type, entity_id=entity_id, role=role)
    db.add(row)
    db.flush()
    events.record(db, "document", document_id, "link",
                  {"entity_type": entity_type, "entity_id": entity_id, "role": role}, source, actor=actor)
    return row


def unlink(db: Session, document_id: uuid.UUID, link_id: uuid.UUID, source: str = "api",
           actor: str | None = None) -> None:
    row = db.get(DocumentLink, link_id)
    if row is None or row.document_id != document_id:
        raise NotFound("not_found", "Link not found")
    data = {"entity_type": row.entity_type, "entity_id": row.entity_id, "role": row.role}
    db.delete(row)
    db.flush()
    events.record(db, "document", document_id, "unlink", data, source, actor=actor)
