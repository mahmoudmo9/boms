"""Tasks: the public service other modules call for internal reminders (instead of the parties follow-up service).

A task has a due date (and a time when it matters), a status open / done / cancelled, a priority, the case and party
it is about (context only: a task never appears on a party's follow-up list), the module and record it comes from
(``source``, ``source_kind``, ``source_id``) and the date it reminds about (``remind_of_due``). ``sync`` keeps one
task per remind day before a date, moved with the date and cancelled when the date goes away, exactly as the
follow-up reminders of v0.6.0 / v0.7.0 did.
"""
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.tasks.models import Task

KINDS = ("tender_date", "process_step", "guarantee_expiry", "warranty_end", "warranty_remind", "opening", "contract",
         "invoice_issue", "manual")
FIELDS = ("title", "due_on", "due_at", "priority", "case_id", "party_id", "notes")


def get_task(db: Session, task_id: uuid.UUID) -> Task:
    row = db.get(Task, task_id)
    if row is None:
        raise NotFound("not_found", "Task not found")
    return row


def _open(db: Session, task_id: uuid.UUID) -> Task:
    row = get_task(db, task_id)
    if row.status != "open":
        raise Conflict("task_not_open", f"The task is already {row.status}", {"status": row.status})
    return row


def create(db: Session, data: dict, source: str, actor: str | None = None) -> Task:
    if data.get("source_kind", "manual") not in KINDS:
        raise AppError("invalid_kind", "Unknown task kind", status=422)
    title = (data.get("title") or "").strip()
    if not title:
        raise AppError("title_required", "A task needs a title", status=422)
    row = Task(title=title[:500], due_on=data["due_on"], due_at=data.get("due_at"), status="open",
               priority=data.get("priority") or "normal", case_id=data.get("case_id"), party_id=data.get("party_id"),
               source=data.get("source") or "manual", source_kind=data.get("source_kind") or "manual",
               source_id=data.get("source_id"), remind_of_due=data.get("remind_of_due") or data["due_on"],
               remind_days_before=data.get("remind_days_before"), notes=data.get("notes"))
    db.add(row)
    flush(db, "invalid_task")
    events.record(db, "task", row.id, "create", jsonable({k: getattr(row, k) for k in (
        "title", "due_on", "case_id", "source", "source_kind", "source_id", "remind_days_before")}), source, actor=actor)
    return row


def update(db: Session, task_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Task:
    row = _open(db, task_id)
    changed = diff(row, {k: v for k, v in changes.items() if k in FIELDS})
    flush(db, "invalid_task")
    if changed:
        events.record(db, "task", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return row


def move(db: Session, task_id: uuid.UUID, due_on: date, note: str | None, source: str, actor: str | None = None,
         due_at: datetime | None = None) -> Task:
    row = _open(db, task_id)
    old = row.due_on
    if old != due_on or (due_at is not None and due_at != row.due_at):
        row.due_on = due_on
        if due_at is not None:
            row.due_at = due_at
        flush(db, "invalid_task")
        events.record(db, "task", row.id, "move", {"old_due_on": old.isoformat(), "new_due_on": due_on.isoformat(),
                                                    "note": note}, source, actor=actor)
    return row


def done(db: Session, task_id: uuid.UUID, note: str | None, source: str, actor: str | None = None) -> Task:
    row = _open(db, task_id)
    row.status, row.done_at, row.done_note = "done", clock.now(), (note or "").strip() or None
    flush(db, "invalid_task")
    events.record(db, "task", row.id, "done", {"note": row.done_note}, source, actor=actor)
    return row


def cancel(db: Session, task_id: uuid.UUID, note: str, source: str, actor: str | None = None) -> Task:
    note = (note or "").strip()
    if not note:
        raise AppError("note_required", "Cancelling a task needs a note", status=422)
    row = _open(db, task_id)
    row.status, row.done_at, row.done_note = "cancelled", clock.now(), note
    flush(db, "invalid_task")
    events.record(db, "task", row.id, "cancel", {"note": note}, source, actor=actor)
    return row


def reopen(db: Session, task_id: uuid.UUID, source: str, actor: str | None = None) -> Task:
    row = get_task(db, task_id)
    if row.status == "open":
        return row
    row.status, row.done_at, row.done_note = "open", None, None
    flush(db, "invalid_task")
    events.record(db, "task", row.id, "reopen", {}, source, actor=actor)
    return row


def tasks_of(db: Session, *, case_id=None, source: str | None = None, source_kind: str | None = None,
             source_id=None, kinds: tuple[str, ...] | None = None, open_only: bool = True) -> list[Task]:
    query = select(Task)
    if case_id is not None:
        query = query.where(Task.case_id == case_id)
    if source is not None:
        query = query.where(Task.source == source)
    if source_kind is not None:
        query = query.where(Task.source_kind == source_kind)
    if kinds:
        query = query.where(Task.source_kind.in_(kinds))
    if source_id is not None:
        query = query.where(Task.source_id == source_id)
    if open_only:
        query = query.where(Task.status == "open")
    return list(db.scalars(query.order_by(Task.due_on, Task.created_at)))


def cancel_by_source(db: Session, note: str, source_ev: str, actor: str | None, *, source: str | None = None,
                     kinds: tuple[str, ...] | None = None, source_id=None, case_id=None) -> list[uuid.UUID]:
    out = []
    for row in tasks_of(db, case_id=case_id, source=source, kinds=kinds, source_id=source_id):
        cancel(db, row.id, note, source_ev, actor)
        out.append(row.id)
    return out


def sync(db: Session, *, source: str, source_kind: str, source_id: uuid.UUID, case_id, party_id, title: str,
         target: date | None, offsets: list[int], note: str, source_ev: str, actor: str | None,
         due_at: datetime | None = None, today: date | None = None) -> dict:
    """Make the open tasks of one date match ``target`` minus each offset: move the ones that stay, cancel the ones
    no longer wanted (or in the past), create the missing ones; none for a date that has passed."""
    today = today or clock.today()
    wanted: dict[int, date] = {}
    if target is not None and target >= today:
        for offset in offsets:
            due = target - timedelta(days=offset)
            if due >= today:
                wanted[offset] = due
    out = {"created": 0, "moved": 0, "cancelled": 0}
    for row in tasks_of(db, source=source, source_kind=source_kind, source_id=source_id):
        if row.remind_days_before in wanted:
            due = wanted.pop(row.remind_days_before)
            if row.due_on != due:
                move(db, row.id, due, note, source_ev, actor)
                out["moved"] += 1
            if row.title != title[:500] or row.remind_of_due != target or (due_at and row.due_at != due_at):
                row.title, row.remind_of_due = title[:500], target
                if due_at:
                    row.due_at = due_at
                flush(db, "invalid_task")
        else:
            cancel(db, row.id, note, source_ev, actor)
            out["cancelled"] += 1
    for offset, due in wanted.items():
        create(db, {"title": title, "due_on": due, "due_at": due_at, "case_id": case_id, "party_id": party_id,
                    "source": source, "source_kind": source_kind, "source_id": source_id, "remind_of_due": target,
                    "remind_days_before": offset}, source_ev, actor)
        out["created"] += 1
    return out


def buckets(rows: list[Task], today: date) -> dict:
    """«کارهای من»: overdue, today, this week (next 7 days), later; done (and cancelled) separately."""
    out = {"overdue": [], "today": [], "week": [], "later": [], "done": []}
    for r in rows:
        if r.status != "open":
            out["done"].append(r)
        elif r.due_on < today:
            out["overdue"].append(r)
        elif r.due_on == today:
            out["today"].append(r)
        elif r.due_on <= today + timedelta(days=7):
            out["week"].append(r)
        else:
            out["later"].append(r)
    return out


def list_tasks(db: Session, *, case_id=None, kind: str | None = None, status: str | None = "open", q: str | None = None,
               limit: int = 500) -> list[Task]:
    query = select(Task)
    if case_id:
        query = query.where(Task.case_id == case_id)
    if kind:
        query = query.where(Task.source_kind == kind)
    if status == "open":
        query = query.where(Task.status == "open")
    elif status == "closed":
        query = query.where(Task.status != "open")
    if q:
        query = query.where(or_(Task.title.ilike(f"%{q}%"), Task.notes.ilike(f"%{q}%")))
    order = (Task.due_on, Task.created_at) if status != "closed" else (Task.done_at.desc(),)
    return list(db.scalars(query.order_by(*order).limit(limit)))


def task_out(row: Task, titles: dict | None = None) -> dict:
    out = jsonable(row_snapshot(row))
    if titles is not None:
        out["case_title"] = titles.get(row.case_id)
    return out
