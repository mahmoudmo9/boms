"""Reminders BOMS creates for execution.

Since v0.8.0 the internal ones (process step reminders, «صدور فاکتور», warranty end and the reminder before it) are
TASKS (module ``tasks``, never on a party's follow-up list). The actions with a counterparty (PO confirmation and
readiness chases, claim chases) stay parties follow-ups linked in ``ops.execution_followup``. ``links`` returns both
kinds as (link, item) pairs with the same attributes (link.purpose / days_before / ref_id / case_id, item.id / due_on
/ action / party_id / status), so callers do not care which kind a reminder is."""
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.execution.common import today
from app.modules.execution.models import ExecutionFollowup
from app.modules.parties import interactions as party_interactions
from app.modules.parties.models import Followup
from app.modules.tasks import service as tasks

# execution reminder purpose -> task kind (internal); every other purpose is a follow-up with a counterparty
INTERNAL = {"step_reminder": "process_step", "invoice": "invoice_issue", "warranty_end": "warranty_end",
            "warranty_remind": "warranty_remind"}
PURPOSE_OF = {v: k for k, v in INTERNAL.items()}


@dataclass
class TaskLink:
    purpose: str
    days_before: int | None
    ref_id: uuid.UUID | None
    case_id: uuid.UUID | None


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


def links(db: Session, *, case_id: uuid.UUID | None = None, purpose: str | None = None, ref_id: uuid.UUID | None = None,
          open_only: bool = True) -> list[tuple]:
    out: list[tuple] = []
    if purpose is None or purpose not in INTERNAL:
        query = select(ExecutionFollowup, Followup).join(Followup, Followup.id == ExecutionFollowup.followup_id)
        if case_id is not None:
            query = query.where(ExecutionFollowup.case_id == case_id)
        if purpose is not None:
            query = query.where(ExecutionFollowup.purpose == purpose)
        if ref_id is not None:
            query = query.where(ExecutionFollowup.ref_id == ref_id)
        if open_only:
            query = query.where(Followup.status == "open")
        out += list(db.execute(query).all())
    if purpose is None or purpose in INTERNAL:
        kinds = (INTERNAL[purpose],) if purpose else tuple(INTERNAL.values())
        rows = tasks.tasks_of(db, case_id=case_id, source="execution", kinds=kinds, source_id=ref_id, open_only=open_only)
        out += [(TaskLink(PURPOSE_OF[t.source_kind], t.remind_days_before, t.source_id, t.case_id), _item(t)) for t in rows]
    return sorted(out, key=lambda pair: pair[1].due_on)


def create(db: Session, *, case_id: uuid.UUID, purpose: str, ref_id: uuid.UUID | None, party_id: uuid.UUID, action: str,
           due_on: date, days_before: int | None = None, interaction_id: uuid.UUID | None = None, source: str,
           actor: str | None, remind_of_due: date | None = None):
    if purpose in INTERNAL:
        return _item(tasks.create(db, {"title": action, "due_on": due_on, "case_id": case_id, "party_id": party_id,
                                       "source": "execution", "source_kind": INTERNAL[purpose], "source_id": ref_id,
                                       "remind_of_due": remind_of_due or due_on, "remind_days_before": days_before},
                                  source, actor))
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
    """One task per remind day before ``target`` (moved with it, cancelled when it goes away or passes); none for a
    date that has passed. ``target=None`` cancels them all."""
    if purpose not in INTERNAL:
        raise ValueError(f"sync is for internal reminders, not {purpose}")
    return tasks.sync(db, source="execution", source_kind=INTERNAL[purpose], source_id=ref_id, case_id=case_id,
                      party_id=party_id, title=action, target=target, offsets=offsets, note=note, source_ev=source,
                      actor=actor, today=today())


def cancel(db: Session, note: str, source: str, actor: str | None, *, case_id: uuid.UUID | None = None,
           purposes: tuple[str, ...] | None = None, ref_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    cancelled = []
    for link, item in links(db, case_id=case_id, ref_id=ref_id):
        if purposes and link.purpose not in purposes:
            continue
        if isinstance(item, TaskItem):
            tasks.cancel(db, item.id, note, source, actor)
        else:
            party_interactions.cancel_followup(db, item.id, note, source, actor)
        cancelled.append(item.id)
    return cancelled


def complete(db: Session, note: str, source: str, actor: str | None, *, purpose: str, ref_id: uuid.UUID) -> list[uuid.UUID]:
    done = []
    for _link, item in links(db, purpose=purpose, ref_id=ref_id):
        if isinstance(item, TaskItem):
            tasks.done(db, item.id, note, source, actor)
        else:
            party_interactions.complete_followup(db, item.id, note, None, source, actor)
        done.append(item.id)
    return done
