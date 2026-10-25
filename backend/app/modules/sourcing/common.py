"""Helpers shared by the sourcing services."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.documents.models import DocumentLink
from app.modules.parties.service import jsonable

__all__ = ["jsonable", "diff", "flush", "row_snapshot", "document_count", "linked_documents"]

FK_MESSAGES = {
    "unit": ("unknown_unit", "Unknown unit"),
    "currency": ("unknown_currency", "Unknown currency"),
    "country": ("unknown_country", "Unknown country"),
    "payment_term": ("unknown_payment_term", "Unknown payment term"),
    "product": ("unknown_product", "Unknown product"),
    "item_status": ("unknown_status", "Unknown item status"),
}


def diff(obj, changes: dict) -> dict:
    """Apply ``changes`` to ``obj``; return {field: {old, new}} of what really changed."""
    result = {}
    for field, value in changes.items():
        if getattr(obj, field) != value:
            result[field] = {"old": getattr(obj, field), "new": value}
            setattr(obj, field, value)
    return result


def flush(db: Session, code: str = "invalid_data") -> None:
    """Flush; constraint errors become 422 (unknown reference / check) or 409 (unique)."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        detail = str(exc.orig).splitlines()[0] if exc.orig else str(exc)
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == "23503":  # foreign key
            for key, (fk_code, message) in FK_MESSAGES.items():
                if key in detail:
                    raise AppError(fk_code, message, {"detail": detail}, status=422) from None
            raise AppError("unknown_reference", detail, status=422) from None
        if sqlstate == "23514":  # check
            raise AppError(code, detail, status=422) from None
        raise Conflict(code, detail) from None


def row_snapshot(obj, skip: tuple[str, ...] = ()) -> dict:
    return jsonable({c.key: getattr(obj, c.key) for c in obj.__table__.columns
                     if c.key not in skip and not c.computed})


def document_count(db: Session, entity_type: str, entity_ids: list) -> int:
    if not entity_ids:
        return 0
    return db.scalar(select(func.count()).select_from(DocumentLink).where(
        DocumentLink.entity_type == entity_type, DocumentLink.entity_id.in_([str(i) for i in entity_ids]))) or 0


def linked_documents(db: Session, entity_type: str, entity_ids: list) -> list[dict]:
    from app.modules.parties import service as parties

    return parties.linked_documents(db, entity_type, [str(i) for i in entity_ids])
