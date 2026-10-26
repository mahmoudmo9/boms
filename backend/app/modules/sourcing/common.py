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
    """Flush; constraint errors become 422 (unknown reference / check) or 409 (unique / still referenced).

    The database's own message is never copied into the API error; only stable codes and the constraint name.
    """
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        diag = getattr(exc.orig, "diag", None)
        detail = (getattr(diag, "message_detail", None) or "") if diag else ""
        constraint = getattr(diag, "constraint_name", None) if diag else None
        sqlstate = getattr(exc.orig, "sqlstate", None)
        info = {"constraint": constraint} if constraint else {}
        if sqlstate == "23503":  # foreign key
            if "still referenced" in detail:
                table = detail.rsplit("table", 1)[-1].strip(' ".')
                raise Conflict("in_use", "The record is still referenced by other records",
                               {**info, "referenced_by": table}) from None
            for key, (fk_code, message) in FK_MESSAGES.items():
                if f'table "{key}"' in detail:
                    raise AppError(fk_code, message, info, status=422) from None
            raise AppError("unknown_reference", "A referenced record does not exist", info, status=422) from None
        if sqlstate == "23514":  # check
            raise AppError(code, "The data violates a rule", info, status=422) from None
        raise Conflict(code, "The data conflicts with an existing record", info) from None


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
