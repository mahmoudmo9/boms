"""Drafts and the review screen (v0.9.0 section 2).

A draft holds what the AI proposed for a target record, field by field: the proposed value, a confidence, the source
reference (file, page, row or region) and the owner's decision with the final value. Nothing reaches a business table
before «ثبت»: then the target's committer (registered by the owning module) writes through that module's normal services
with source ``ai_draft`` — the same validation, events and audit as manual entry. Edited fields are stored as
corrections and the last relevant ones are given to the next prompt of the same task as examples."""
import json
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.modules.ai.models import Correction, Draft, DraftField
from app.modules.events import service as events

SOURCE = "ai_draft"
OPEN = ("pending", "ready")
COMMITTERS: dict[str, Callable] = {}       # target_type -> fn(db, draft, values: dict, source, actor) -> dict


def register_committer(target_type: str, fn: Callable) -> None:
    COMMITTERS[target_type] = fn


def create(db: Session, *, task: str, target_type: str, target_id: str | None = None, case_id=None,
           sources: list | None = None, source: str = "api", actor: str | None = None) -> Draft:
    """A pending draft (the job fills it); earlier open drafts of the same target are superseded."""
    for old in db.scalars(select(Draft).where(Draft.target_type == target_type, Draft.target_id == target_id,
                                              Draft.task == task, Draft.status.in_(OPEN))):
        old.status = "superseded"
    row = Draft(task=task, target_type=target_type, target_id=str(target_id) if target_id else None, case_id=case_id,
                sources=sources or [], status="pending")
    db.add(row)
    db.flush()
    events.record(db, "ai_draft", row.id, "create", {"task": task, "target_type": target_type,
                                                    "target_id": row.target_id}, source, actor=actor)
    return row


def fill(db: Session, draft: Draft, fields: list[dict], payload: dict | None = None, checks: list | None = None,
         call_id=None) -> Draft:
    """``fields``: [{path, label, value, confidence, source}] in display order."""
    db.query(DraftField).filter(DraftField.draft_id == draft.id).delete()
    for i, f in enumerate(fields):
        db.add(DraftField(draft_id=draft.id, position=i, path=f["path"], label=f.get("label"), proposed=f.get("value"),
                          confidence=f.get("confidence") or "medium", source=f.get("source") or {}))
    draft.payload = payload or {}
    draft.checks = checks or []
    draft.status = "ready"
    draft.created_by_call_id = call_id
    db.flush()
    return draft


def fail(db: Session, draft: Draft, error: str) -> None:
    draft.status = "failed"
    draft.error = error[:2000]
    db.flush()


def get(db: Session, draft_id) -> Draft:
    row = db.get(Draft, draft_id)
    if row is None:
        raise NotFound("not_found", "Draft not found")
    return row


def fields_of(db: Session, draft_id) -> list[DraftField]:
    return list(db.scalars(select(DraftField).where(DraftField.draft_id == draft_id).order_by(DraftField.position)))


def out(db: Session, draft: Draft) -> dict:
    from app.modules.sourcing.common import jsonable

    return jsonable({
        "id": draft.id, "task": draft.task, "target_type": draft.target_type, "target_id": draft.target_id,
        "case_id": draft.case_id, "status": draft.status, "error": draft.error, "sources": draft.sources,
        "checks": draft.checks, "payload": draft.payload, "committed_at": draft.committed_at, "result": draft.result,
        "created_at": draft.created_at, "call_id": draft.created_by_call_id,
        "fields": [{"id": f.id, "path": f.path, "label": f.label, "proposed": f.proposed, "confidence": f.confidence,
                    "source": f.source, "decision": f.decision, "final": f.final} for f in fields_of(db, draft.id)],
    })


def _open(draft: Draft) -> None:
    if draft.status != "ready":
        raise AppError("draft_not_open", "This draft can no longer be changed", {"status": draft.status}, status=409)


def decide(db: Session, draft_id, field_id, decision: str, value: Any = None) -> DraftField:
    draft = get(db, draft_id)
    _open(draft)
    f = db.get(DraftField, field_id)
    if f is None or f.draft_id != draft.id:
        raise NotFound("not_found", "Field not found")
    if decision not in ("accepted", "edited", "rejected", "undecided"):
        raise AppError("invalid_decision", "Decision is accepted, edited, rejected or undecided", status=422)
    if decision == "edited" and value is None:
        raise AppError("value_required", "An edited field needs its value", status=422)
    f.decision = None if decision == "undecided" else decision
    f.final = f.proposed if decision == "accepted" else value if decision == "edited" else None
    db.flush()
    return f


def accept_confident(db: Session, draft_id) -> int:
    """«پذیرش همهٔ موارد مطمئن»: every undecided high-confidence field is accepted as proposed."""
    draft = get(db, draft_id)
    _open(draft)
    count = 0
    for f in fields_of(db, draft.id):
        if f.decision is None and f.confidence == "high":
            f.decision, f.final = "accepted", f.proposed
            count += 1
    db.flush()
    return count


def reject(db: Session, draft_id, source: str, actor: str | None) -> Draft:
    draft = get(db, draft_id)
    _open(draft)
    draft.status = "rejected"
    db.flush()
    events.record(db, "ai_draft", draft.id, "reject", {"task": draft.task}, source, actor=actor)
    return draft


def commit(db: Session, draft_id, source: str, actor: str | None) -> dict:
    """«ثبت»: the accepted and edited values go to the target through its module's services."""
    from app.core.time import utcnow

    draft = get(db, draft_id)
    _open(draft)
    fields = fields_of(db, draft.id)
    chosen = {f.path: f.final for f in fields if f.decision in ("accepted", "edited")}
    if not chosen:
        raise AppError("nothing_accepted", "Accept or edit at least one field before «ثبت»", status=422)
    committer = COMMITTERS.get(draft.target_type)
    if committer is None:
        raise AppError("no_committer", "BOMS cannot write this kind of draft yet", {"target_type": draft.target_type},
                       status=409)
    result = committer(db, draft, chosen, SOURCE, actor)
    for f in fields:
        if f.decision == "edited":
            db.add(Correction(task=draft.task, draft_id=draft.id, field=_generic(f.path), proposed=f.proposed,
                              final=f.final, context=f.label))
    accepted = sum(1 for f in fields if f.decision in ("accepted", "edited"))
    draft.status = "accepted" if accepted == len(fields) else "partly_accepted"
    draft.committed_at = utcnow()
    draft.result = result
    db.flush()
    events.record(db, "ai_draft", draft.id, "commit", {"task": draft.task, "target_type": draft.target_type,
                                                      "fields": len(fields), "accepted": accepted,
                                                      "edited": sum(1 for f in fields if f.decision == "edited"),
                                                      "result": result}, source, actor=actor)
    return result


def _generic(path: str) -> str:
    """``items[3].unit`` -> ``items[].unit``: corrections are reused per field kind, not per row."""
    import re

    return re.sub(r"\[\d+\]", "[]", path)


def examples(db: Session, task: str, limit: int = 8) -> str:
    """The owner's last corrections of this task, for the next prompt («examples»)."""
    rows = list(db.scalars(select(Correction).where(Correction.task == task).order_by(Correction.created_at.desc())
                           .limit(limit)))
    if not rows:
        return ""
    lines = [f"- {r.field}: proposed {json.dumps(r.proposed, ensure_ascii=False)} -> corrected to "
             f"{json.dumps(r.final, ensure_ascii=False)}" for r in rows]
    return "Earlier corrections by the owner (follow them):\n" + "\n".join(lines)


def case_cleanup(db: Session, case_id: uuid.UUID, _note: str, _source: str, _actor: str | None) -> dict:
    """The case's drafts and its AI privacy setting go with the case (the privacy log stays: it is a log)."""
    from sqlalchemy import text

    drafts = db.execute(text("DELETE FROM ai.draft WHERE case_id = :c RETURNING id"), {"c": case_id}).scalars().all()
    settings_rows = db.execute(text("DELETE FROM ai.case_setting WHERE case_id = :c RETURNING id"), {"c": case_id}).rowcount
    db.execute(text("UPDATE ai.call SET case_id = NULL WHERE case_id = :c"), {"c": case_id})
    return {"counts": {"ai_drafts": len(drafts), "ai_case_settings": settings_rows}}
