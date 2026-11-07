"""Tender dates with optional reminders and a change history (no silent overwrite)."""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.time import ensure_aware
from app.modules.events import service as events
from app.modules.sourcing.common import flush, jsonable
from app.modules.system import settings
from app.modules.tenders import reminders
from app.modules.tenders.common import date_label, get_tender, reason_required, tehran_day
from app.modules.tenders.models import Tender, TenderDate, TenderDateChange

REMINDER_PURPOSE = "date_reminder"
DATE_MOVED_NOTE = "tender date moved"


def _aware(value: datetime) -> datetime:
    try:
        return ensure_aware(value)
    except ValueError:
        raise AppError("naive_datetime", "The time needs a timezone", status=422) from None


def get_date(db: Session, date_id: uuid.UUID) -> TenderDate:
    row = db.get(TenderDate, date_id)
    if row is None:
        raise NotFound("not_found", "Tender date not found")
    return row


def dates_of(db: Session, tender_id: uuid.UUID) -> list[TenderDate]:
    return list(db.scalars(select(TenderDate).where(TenderDate.tender_id == tender_id).order_by(TenderDate.at)))


def date_of_kind(db: Session, tender_id: uuid.UUID, kind: str) -> TenderDate | None:
    return db.scalar(select(TenderDate).where(TenderDate.tender_id == tender_id, TenderDate.kind == kind))


def changes_of(db: Session, tender_id: uuid.UUID) -> list[TenderDateChange]:
    return list(db.scalars(select(TenderDateChange).where(TenderDateChange.tender_id == tender_id)
                           .order_by(TenderDateChange.created_at)))


def reminder_action(tender: Tender, row: TenderDate) -> str:
    return f"یادآوری: {date_label(row.kind, row.label)} {tender.tender_no or ''}".strip()


def sync_reminders(db: Session, tender: Tender, row: TenderDate, source: str, actor: str | None,
                   note: str = DATE_MOVED_NOTE) -> dict:
    """The date's reminder tasks (v0.8.0; none when the tender is closed or has a result)."""
    active = tender.result is None and tender.stage not in ("result", "closed")
    return reminders.sync(db, tender_id=tender.id, purpose=REMINDER_PURPOSE, ref_id=row.id,
                          party_id=tender.organizer_party_id, action=reminder_action(tender, row),
                          target=tehran_day(row.at) if active else None, offsets=list(row.remind_days_before or []),
                          note=note, source=source, actor=actor)


def add_date(db: Session, tender_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> TenderDate:
    tender = get_tender(db, tender_id)
    kind = data["kind"]
    if kind != "other" and date_of_kind(db, tender.id, kind) is not None:
        raise Conflict("date_exists", "This tender already has that date; change it instead", {"kind": kind})
    offsets = data.get("remind_days_before")
    if offsets is None:
        offsets = settings.get(db, "tenders.reminder_days")
    row = TenderDate(tender_id=tender.id, kind=kind, label=(data.get("label") or "").strip() or None,
                     at=_aware(data["at"]), all_day=bool(data.get("all_day")), note=data.get("note"),
                     remind_days_before=sorted(set(offsets), reverse=True), source=data.get("source") or "manual")
    db.add(row)
    flush(db, "invalid_tender_date")
    events.record(db, "tender", tender.id, "date_add", jsonable({"date_id": row.id, "kind": kind, "at": row.at,
                                                                 "source": row.source}), source, actor=actor)
    sync_reminders(db, tender, row, source, actor)
    return row


def change_date(db: Session, date_id: uuid.UUID, new_at: datetime, reason: str | None, source: str,
                actor: str | None = None, *, addendum_id: uuid.UUID | None = None) -> TenderDate:
    """Move a date: a change row with the reason (and the addendum), the reminders move with it."""
    row = get_date(db, date_id)
    tender = get_tender(db, row.tender_id)
    reason = reason_required(reason)
    new_at = _aware(new_at)
    if new_at == row.at:
        return row
    old = row.at
    db.add(TenderDateChange(tender_date_id=row.id, tender_id=tender.id, old_at=old, new_at=new_at, reason=reason,
                            addendum_id=addendum_id))
    row.at = new_at
    if addendum_id is not None:
        row.source = "addendum"
    flush(db, "invalid_tender_date")
    moved = sync_reminders(db, tender, row, source, actor)
    events.record(db, "tender", tender.id, "date_change", jsonable({
        "date_id": row.id, "kind": row.kind, "old": old, "new": new_at, "reason": reason, "addendum_id": addendum_id,
        "reminders": moved}), source, actor=actor)
    return row


def update_date(db: Session, date_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> TenderDate:
    """Label, note, all-day and reminder days; the time itself only through ``change_date`` (with a reason)."""
    row = get_date(db, date_id)
    tender = get_tender(db, row.tender_id)
    if "at" in changes:
        new_at = changes.pop("at")
        if new_at is not None and _aware(new_at) != row.at:
            change_date(db, row.id, new_at, changes.pop("reason", None), source, actor)
    changes.pop("reason", None)
    if "remind_days_before" in changes and changes["remind_days_before"] is not None:
        changes["remind_days_before"] = sorted(set(changes["remind_days_before"]), reverse=True)
    changed = {}
    for key in ("label", "note", "all_day", "remind_days_before"):
        if key in changes and changes[key] != getattr(row, key):
            changed[key] = {"old": getattr(row, key), "new": changes[key]}
            setattr(row, key, changes[key])
    if changed:
        flush(db, "invalid_tender_date")
        events.record(db, "tender", tender.id, "date_update", jsonable({"date_id": row.id, "changes": changed}),
                      source, actor=actor)
        sync_reminders(db, tender, row, source, actor, note="tender reminders changed")
    return row


def delete_date(db: Session, date_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_date(db, date_id)
    tender = get_tender(db, row.tender_id)
    reminders.cancel(db, "tender date deleted", source, actor, purposes=(REMINDER_PURPOSE,), ref_id=row.id)
    history = list(db.scalars(select(TenderDateChange).where(TenderDateChange.tender_date_id == row.id)))
    snapshot = {"kind": row.kind, "label": row.label, "at": row.at, "changes": [
        {"old": c.old_at, "new": c.new_at, "reason": c.reason} for c in history]}
    for change in history:
        db.delete(change)
    db.flush()
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "tender", tender.id, "date_delete", jsonable({"date_id": date_id, "deleted": snapshot}),
                  source, actor=actor)


def resync_all(db: Session, tender: Tender, source: str, actor: str | None, note: str) -> None:
    """After the organizer or the result changes: every date's reminders follow."""
    for row in dates_of(db, tender.id):
        sync_reminders(db, tender, row, source, actor, note=note)


def next_date(db: Session, tender_id: uuid.UUID) -> TenderDate | None:
    from app.modules.parties import clock

    now = clock.now()
    return db.scalar(select(TenderDate).where(TenderDate.tender_id == tender_id, TenderDate.at >= now)
                     .order_by(TenderDate.at).limit(1))
