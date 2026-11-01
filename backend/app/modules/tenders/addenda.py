"""Addenda, questions and answers, extensions (v0.6.0).

An addendum can carry date changes: applying them writes ``tender_date_change`` rows linked to it and moves the
reminders. A cancellation sets the tender result to ``cancelled`` (with confirmation), cancels the reminders and
creates the bid-bond release follow-up. Recording an addendum marks Setad's addenda counters as seen.
"""
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.tenders import dates as tender_dates
from app.modules.tenders.common import get_tender
from app.modules.tenders.models import TenderAddendum, TenderDateChange

FIELDS = ("number", "received_on", "kind", "summary", "document_id", "question", "asked_on", "answer", "answered_on")


def get_addendum(db: Session, addendum_id: uuid.UUID) -> TenderAddendum:
    row = db.get(TenderAddendum, addendum_id)
    if row is None:
        raise NotFound("not_found", "Addendum not found")
    return row


def addenda_of(db: Session, tender_id: uuid.UUID) -> list[TenderAddendum]:
    return list(db.scalars(select(TenderAddendum).where(TenderAddendum.tender_id == tender_id)
                           .order_by(TenderAddendum.received_on, TenderAddendum.created_at)))


def _reason(row: TenderAddendum) -> str:
    kind = {"extension": "تمدید", "change": "اصلاحیه", "clarification": "توضیحات", "question_answer": "پرسش و پاسخ",
            "cancellation": "لغو", "other": "الحاقیه"}[row.kind]
    return f"{kind} {row.number or ''}".strip() + f" ({row.received_on.isoformat()})"


def add_addendum(db: Session, tender_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> TenderAddendum:
    """Record an addendum; ``date_changes`` [{date_id | kind, at}] are applied as changes linked to it; a
    cancellation needs ``confirm_cancellation``."""
    from app.modules.tenders import results, service

    tender = get_tender(db, tender_id)
    if data.get("kind") == "cancellation" and not data.get("confirm_cancellation"):
        raise AppError("confirmation_required", "Recording a cancellation cancels the tender; confirm it", status=422)
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    summary = (data.get("summary") or "").strip()
    if not summary:
        raise AppError("summary_required", "The addendum needs a summary", status=422)
    row = TenderAddendum(tender_id=tender.id, **{k: data.get(k) for k in FIELDS if data.get(k) is not None})
    row.summary = summary
    db.add(row)
    flush(db, "invalid_addendum")
    applied = apply_date_changes(db, row, data.get("date_changes") or [], source, actor)
    events.record(db, "tender", tender.id, "addendum_add", jsonable({**row_snapshot(row), "date_changes": applied}),
                  source, actor=actor)
    service.acknowledge_appendices(db, tender, source, actor)
    if row.kind == "cancellation":
        results.set_result(db, tender.id, {"result": "cancelled", "result_reason": "cancelled_by_organizer",
                                           "result_note": summary, "result_on": row.received_on}, source, actor)
    return row


def apply_date_changes(db: Session, row: TenderAddendum, changes: list[dict], source: str, actor: str | None) -> list[dict]:
    applied = []
    for change in changes:
        new_at: datetime = change["at"]
        if change.get("date_id"):
            date_row = tender_dates.get_date(db, change["date_id"])
            if date_row.tender_id != row.tender_id:
                raise AppError("date_not_of_tender", "The date belongs to another tender", status=422)
        else:
            date_row = tender_dates.date_of_kind(db, row.tender_id, change["kind"])
            if date_row is None:
                date_row = tender_dates.add_date(db, row.tender_id, {"kind": change["kind"], "at": new_at,
                                                                     "source": "addendum"}, source, actor)
                applied.append({"date_id": str(date_row.id), "kind": date_row.kind, "old": None, "new": new_at.isoformat()})
                continue
        old = date_row.at
        tender_dates.change_date(db, date_row.id, new_at, _reason(row), source, actor, addendum_id=row.id)
        applied.append({"date_id": str(date_row.id), "kind": date_row.kind, "old": old.isoformat(), "new": new_at.isoformat()})
    return applied


def update_addendum(db: Session, addendum_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> TenderAddendum:
    """Texts, number, dates of the question and answer; the kind and the applied date changes stay."""
    row = get_addendum(db, addendum_id)
    if changes.get("document_id"):
        documents.get(db, changes["document_id"])
    changed = {}
    for key in ("number", "summary", "document_id", "question", "asked_on", "answer", "answered_on", "received_on"):
        if key in changes and changes[key] != getattr(row, key):
            if key in ("summary", "received_on") and not changes[key]:
                continue
            changed[key] = {"old": getattr(row, key), "new": changes[key]}
            setattr(row, key, changes[key])
    applied = apply_date_changes(db, row, changes.get("date_changes") or [], source, actor)
    if changed or applied:
        flush(db, "invalid_addendum")
        events.record(db, "tender", row.tender_id, "addendum_update", jsonable({"addendum_id": row.id, "changes": changed,
                                                                                 "date_changes": applied}), source, actor=actor)
    return row


def delete_addendum(db: Session, addendum_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_addendum(db, addendum_id)
    linked = db.scalar(select(func.count()).select_from(TenderDateChange).where(TenderDateChange.addendum_id == row.id)) or 0
    if linked:
        raise Conflict("in_use", "Dates were changed by this addendum; the history keeps it", {"date_changes": linked})
    if row.kind == "cancellation":
        raise Conflict("addendum_cancellation", "A cancellation is part of the result; revise the result instead")
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "tender", row.tender_id, "addendum_delete", jsonable(snapshot), source, actor=actor)
