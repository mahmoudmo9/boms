"""Process checklists per deal type (v0.7.0): import, export, domestic.

Templates (``process_template`` + steps) are data the owner edits in Settings → Execution (labels, references,
"needs a document", default offsets, order); three are seeded. A case gets one process per deal type, copied from the
default template of the deal type of its current cost sheet when its sales order is confirmed (or by hand). A step's
due date is the order confirmation plus the step's offset (editable). Reminders before each due date (``remind
days``, default ``execution.step_reminder_days``) are parties follow-ups that move with the date and are cancelled when
the step is done or not applicable, or the case is closed. A step that needs a document is not ``done`` without one
unless a reason is given.
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.costing import service as costing
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.execution import followups
from app.modules.execution.common import get, today
from app.modules.execution.models import Process, ProcessStep, ProcessTemplate, ProcessTemplateStep, SalesOrder
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings

DEAL_TYPES = ("import", "export", "domestic")
STEP_FIELDS = ("group", "code", "label_fa", "label_en", "reference_label", "requires_document", "default_offset_days")
CLOSED_CASE = ("lost", "cancelled", "closed")


# ---- templates --------------------------------------------------------------------------------------------------------

def get_template(db: Session, template_id: uuid.UUID) -> ProcessTemplate:
    return get(db, ProcessTemplate, template_id, "Process template")


def template_steps(db: Session, template_id: uuid.UUID) -> list[ProcessTemplateStep]:
    return list(db.scalars(select(ProcessTemplateStep).where(ProcessTemplateStep.template_id == template_id)
                           .order_by(ProcessTemplateStep.position)))


def list_templates(db: Session, include_archived: bool = False) -> list[ProcessTemplate]:
    query = select(ProcessTemplate)
    if not include_archived:
        query = query.where(ProcessTemplate.status == "active")
    return list(db.scalars(query.order_by(ProcessTemplate.deal_type, ProcessTemplate.is_default.desc(), ProcessTemplate.name)))


def default_template(db: Session, deal_type: str) -> ProcessTemplate | None:
    return db.scalar(select(ProcessTemplate).where(ProcessTemplate.deal_type == deal_type, ProcessTemplate.status == "active")
                     .order_by(ProcessTemplate.is_default.desc(), ProcessTemplate.created_at).limit(1))


def _clear_default(db: Session, template: ProcessTemplate) -> None:
    if template.is_default:
        for other in db.scalars(select(ProcessTemplate).where(ProcessTemplate.deal_type == template.deal_type,
                                                              ProcessTemplate.id != template.id, ProcessTemplate.is_default)):
            other.is_default = False
        db.flush()


def _write_steps(db: Session, template: ProcessTemplate, steps: list[dict]) -> None:
    codes = [s["code"] for s in steps]
    if len(codes) != len(set(codes)):
        raise AppError("duplicate_step_code", "Step codes must be unique in a template", status=422)
    for row in template_steps(db, template.id):
        db.delete(row)
    db.flush()
    for position, step in enumerate(steps, start=1):
        db.add(ProcessTemplateStep(template_id=template.id, position=position,
                                   **{k: step.get(k) for k in STEP_FIELDS if k != "requires_document"},
                                   requires_document=bool(step.get("requires_document"))))
    flush(db, "invalid_template_step")


def create_template(db: Session, data: dict, source: str, actor: str | None = None) -> ProcessTemplate:
    row = ProcessTemplate(deal_type=data["deal_type"], name=data["name"], is_default=bool(data.get("is_default")))
    db.add(row)
    _clear_default(db, row)
    flush(db, "invalid_template")
    _write_steps(db, row, data.get("steps") or [])
    events.record(db, "process_template", row.id, "create", jsonable({"name": row.name, "deal_type": row.deal_type,
                                                                     "steps": len(data.get("steps") or [])}), source, actor=actor)
    return row


def update_template(db: Session, template_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> ProcessTemplate:
    row = get_template(db, template_id)
    steps = changes.pop("steps", None)
    changed = diff(row, {k: v for k, v in changes.items() if k in ("name", "is_default", "status")})
    _clear_default(db, row)
    flush(db, "invalid_template")
    if steps is not None:
        _write_steps(db, row, steps)
        changed["steps"] = len(steps)
    if changed:
        events.record(db, "process_template", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return row


def delete_template(db: Session, template_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_template(db, template_id)
    if row.is_default:
        raise Conflict("template_is_default", "Make another template the default first")
    snapshot = row_snapshot(row)
    for step in template_steps(db, row.id):
        db.delete(step)
    db.flush()
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "process_template", template_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def template_out(db: Session, row: ProcessTemplate) -> dict:
    return jsonable({**row_snapshot(row), "steps": [row_snapshot(s) for s in template_steps(db, row.id)]})


# ---- the process of a case -------------------------------------------------------------------------------------------

def processes_of(db: Session, case_id: uuid.UUID) -> list[Process]:
    return list(db.scalars(select(Process).where(Process.case_id == case_id).order_by(Process.created_at)))


def steps_of(db: Session, process_id: uuid.UUID) -> list[ProcessStep]:
    return list(db.scalars(select(ProcessStep).where(ProcessStep.process_id == process_id).order_by(ProcessStep.position)))


def _reminder_party(db: Session, process: Process):
    if process.sales_order_id:
        return db.get(SalesOrder, process.sales_order_id).customer_party_id
    return sourcing.get_case(db, process.case_id).party_id


def _sync_reminders(db: Session, process: Process, step: ProcessStep, note: str, source: str, actor: str | None) -> dict:
    active = step.status in ("pending", "in_progress")
    case = sourcing.get_case(db, process.case_id)
    return followups.sync(db, case_id=process.case_id, purpose="step_reminder", ref_id=step.id,
                          party_id=_reminder_party(db, process) if active else None,
                          action=f"{step.label_fa} — {case.title}", target=step.due_on if active else None,
                          offsets=list(step.remind_days_before or []), note=note, source=source, actor=actor)


def deal_type_of(db: Session, case_id: uuid.UUID) -> str:
    sheet = costing.current_sheet(db, case_id)
    return sheet.deal_type if sheet is not None and sheet.deal_type in DEAL_TYPES else "domestic"


def create_process(db: Session, case_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> Process:
    case = sourcing.get_case(db, case_id)
    deal_type = data.get("deal_type") or deal_type_of(db, case.id)
    if db.scalar(select(Process).where(Process.case_id == case.id, Process.deal_type == deal_type)):
        raise Conflict("process_exists", "The case already has a checklist of this deal type", {"deal_type": deal_type})
    template = get_template(db, data["template_id"]) if data.get("template_id") else default_template(db, deal_type)
    if template is not None and template.deal_type != deal_type:
        raise AppError("template_deal_type", "The template is of another deal type", status=422)
    base = data.get("base_date") or today()
    process = Process(case_id=case.id, deal_type=deal_type, template_id=template.id if template else None,
                      name=template.name if template else deal_type, sales_order_id=data.get("sales_order_id"),
                      base_date=base)
    db.add(process)
    flush(db, "invalid_process")
    offsets = settings.get(db, "execution.step_reminder_days")
    for t in template_steps(db, template.id) if template else []:
        step = ProcessStep(process_id=process.id, position=t.position, status="pending", remind_days_before=list(offsets),
                           due_on=base + timedelta(days=t.default_offset_days) if t.default_offset_days is not None else None,
                           **{k: getattr(t, k) for k in STEP_FIELDS if k != "default_offset_days"})
        db.add(step)
    flush(db, "invalid_process_step")
    for step in steps_of(db, process.id):
        _sync_reminders(db, process, step, "process created", source, actor)
    events.record(db, "process", process.id, "create", jsonable({
        "case_id": case.id, "deal_type": deal_type, "template_id": process.template_id, "base_date": base,
        "steps": len(steps_of(db, process.id))}), source, actor=actor)
    events.record(db, "case", case.id, "process_add", jsonable({"process_id": process.id, "deal_type": deal_type}),
                  source, actor=actor)
    return process


def on_order_confirmed(db: Session, order: SalesOrder, source: str, actor: str | None) -> None:
    """Sales-order hook: the checklist of the case's deal type, due dates from the confirmation day."""
    deal_type = deal_type_of(db, order.case_id)
    if db.scalar(select(Process).where(Process.case_id == order.case_id, Process.deal_type == deal_type)) is None:
        create_process(db, order.case_id, {"deal_type": deal_type, "sales_order_id": order.id,
                                           "base_date": order.confirmed_at.date()}, source, actor)


def _check_done(db: Session, step: ProcessStep) -> None:
    if step.status == "done" and step.requires_document and step.document_id is None \
            and not (step.no_document_reason or "").strip():
        raise AppError("document_required", "This step needs its document, or a reason why there is none",
                       {"step": step.code}, status=422)


def update_step(db: Session, step_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> ProcessStep:
    step = get(db, ProcessStep, step_id, "Process step")
    process = get(db, Process, step.process_id, "Process")
    if changes.get("document_id"):
        documents.get(db, changes["document_id"])
    old_status = step.status
    changed = diff(step, {k: v for k, v in changes.items() if k in (
        "status", "reference", "started_on", "done_on", "due_on", "remind_days_before", "document_id",
        "no_document_reason", "shipment_id", "note", "label_fa", "label_en", "reference_label", "requires_document")})
    if step.status == "in_progress" and step.started_on is None:
        step.started_on = today()
    if step.status == "done" and step.done_on is None:
        step.done_on = today()
    if step.status in ("pending", "in_progress") and old_status == "done":
        step.done_on = None
    _check_done(db, step)
    flush(db, "invalid_process_step")
    if set(changed) & {"status", "due_on", "remind_days_before"}:
        _sync_reminders(db, process, step, f"step {step.code}: {step.status}", source, actor)
    if changed:
        events.record(db, "process", process.id, "step_update", jsonable({"step_id": step.id, "code": step.code,
                                                                         "changes": changed}), source, actor=actor)
    return step


def add_step(db: Session, process_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> ProcessStep:
    process = get(db, Process, process_id, "Process")
    position = (db.scalar(select(func.max(ProcessStep.position)).where(ProcessStep.process_id == process.id)) or 0) + 1
    step = ProcessStep(process_id=process.id, position=position, status="pending",
                       remind_days_before=data.get("remind_days_before") or list(settings.get(db, "execution.step_reminder_days")),
                       due_on=data.get("due_on"), code=data.get("code") or f"custom_{position}",
                       label_fa=data["label_fa"], label_en=data.get("label_en") or data["label_fa"],
                       group=data.get("group"), reference_label=data.get("reference_label"),
                       requires_document=bool(data.get("requires_document")))
    db.add(step)
    flush(db, "invalid_process_step")
    _sync_reminders(db, process, step, "step added", source, actor)
    events.record(db, "process", process.id, "step_add", jsonable(row_snapshot(step)), source, actor=actor)
    return step


def remove_step(db: Session, step_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    step = get(db, ProcessStep, step_id, "Process step")
    if step.status == "done":
        raise Conflict("step_done", "A done step is kept; mark it not applicable instead")
    followups.cancel(db, "step removed", source, actor, ref_id=step.id)
    snapshot = row_snapshot(step)
    db.delete(step)
    flush(db, "in_use")
    events.record(db, "process", snapshot["process_id"], "step_remove", jsonable({"step": snapshot}), source, actor=actor)


def reorder(db: Session, process_id: uuid.UUID, step_ids: list[uuid.UUID], source: str, actor: str | None = None) -> None:
    steps = {s.id: s for s in steps_of(db, process_id)}
    if set(step_ids) != set(steps):
        raise AppError("invalid_order", "Give every step of the process once", status=422)
    for position, sid in enumerate(step_ids, start=1):
        steps[sid].position = position
    flush(db, "invalid_process_step")
    events.record(db, "process", process_id, "reorder", jsonable({"steps": step_ids}), source, actor=actor)


def progress(db: Session, process: Process) -> dict:
    """«9 of 14» (done or not applicable) and the next step due (open, earliest due date)."""
    steps = steps_of(db, process.id)
    finished = [s for s in steps if s.status in ("done", "not_applicable")]
    open_steps = [s for s in steps if s.status in ("pending", "in_progress")]
    dated = sorted((s for s in open_steps if s.due_on), key=lambda s: (s.due_on, s.position))
    nxt = dated[0] if dated else (open_steps[0] if open_steps else None)
    return jsonable({"done": len(finished), "total": len(steps),
                     "next": None if nxt is None else {"id": nxt.id, "code": nxt.code, "label_fa": nxt.label_fa,
                                                       "label_en": nxt.label_en, "due_on": nxt.due_on,
                                                       "overdue": bool(nxt.due_on and nxt.due_on < today())}})


def process_out(db: Session, process: Process) -> dict:
    reminders: dict = {}
    for link, f in followups.links(db, case_id=process.case_id, purpose="step_reminder"):
        reminders.setdefault(str(link.ref_id), []).append({"id": f.id, "due_on": f.due_on, "days_before": link.days_before})
    return jsonable({**row_snapshot(process), "progress": progress(db, process),
                     "steps": [{**row_snapshot(s), "reminders": reminders.get(str(s.id), [])} for s in steps_of(db, process.id)]})


def on_purchase_order_event(db: Session, po, code: str, source: str, actor: str | None) -> None:
    """Domestic checklists: «PO sent» and «goods ready» follow the PO (a pending step only)."""
    for process in processes_of(db, po.case_id):
        for step in steps_of(db, process.id):
            if step.code == code and step.status == "pending":
                update_step(db, step.id, {"status": "done", "note": f"{po.number}"}, source, actor)


def on_case_status(db: Session, case, old_status, source: str, actor: str | None) -> None:
    if case.status in CLOSED_CASE:
        followups.cancel(db, f"case {case.status}", source, actor, case_id=case.id, purposes=("step_reminder",))


__all__ = ["date"]
