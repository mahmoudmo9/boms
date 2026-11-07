"""Reminders BOMS creates for tenders.

Since v0.8.0 the internal ones (reminders before a tender date, guarantee expiry, the opening day, the contract) are
TASKS (module ``tasks``, never on a party's follow-up list); only the guarantee release chase, which is an action with
the beneficiary, stays a parties follow-up linked in ``ops.tender_followup``. ``links`` returns both kinds as
(link, item) pairs with the same attributes (link.purpose / days_before / ref_id, item.id / due_on / action /
party_id / status), so callers do not care which kind a reminder is.
"""
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.parties import interactions as party_interactions
from app.modules.parties.models import Followup
from app.modules.tasks import service as tasks
from app.modules.tenders.common import today
from app.modules.tenders.models import Guarantee, Tender, TenderFollowup

# tender reminder purpose -> task kind (internal); every other purpose is a follow-up with a counterparty
INTERNAL = {"date_reminder": "tender_date", "guarantee_expiry": "guarantee_expiry", "opening": "opening", "contract": "contract"}
PURPOSE_OF = {v: k for k, v in INTERNAL.items()}


@dataclass
class TaskLink:
    purpose: str
    days_before: int | None
    ref_id: uuid.UUID | None
    tender_id: uuid.UUID | None = None


@dataclass
class TaskItem:
    id: uuid.UUID
    due_on: date
    action: str
    party_id: uuid.UUID | None
    status: str
    kind: str = "task"


def _item(t) -> TaskItem:
    return TaskItem(id=t.id, due_on=t.due_on, action=t.title, party_id=t.party_id, status=t.status)


def _case_of(db: Session, tender_id, purpose: str, ref_id):
    if tender_id:
        tender = db.get(Tender, tender_id)
        if tender is not None:
            return tender.case_id
    if purpose == "guarantee_expiry" and ref_id:
        g = db.get(Guarantee, ref_id)
        return g.case_id if g else None
    return None


def links(db: Session, *, tender_id: uuid.UUID | None = None, purpose: str | None = None,
          ref_id: uuid.UUID | None = None, open_only: bool = True) -> list[tuple]:
    out: list[tuple] = []
    if purpose is None or purpose not in INTERNAL:
        query = select(TenderFollowup, Followup).join(Followup, Followup.id == TenderFollowup.followup_id)
        if tender_id is not None:
            query = query.where(TenderFollowup.tender_id == tender_id)
        if purpose is not None:
            query = query.where(TenderFollowup.purpose == purpose)
        if ref_id is not None:
            query = query.where(TenderFollowup.ref_id == ref_id)
        if open_only:
            query = query.where(Followup.status == "open")
        out += list(db.execute(query).all())
    if purpose is None or purpose in INTERNAL:
        kinds = (INTERNAL[purpose],) if purpose else tuple(INTERNAL.values())
        case_id = None
        if tender_id is not None:
            tender = db.get(Tender, tender_id)
            if tender is None:
                return out
            case_id = tender.case_id
        rows = tasks.tasks_of(db, case_id=case_id, source="tenders", kinds=kinds, source_id=ref_id, open_only=open_only)
        out += [(TaskLink(PURPOSE_OF[t.source_kind], t.remind_days_before, t.source_id, tender_id), _item(t)) for t in rows]
    return sorted(out, key=lambda pair: pair[1].due_on)


def create(db: Session, *, tender_id: uuid.UUID | None, purpose: str, ref_id: uuid.UUID | None, party_id: uuid.UUID,
           action: str, due_on: date, days_before: int | None, source: str, actor: str | None):
    if purpose in INTERNAL:
        task = tasks.create(db, {"title": action, "due_on": due_on, "case_id": _case_of(db, tender_id, purpose, ref_id),
                                 "party_id": party_id, "source": "tenders", "source_kind": INTERNAL[purpose],
                                 "source_id": ref_id, "remind_of_due": due_on, "remind_days_before": days_before}, source, actor)
        return _item(task)
    followup = party_interactions.create_followup(db, {"party_id": party_id, "action": action[:500], "due_on": due_on},
                                                  source, actor)
    db.add(TenderFollowup(tender_id=tender_id, followup_id=followup.id, purpose=purpose, ref_id=ref_id,
                          days_before=days_before))
    db.flush()
    return followup


def sync(db: Session, *, tender_id: uuid.UUID | None, purpose: str, ref_id: uuid.UUID, party_id: uuid.UUID | None,
         action: str, target: date | None, offsets: list[int], note: str, source: str, actor: str | None) -> dict:
    """One task per remind day before ``target`` (moved with it, cancelled when it goes away or passes); a reminder
    for a date that has passed is not created. ``target=None`` cancels them all."""
    if purpose not in INTERNAL:
        raise ValueError(f"sync is for internal reminders, not {purpose}")
    return tasks.sync(db, source="tenders", source_kind=INTERNAL[purpose], source_id=ref_id,
                      case_id=_case_of(db, tender_id, purpose, ref_id), party_id=party_id, title=action, target=target,
                      offsets=offsets, note=note, source_ev=source, actor=actor, today=today())


def cancel(db: Session, note: str, source: str, actor: str | None, *, tender_id: uuid.UUID | None = None,
           purposes: tuple[str, ...] | None = None, ref_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    cancelled = []
    for link, item in links(db, tender_id=tender_id, ref_id=ref_id):
        if purposes and link.purpose not in purposes:
            continue
        if isinstance(item, TaskItem):
            tasks.cancel(db, item.id, note, source, actor)
        else:
            party_interactions.cancel_followup(db, item.id, note, source, actor)
        cancelled.append(item.id)
    return cancelled
