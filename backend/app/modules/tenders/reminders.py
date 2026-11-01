"""Follow-ups BOMS creates for tenders (reminders before a date, guarantee expiry and release, opening, contract).

The follow-ups themselves are written by the parties module (public service); ``ops.tender_followup`` records which
one belongs to which date or guarantee, so a moved date moves its reminders and a closed tender cancels them.
"""
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.parties import interactions as party_interactions
from app.modules.parties.models import Followup
from app.modules.tenders.common import today
from app.modules.tenders.models import TenderFollowup


def links(db: Session, *, tender_id: uuid.UUID | None = None, purpose: str | None = None,
          ref_id: uuid.UUID | None = None, open_only: bool = True) -> list[tuple[TenderFollowup, Followup]]:
    query = select(TenderFollowup, Followup).join(Followup, Followup.id == TenderFollowup.followup_id)
    if tender_id is not None:
        query = query.where(TenderFollowup.tender_id == tender_id)
    if purpose is not None:
        query = query.where(TenderFollowup.purpose == purpose)
    if ref_id is not None:
        query = query.where(TenderFollowup.ref_id == ref_id)
    if open_only:
        query = query.where(Followup.status == "open")
    return list(db.execute(query.order_by(Followup.due_on)).all())


def create(db: Session, *, tender_id: uuid.UUID | None, purpose: str, ref_id: uuid.UUID | None, party_id: uuid.UUID,
           action: str, due_on: date, days_before: int | None, source: str, actor: str | None) -> Followup:
    followup = party_interactions.create_followup(db, {"party_id": party_id, "action": action[:500], "due_on": due_on},
                                                  source, actor)
    db.add(TenderFollowup(tender_id=tender_id, followup_id=followup.id, purpose=purpose, ref_id=ref_id,
                          days_before=days_before))
    db.flush()
    return followup


def sync(db: Session, *, tender_id: uuid.UUID | None, purpose: str, ref_id: uuid.UUID, party_id: uuid.UUID | None,
         action: str, target: date | None, offsets: list[int], note: str, source: str, actor: str | None) -> dict:
    """Make the open reminders of one date / guarantee match ``target`` minus each offset: move the ones that stay,
    cancel the ones no longer wanted (or already in the past), create the missing ones. Reminders for a date that
    has passed are not created."""
    wanted: dict[int, date] = {}
    if target is not None and party_id is not None and target >= today():
        for offset in offsets:
            due = target - _days(offset)
            if due >= today():
                wanted[offset] = due
    out = {"created": 0, "moved": 0, "cancelled": 0}
    for link, followup in links(db, purpose=purpose, ref_id=ref_id):
        offset = link.days_before
        if offset in wanted and followup.party_id == party_id:
            due = wanted.pop(offset)
            if followup.due_on != due:
                party_interactions.reschedule_followup(db, followup.id, due, note, source, actor)
                out["moved"] += 1
            if followup.action != action[:500]:
                followup.action = action[:500]
        else:
            party_interactions.cancel_followup(db, followup.id, note, source, actor)
            out["cancelled"] += 1
    for offset, due in wanted.items():
        create(db, tender_id=tender_id, purpose=purpose, ref_id=ref_id, party_id=party_id, action=action,
               due_on=due, days_before=offset, source=source, actor=actor)
        out["created"] += 1
    db.flush()
    return out


def cancel(db: Session, note: str, source: str, actor: str | None, *, tender_id: uuid.UUID | None = None,
           purposes: tuple[str, ...] | None = None, ref_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    cancelled = []
    for link, followup in links(db, tender_id=tender_id, ref_id=ref_id):
        if purposes and link.purpose not in purposes:
            continue
        party_interactions.cancel_followup(db, followup.id, note, source, actor)
        cancelled.append(followup.id)
    return cancelled


def _days(n: int):
    from datetime import timedelta

    return timedelta(days=n)
