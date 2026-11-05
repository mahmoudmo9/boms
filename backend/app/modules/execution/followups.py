"""Follow-ups BOMS creates for execution (PO confirmation and readiness, process step reminders, claims, invoicing,
warranty end, performance guarantee release). They are written by the parties module (public service);
``ops.execution_followup`` records which one belongs to which order / step / claim, so a moved date moves it and a
closed item cancels it."""
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.execution.common import today
from app.modules.execution.models import ExecutionFollowup
from app.modules.parties import interactions as party_interactions
from app.modules.parties.models import Followup


def links(db: Session, *, case_id: uuid.UUID | None = None, purpose: str | None = None, ref_id: uuid.UUID | None = None,
          open_only: bool = True) -> list[tuple[ExecutionFollowup, Followup]]:
    query = select(ExecutionFollowup, Followup).join(Followup, Followup.id == ExecutionFollowup.followup_id)
    if case_id is not None:
        query = query.where(ExecutionFollowup.case_id == case_id)
    if purpose is not None:
        query = query.where(ExecutionFollowup.purpose == purpose)
    if ref_id is not None:
        query = query.where(ExecutionFollowup.ref_id == ref_id)
    if open_only:
        query = query.where(Followup.status == "open")
    return list(db.execute(query.order_by(Followup.due_on)).all())


def create(db: Session, *, case_id: uuid.UUID, purpose: str, ref_id: uuid.UUID | None, party_id: uuid.UUID, action: str,
           due_on: date, days_before: int | None = None, interaction_id: uuid.UUID | None = None, source: str,
           actor: str | None) -> Followup:
    followup = party_interactions.create_followup(
        db, {"party_id": party_id, "action": action[:500], "due_on": due_on, "interaction_id": interaction_id},
        source, actor)
    db.add(ExecutionFollowup(case_id=case_id, followup_id=followup.id, purpose=purpose, ref_id=ref_id,
                             days_before=days_before))
    db.flush()
    return followup


def adopt(db: Session, *, case_id: uuid.UUID, purpose: str, ref_id: uuid.UUID, followup_id: uuid.UUID) -> None:
    """Record a follow-up created elsewhere (e.g. with the PO's sending interaction) as ours."""
    db.add(ExecutionFollowup(case_id=case_id, followup_id=followup_id, purpose=purpose, ref_id=ref_id))
    db.flush()


def sync(db: Session, *, case_id: uuid.UUID, purpose: str, ref_id: uuid.UUID, party_id: uuid.UUID | None, action: str,
         target: date | None, offsets: list[int], note: str, source: str, actor: str | None) -> dict:
    """Make the open reminders of one date match ``target`` minus each offset (as tender date reminders): move the
    ones that stay, cancel the ones no longer wanted, create the missing ones; none for dates in the past."""
    wanted: dict[int, date] = {}
    if target is not None and party_id is not None and target >= today():
        for offset in offsets:
            due = target - timedelta(days=offset)
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
        create(db, case_id=case_id, purpose=purpose, ref_id=ref_id, party_id=party_id, action=action, due_on=due,
               days_before=offset, source=source, actor=actor)
        out["created"] += 1
    db.flush()
    return out


def cancel(db: Session, note: str, source: str, actor: str | None, *, case_id: uuid.UUID | None = None,
           purposes: tuple[str, ...] | None = None, ref_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    cancelled = []
    for link, followup in links(db, case_id=case_id, ref_id=ref_id):
        if purposes and link.purpose not in purposes:
            continue
        party_interactions.cancel_followup(db, followup.id, note, source, actor)
        cancelled.append(followup.id)
    return cancelled


def complete(db: Session, note: str, source: str, actor: str | None, *, purpose: str, ref_id: uuid.UUID) -> list[uuid.UUID]:
    done = []
    for _link, followup in links(db, purpose=purpose, ref_id=ref_id):
        party_interactions.complete_followup(db, followup.id, note, None, source, actor)
        done.append(followup.id)
    return done
