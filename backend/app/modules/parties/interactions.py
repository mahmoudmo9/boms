"""Interactions and follow-ups.

Rule "next action is mandatory": every new interaction comes with exactly one of a follow-up or a
``no_followup_reason``. Checked here (422) and again at commit by a deferred constraint trigger.
Interactions are immutable except corrections (subject/body, and party/contact/channel/direction/time under a
transaction-local flag), which are recorded as events with before/after.
"""

import re
import uuid
from datetime import date, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.text import WORD_SIMILARITY, normalize_fa
from app.core.time import ensure_aware
from app.modules.events import service as events
from app.modules.parties import clock, service
from app.modules.parties.models import Followup, Interaction


def get_interaction(db: Session, interaction_id: uuid.UUID) -> Interaction:
    row = db.get(Interaction, interaction_id)
    if row is None:
        raise NotFound("not_found", "Interaction not found")
    return row


# v0.10.1 (0.4.6): the case of each record an interaction can concern (read-only lookups)
REF_CASE_SQL = {
    "rfq_recipient": "SELECT r.case_id FROM ops.rfq_recipient rr JOIN ops.rfq r ON r.id = rr.rfq_id WHERE rr.id = :id",
    "quote": "SELECT case_id FROM ops.quote WHERE id = :id",
    "purchase_order": "SELECT case_id FROM ops.purchase_order WHERE id = :id",
    "shipment": "SELECT case_id FROM ops.shipment WHERE id = :id",
    "offer": "SELECT case_id FROM ops.supplier_offer WHERE id = :id",
}


def link_of(db: Session, case_id, ref_type: str | None, ref_id) -> tuple:
    """(case, ref type, ref id) of a new interaction: the record must exist, and it gives the case when none is given;
    a record of another case is refused."""
    from sqlalchemy import text

    if bool(ref_type) != bool(ref_id):
        raise AppError("ref_incomplete", "A linked record needs both its type and its id", status=422)
    if ref_type:
        if ref_type not in REF_CASE_SQL:
            raise AppError("invalid_ref", "Unknown record type", {"ref_type": ref_type}, status=422)
        found = db.execute(text(REF_CASE_SQL[ref_type]), {"id": ref_id}).first()
        if found is None:
            raise AppError("ref_not_found", "The linked record does not exist", {"ref_type": ref_type}, status=422)
        if case_id and found[0] and str(found[0]) != str(case_id):
            raise AppError("ref_other_case", "The linked record belongs to another case", status=422)
        case_id = case_id or found[0]
    if case_id and db.execute(text("SELECT 1 FROM ops.case WHERE id = :c"), {"c": case_id}).first() is None:
        raise AppError("case_not_found", "Case not found", status=422)
    return case_id, ref_type, ref_id


def create_interaction(db: Session, data: dict, source: str, actor: str | None = None) -> tuple[Interaction, Followup | None]:
    followup = data.get("followup")
    reason = (data.get("no_followup_reason") or "").strip() or None
    if followup and reason:
        raise AppError("next_action_conflict", "Give either a next action or a no-follow-up reason, not both",
                       status=422)
    if not followup and not reason:
        raise AppError("next_action_required", "A next action (or a reason why none is needed) is required",
                       status=422)
    party = service.get_party(db, data["party_id"])
    if data.get("contact_id"):
        contact = service.get_contact(db, data["contact_id"])
        if contact.party_id != party.id:
            raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)
    occurred_at = data.get("occurred_at") or clock.now()
    try:
        occurred_at = ensure_aware(occurred_at)
    except ValueError:
        raise AppError("naive_datetime", "occurred_at needs a timezone", status=422) from None

    case_id, ref_type, ref_id = link_of(db, data.get("case_id"), data.get("ref_type"), data.get("ref_id"))
    row = Interaction(party_id=party.id, contact_id=data.get("contact_id"), channel=data["channel"],
                      direction=data["direction"], occurred_at=occurred_at, subject=data.get("subject"),
                      body=data.get("body"), no_followup_reason=reason, case_id=case_id, ref_type=ref_type, ref_id=ref_id,
                      raw_document_id=data.get("raw_document_id"))
    db.add(row)
    db.flush()
    events.record(db, "interaction", row.id, "create", service.jsonable({
        "party_id": party.id, "channel": row.channel, "direction": row.direction, "occurred_at": occurred_at,
        "subject": row.subject, "no_followup_reason": reason, "case_id": case_id, "ref_type": ref_type, "ref_id": ref_id}),
        source, actor=actor)
    events.record(db, "party", party.id, "interaction_add", service.jsonable({"interaction_id": row.id}), source,
                  actor=actor)

    created_followup = None
    if followup:
        created_followup = _new_followup(db, party.id, row.id, followup["action"], followup["due_on"], source, actor)
    if data.get("move_stage"):
        move = data["move_stage"]
        service.change_stage(db, party.id, move["role"], move["stage"], move.get("reason"), source, actor)
    for document_id in dict.fromkeys(data.get("document_ids") or []):
        service.link_document(db, "interaction", row.id, document_id, source, actor)
    if row.raw_document_id:              # v0.10.1 (0.4.6): the .eml and its attachments, linked to the interaction
        from app.modules.parties import eml

        eml.store_attachments(db, row.raw_document_id, "interaction", row.id, source, actor)
    if row.direction in ("in", "out") and not data.get("move_stage"):   # v0.10.1 (0.4.3); an explicit move wins
        service.happened(db, f"interaction_{row.direction}", party.id, cause={"entity": "interaction", "id": str(row.id)},
                         source=source, actor=actor)
    return row, created_followup


MOVABLE = ("party_id", "contact_id", "channel", "direction", "occurred_at")


def correct_interaction(db: Session, interaction_id: uuid.UUID, changes: dict, source: str,
                        actor: str | None = None) -> Interaction:
    """Correct subject/body and, since v0.2.1, party/contact/channel/direction/time.

    The non-text columns are writable only under the transaction-local flag ``boms.interaction_edit`` (checked
    by core.interaction_guard). Moving to another party moves the follow-ups created from this interaction.
    """
    row = get_interaction(db, interaction_id)
    for field in ("party_id", "channel", "direction", "occurred_at"):
        if field in changes and changes[field] is None:
            changes.pop(field)  # not nullable: null means "unchanged"
    if "occurred_at" in changes:
        try:
            changes["occurred_at"] = ensure_aware(changes["occurred_at"])
        except ValueError:
            raise AppError("naive_datetime", "occurred_at needs a timezone", status=422) from None
    party_id = changes.get("party_id", row.party_id)
    if "party_id" in changes:
        service.get_party(db, party_id)
    contact_id = changes.get("contact_id", row.contact_id)
    if contact_id is not None and ("contact_id" in changes or party_id != row.party_id):
        if service.get_contact(db, contact_id).party_id != party_id:
            raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)

    before, after = {}, {}
    for field in ("subject", "body", *MOVABLE):
        if field in changes and getattr(row, field) != changes[field]:
            before[field] = getattr(row, field)
            after[field] = changes[field]
    if not after:
        return row
    if any(field in after for field in MOVABLE):
        db.execute(text("SELECT set_config('boms.interaction_edit', 'on', true)"))
    old_party = row.party_id
    for field, value in after.items():
        setattr(row, field, value)
    db.flush()
    moved = []
    if "party_id" in after:
        for followup in db.scalars(select(Followup).where(Followup.interaction_id == row.id,
                                                          Followup.party_id == old_party)):
            followup.party_id = party_id
            db.flush()
            events.record(db, "followup", followup.id, "move", service.jsonable(
                {"interaction_id": row.id, "old_party_id": old_party, "new_party_id": party_id}), source, actor=actor)
            moved.append(str(followup.id))
        payload = service.jsonable({"interaction_id": row.id, "old_party_id": old_party, "new_party_id": party_id})
        events.record(db, "party", old_party, "interaction_move_out", payload, source, actor=actor)
        events.record(db, "party", party_id, "interaction_move_in", payload, source, actor=actor)
    data = {"before": before, "after": after}
    if "party_id" in after:
        data["moved_followups"] = moved
    events.record(db, "interaction", row.id, "correct", service.jsonable(data), source, actor=actor)
    return row


def list_interactions(db: Session, *, party_id: uuid.UUID | None = None, channel: str | None = None,
                      date_from: datetime | None = None, date_to: datetime | None = None, q: str | None = None,
                      page: int = 1, page_size: int = 50) -> tuple[list[Interaction], int]:
    query = select(Interaction)
    if party_id:
        query = query.where(Interaction.party_id == party_id)
    if channel:
        query = query.where(Interaction.channel == channel)
    if date_from:
        query = query.where(Interaction.occurred_at >= ensure_aware(date_from))
    if date_to:
        query = query.where(Interaction.occurred_at < ensure_aware(date_to))
    condition = match_condition(db, q)
    if condition is not None:
        query = query.where(condition)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Interaction.occurred_at.desc(), Interaction.id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    return list(rows), total


FTS_EXPR = ("to_tsvector('simple', left(coalesce(core.normalize_fa(core.interaction.subject), '') || ' ' || "
            "coalesce(core.interaction.body_norm, ''), 300000))")
SUBJECT_EXPR = "core.normalize_fa(coalesce(core.interaction.subject, ''))"


def match_condition(db: Session, q: str | None):
    """Full-text prefix match on subject + body, or fuzzy match on the subject. Matches the 0004 indexes."""
    needle = normalize_fa(q or "") or ""
    tokens = re.findall(r"\w+", needle)
    if not tokens:
        return None
    db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"), {"v": str(WORD_SIMILARITY)})
    tsquery = " & ".join(f"{t}:*" for t in tokens)
    return or_(
        text(f"{FTS_EXPR} @@ to_tsquery('simple', :itsq)").bindparams(itsq=tsquery),
        text(f"{SUBJECT_EXPR} %> :isubj").bindparams(isubj=needle),
    )


# ---- follow-ups --------------------------------------------------------------------------

def get_followup(db: Session, followup_id: uuid.UUID) -> Followup:
    row = db.get(Followup, followup_id)
    if row is None:
        raise NotFound("not_found", "Follow-up not found")
    return row


def _new_followup(db: Session, party_id: uuid.UUID, interaction_id: uuid.UUID | None, action: str, due_on: date,
                  source: str, actor: str | None) -> Followup:
    action = action.strip()
    if not action:
        raise AppError("action_required", "The follow-up needs an action", status=422)
    row = Followup(party_id=party_id, interaction_id=interaction_id, action=action, due_on=due_on, status="open")
    db.add(row)
    db.flush()
    events.record(db, "followup", row.id, "create", service.jsonable({
        "party_id": party_id, "interaction_id": interaction_id, "action": action, "due_on": due_on}),
        source, actor=actor)
    return row


def create_followup(db: Session, data: dict, source: str, actor: str | None = None) -> Followup:
    service.get_party(db, data["party_id"])
    if data.get("interaction_id"):
        interaction = get_interaction(db, data["interaction_id"])
        if interaction.party_id != data["party_id"]:
            raise AppError("interaction_not_of_party", "The interaction belongs to another party", status=422)
    return _new_followup(db, data["party_id"], data.get("interaction_id"), data["action"], data["due_on"],
                         source, actor)


def _open(db: Session, followup_id: uuid.UUID) -> Followup:
    row = get_followup(db, followup_id)
    if row.status != "open":
        raise Conflict("followup_not_open", f"The follow-up is already {row.status}", {"status": row.status})
    return row


def complete_followup(db: Session, followup_id: uuid.UUID, note: str | None, next_spec: dict | None, source: str,
                      actor: str | None = None) -> tuple[Followup, Followup | None]:
    row = _open(db, followup_id)
    row.status = "done"
    row.done_at = clock.now()
    row.done_note = (note or "").strip() or None
    db.flush()
    events.record(db, "followup", row.id, "done", {"note": row.done_note}, source, actor=actor)
    created = None
    if next_spec:
        created = _new_followup(db, row.party_id, row.interaction_id, next_spec["action"], next_spec["due_on"],
                                source, actor)
    return row, created


def reschedule_followup(db: Session, followup_id: uuid.UUID, due_on: date, note: str | None, source: str,
                        actor: str | None = None) -> Followup:
    row = _open(db, followup_id)
    old = row.due_on
    if old != due_on:
        row.due_on = due_on
        db.flush()
        events.record(db, "followup", row.id, "reschedule",
                      {"old_due_on": old.isoformat(), "new_due_on": due_on.isoformat(), "note": note}, source,
                      actor=actor)
    return row


def cancel_followup(db: Session, followup_id: uuid.UUID, note: str, source: str, actor: str | None = None) -> Followup:
    note = (note or "").strip()
    if not note:
        raise AppError("note_required", "Cancelling a follow-up needs a note", status=422)
    row = _open(db, followup_id)
    row.status = "cancelled"
    row.done_at = clock.now()
    row.done_note = note
    db.flush()
    events.record(db, "followup", row.id, "cancel", {"note": note}, source, actor=actor)
    return row


def open_followups_of_interactions(db: Session, interaction_ids: list[uuid.UUID]) -> list[Followup]:
    """Open follow-ups attached to these interactions (used by sourcing to cancel chases of deleted RFQs)."""
    if not interaction_ids:
        return []
    return list(db.scalars(select(Followup).where(Followup.interaction_id.in_(interaction_ids),
                                                  Followup.status == "open").order_by(Followup.created_at)))


def list_followups(db: Session, *, status: str | None = "open", party_id: uuid.UUID | None = None,
                   due_from: date | None = None, due_to: date | None = None,
                   page: int = 1, page_size: int = 100) -> tuple[list[Followup], int]:
    query = select(Followup)
    if status:
        query = query.where(Followup.status == status)
    if party_id:
        query = query.where(Followup.party_id == party_id)
    if due_from:
        query = query.where(Followup.due_on >= due_from)
    if due_to:
        query = query.where(Followup.due_on <= due_to)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Followup.due_on, Followup.created_at).offset((page - 1) * page_size)
                      .limit(page_size))
    return list(rows), total


# ---- v0.10.1 (0.4.6): the case thread «مکاتبات» ------------------------------------------------------------------

CASE_THREAD_SQL = """
    SELECT i.id, i.party_id, i.contact_id, i.channel, i.direction, i.occurred_at, i.subject, left(i.body, 400) AS excerpt,
           i.ref_type, i.ref_id, i.raw_document_id, p.name_fa AS party_name_fa, p.name_en AS party_name_en,
           c.name_fa AS contact_name_fa, c.name_en AS contact_name_en,
           CASE i.ref_type
             WHEN 'rfq_recipient' THEN (SELECT r.code FROM ops.rfq_recipient rr JOIN ops.rfq r ON r.id = rr.rfq_id WHERE rr.id = i.ref_id)
             WHEN 'quote' THEN (SELECT number FROM ops.quote WHERE id = i.ref_id)
             WHEN 'purchase_order' THEN (SELECT number FROM ops.purchase_order WHERE id = i.ref_id)
             WHEN 'shipment' THEN (SELECT code FROM ops.shipment WHERE id = i.ref_id)
           END AS ref_code
    FROM core.interaction i JOIN core.party p ON p.id = i.party_id LEFT JOIN core.contact c ON c.id = i.contact_id
    WHERE i.case_id = :case {party}
    ORDER BY i.occurred_at DESC, i.created_at DESC
"""


def case_thread(db: Session, case_id: uuid.UUID, party_id: uuid.UUID | None = None) -> dict:
    """Every incoming and outgoing interaction of the case, newest first, with the record it concerns and its files;
    the parties of the thread for the filter."""
    from sqlalchemy import text

    rows = db.execute(text(CASE_THREAD_SQL.format(party="AND i.party_id = :party" if party_id else "")),
                      {"case": case_id, **({"party": party_id} if party_id else {})}).all()
    files = {}
    if rows:
        for f in db.execute(text("""SELECT l.entity_id, d.id, d.title, d.original_filename, d.mime_type, d.size_bytes, l.role
                                    FROM core.document_link l JOIN core.document d ON d.id = l.document_id
                                    WHERE l.entity_type = 'interaction' AND l.entity_id = ANY(:ids)"""),
                            {"ids": [str(r.id) for r in rows]}):
            files.setdefault(f.entity_id, []).append({"id": f.id, "title": f.title, "filename": f.original_filename,
                                                     "mime_type": f.mime_type, "size": f.size_bytes, "role": f.role})
    parties = db.execute(text("""SELECT DISTINCT p.id, p.name_fa, p.name_en FROM core.interaction i JOIN core.party p ON p.id = i.party_id
                                 WHERE i.case_id = :case ORDER BY p.name_en NULLS LAST, p.name_fa"""), {"case": case_id}).all()
    return service.jsonable({"items": [{**dict(r._mapping), "files": files.get(str(r.id), [])} for r in rows],
                             "parties": [dict(p._mapping) for p in parties]})
