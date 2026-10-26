"""Inquiries, go/no-go decisions and cases (reference flow stages 1-2).

Conversion gate: a decision must exist; any hard check 'no' blocks (409 hard_check_failed); red blocks (the
inquiry is rejected); yellow needs ``confirmed``. Converting sets ``case_id`` on the inquiry's own item rows.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.text import WORD_SIMILARITY, normalize_fa
from app.core.time import ensure_aware
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.parties import interactions as party_interactions
from app.modules.parties import service as parties
from app.modules.sourcing import items as items_service
from app.modules.sourcing.common import diff, document_count, flush, jsonable, row_snapshot
from app.modules.sourcing.models import (
    Case,
    Decision,
    Inquiry,
    LineItem,
    OfferItem,
    PaymentTerm,
    Rfq,
    RfqItem,
    RfqRecipient,
    SupplierOffer,
)

HARD_CHECKS = ("feasible_sourcing", "exposure_acceptable", "requirements_ok")
INTERACTION_TO_INQUIRY_CHANNEL = {"whatsapp": "whatsapp", "call": "phone", "email": "email",
                                  "tender_portal": "tender_portal", "in_person": "in_person", "other": "other"}


def _aware(value: datetime | None) -> datetime:
    try:
        return ensure_aware(value or clock.now())
    except ValueError:
        raise AppError("naive_datetime", "The time needs a timezone", status=422) from None


# ---- inquiries --------------------------------------------------------------------------------

def get_inquiry(db: Session, inquiry_id: uuid.UUID) -> Inquiry:
    row = db.get(Inquiry, inquiry_id)
    if row is None:
        raise NotFound("not_found", "Inquiry not found")
    return row


def prefill_from_interaction(db: Session, interaction_id: uuid.UUID) -> dict:
    """Values for "Create inquiry from this interaction" (nothing is stored)."""
    interaction = party_interactions.get_interaction(db, interaction_id)
    return {"party_id": interaction.party_id, "source_channel": INTERACTION_TO_INQUIRY_CHANNEL[interaction.channel],
            "received_at": interaction.occurred_at, "subject": interaction.subject, "raw_text": interaction.body,
            "source_interaction_id": interaction.id}


def create_inquiry(db: Session, data: dict, source: str, actor: str | None = None) -> Inquiry:
    items = data.pop("items", [])
    document_ids = data.pop("document_ids", [])
    if data.get("party_id"):
        parties.get_party(db, data["party_id"])
    if data.get("source_interaction_id"):
        party_interactions.get_interaction(db, data["source_interaction_id"])
    data["received_at"] = _aware(data.get("received_at"))
    for key in ("subject",):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip() or None
    row = Inquiry(**data)
    db.add(row)
    flush(db, "invalid_inquiry")
    events.record(db, "inquiry", row.id, "create", jsonable({
        "party_id": row.party_id, "source_channel": row.source_channel, "kind": row.kind, "subject": row.subject,
        "source_interaction_id": row.source_interaction_id, "items": len(items)}), source, actor=actor)
    if row.party_id:
        events.record(db, "party", row.party_id, "inquiry_add", jsonable({"inquiry_id": row.id}), source, actor=actor)
    if items:
        items_service.add_items(db, row.id, None, items, source, actor)
    for document_id in dict.fromkeys(document_ids):
        parties.link_document(db, "inquiry", row.id, document_id, source, actor)
    return row


def update_inquiry(db: Session, inquiry_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Inquiry:
    row = get_inquiry(db, inquiry_id)
    if row.status in ("converted", "rejected") and "status" in changes:
        raise Conflict("inquiry_closed", f"The inquiry is {row.status}", {"status": row.status})
    if changes.get("party_id"):
        parties.get_party(db, changes["party_id"])
    if "received_at" in changes:
        if changes["received_at"] is None:
            changes.pop("received_at")
        else:
            changes["received_at"] = _aware(changes["received_at"])
    for key in ("source_channel", "kind", "status"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    changed = diff(row, changes)
    if changed:
        flush(db, "invalid_inquiry")
        events.record(db, "inquiry", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return row


def reject_inquiry(db: Session, inquiry_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> Inquiry:
    row = get_inquiry(db, inquiry_id)
    if row.status == "converted":
        raise Conflict("inquiry_closed", "The inquiry is already converted to a case", {"status": row.status})
    reason = reason.strip()
    if not reason:
        raise AppError("reason_required", "A reason is required", status=422)
    old = row.status
    row.status, row.reject_reason = "rejected", reason
    flush(db, "invalid_inquiry")
    events.record(db, "inquiry", row.id, "reject", {"old_status": old, "reason": reason}, source, actor=actor)
    return row


def list_inquiries(db: Session, *, q: str | None = None, status: str | None = None, party_id: uuid.UUID | None = None,
                   page: int = 1, page_size: int = 50) -> tuple[list[Inquiry], int]:
    query = select(Inquiry)
    if status:
        query = query.where(Inquiry.status == status)
    if party_id:
        query = query.where(Inquiry.party_id == party_id)
    condition = match_condition(db, q)
    if condition is not None:
        query = query.where(condition)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Inquiry.received_at.desc(), Inquiry.id.desc())
                      .offset((page - 1) * page_size).limit(page_size))
    return list(rows), total


def match_condition(db: Session, q: str | None):
    needle = normalize_fa(q or "") or ""
    tokens = [t for t in needle.replace("‌", " ").split() if t]
    if not tokens:
        return None
    db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"), {"v": str(WORD_SIMILARITY)})
    import re

    words = [w for t in tokens for w in re.findall(r"\w+", t)]
    if not words:
        return None
    tsquery = " & ".join(f"{w}:*" for w in words)
    return or_(
        text("to_tsvector('simple', left(ops.inquiry.search_norm, 300000)) @@ to_tsquery('simple', :inq_tsq)")
        .bindparams(inq_tsq=tsquery),
        text("core.normalize_fa(coalesce(ops.inquiry.subject, '')) %> :inq_subj").bindparams(inq_subj=needle),
    )


def delete_inquiry(db: Session, inquiry_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Only before conversion and without attached documents; its items and decision go with it."""
    row = get_inquiry(db, inquiry_id)
    case = db.scalar(select(Case).where(Case.inquiry_id == row.id))
    item_rows = items_service.items_of(db, inquiry_id=row.id)
    counts = {"cases": 1 if case else 0,
              "documents": document_count(db, "inquiry", [row.id]) + document_count(db, "line_item", [i.id for i in item_rows])}
    if any(counts.values()):
        raise Conflict("in_use", "The inquiry has a case or documents", counts)
    decision = db.scalar(select(Decision).where(Decision.inquiry_id == row.id))
    snapshot = {"inquiry": row_snapshot(row), "items": [row_snapshot(i) for i in item_rows],
                "decision": row_snapshot(decision) if decision else None}
    for item in item_rows:
        db.delete(item)
    if decision:
        db.delete(decision)
    db.flush()
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "inquiry", inquiry_id, "delete", {"deleted": snapshot}, source, actor=actor)


def _unlink_all(db: Session, entity_type: str, ids: list, source: str, actor: str | None) -> list[dict]:
    """Remove the document links of these rows (the files stay); return them for the snapshot."""
    links = parties.linked_documents(db, entity_type, [str(i) for i in ids])
    for link in links:
        parties.unlink_document(db, entity_type, link["entity_id"], link["link_id"], source, actor)
    return jsonable(links)


def cascade_delete_inquiry(db: Session, inquiry_id: uuid.UUID, confirm_subject: str | None, source: str,
                           actor: str | None = None) -> dict:
    """Test-data cleanup: an inquiry WITHOUT a case, with its items, decision and document links (files stay).

    Needs the exact subject (or the literal ``DELETE`` when it has none). The source interaction stays.
    """
    row = get_inquiry(db, inquiry_id)
    if case_of(db, row.id) is not None:
        raise Conflict("in_use", "The inquiry has a case; delete the case first", {"cases": 1})
    expected = (row.subject or "").strip() or "DELETE"
    if (confirm_subject or "").strip() != expected:
        raise AppError("confirm_subject_mismatch", "Type the exact inquiry subject to confirm", status=422)
    item_rows = items_service.items_of(db, inquiry_id=row.id)
    decision = get_decision(db, row.id)
    snapshot = {"inquiry": row_snapshot(row), "items": [row_snapshot(i) for i in item_rows],
                "decision": row_snapshot(decision) if decision else None}
    snapshot["document_links"] = (_unlink_all(db, "inquiry", [row.id], source, actor)
                                  + _unlink_all(db, "line_item", [i.id for i in item_rows], source, actor))
    for item in item_rows:
        db.delete(item)
    if decision:
        db.delete(decision)
    flush(db, "in_use")
    db.delete(row)
    flush(db, "in_use")
    counts = {"items": len(item_rows), "documents": len(snapshot["document_links"])}
    events.record(db, "inquiry", inquiry_id, "delete", {"cascade": True, "counts": counts, "deleted": snapshot},
                  source, actor=actor)
    return counts


CASE_DELETED_NOTE = "case deleted"


def cascade_delete_case(db: Session, case_id: uuid.UUID, confirm_title: str | None, source: str,
                        actor: str | None = None) -> dict:
    """Test-data cleanup: the case with its line items, RFQs, recipients, offers, offer items and document links.

    Needs the exact title. Files and interactions (from sends/offers) stay; the inquiry, if any, stays. Open
    follow-ups of those interactions (the RFQ chases) are cancelled with the note "case deleted".
    """
    case = get_case(db, case_id)
    if (confirm_title or "").strip() != case.title.strip():
        raise AppError("confirm_title_mismatch", "Type the exact case title to confirm", status=422)
    item_rows = list(db.scalars(select(LineItem).where(LineItem.case_id == case.id)))
    rfqs = list(db.scalars(select(Rfq).where(Rfq.case_id == case.id)))
    rfq_ids = [r.id for r in rfqs]
    rfq_item_rows = list(db.scalars(select(RfqItem).where(RfqItem.rfq_id.in_(rfq_ids)))) if rfq_ids else []
    recipients = list(db.scalars(select(RfqRecipient).where(RfqRecipient.rfq_id.in_(rfq_ids)))) if rfq_ids else []
    offer_rows = list(db.scalars(select(SupplierOffer).where(SupplierOffer.case_id == case.id)))
    offer_ids = [o.id for o in offer_rows]
    offer_item_rows = (list(db.scalars(select(OfferItem).where(OfferItem.offer_id.in_(offer_ids))))
                       if offer_ids else [])
    snapshot = {
        "case": row_snapshot(case), "items": [row_snapshot(i) for i in item_rows],
        "rfqs": [row_snapshot(r) for r in rfqs], "rfq_items": [row_snapshot(r) for r in rfq_item_rows],
        "recipients": [row_snapshot(r) for r in recipients],
        "offers": [row_snapshot(o, skip=("raw_norm",)) for o in offer_rows],
        "offer_items": [row_snapshot(o) for o in offer_item_rows],
    }
    snapshot["document_links"] = (_unlink_all(db, "case", [case.id], source, actor)
                                  + _unlink_all(db, "line_item", [i.id for i in item_rows], source, actor)
                                  + _unlink_all(db, "offer", offer_ids, source, actor))
    # open follow-ups created by "mark as sent" / recording an offer of the deleted rows (v0.3.2)
    interaction_ids = [r.interaction_id for r in recipients if r.interaction_id] + \
        [o.interaction_id for o in offer_rows if o.interaction_id]
    cancelled = [party_interactions.cancel_followup(db, f.id, CASE_DELETED_NOTE, source, actor).id
                 for f in party_interactions.open_followups_of_interactions(db, list(dict.fromkeys(interaction_ids)))]
    snapshot["cancelled_followups"] = jsonable(cancelled)
    for item in item_rows:
        item.selected_offer_item_id = None
    for offer in offer_rows:
        offer.superseded_by_id = None
    flush(db, "in_use")
    for group in (offer_item_rows, offer_rows, rfq_item_rows, recipients, rfqs, item_rows):
        for row in group:
            db.delete(row)
        flush(db, "in_use")
    db.delete(case)
    flush(db, "in_use")
    counts = {"items": len(item_rows), "rfqs": len(rfqs), "recipients": len(recipients), "offers": len(offer_rows),
              "offer_items": len(offer_item_rows), "documents": len(snapshot["document_links"]),
              "followups_cancelled": len(cancelled)}
    events.record(db, "case", case_id, "delete", {"cascade": True, "counts": counts, "deleted": snapshot}, source,
                  actor=actor)
    return counts


# ---- decision -----------------------------------------------------------------------------------

def case_of(db: Session, inquiry_id: uuid.UUID) -> Case | None:
    return db.scalar(select(Case).where(Case.inquiry_id == inquiry_id))


def get_decision(db: Session, inquiry_id: uuid.UUID) -> Decision | None:
    return db.scalar(select(Decision).where(Decision.inquiry_id == inquiry_id))


def _check_payment_term(db: Session, code: str | None, reason: str | None) -> None:
    if not code:
        return
    term = db.get(PaymentTerm, code)
    if term is None:
        raise AppError("unknown_payment_term", "Unknown payment term", {"payment_term": code}, status=422)
    if term.requires_reason and not (reason or "").strip():
        raise AppError("ordering_before_payment_reason_required",
                       "Ordering before payment needs an explicit approval line", status=422)


def set_decision(db: Session, inquiry_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> Decision:
    """Create or replace the inquiry's current decision; the history is in the events."""
    inquiry = get_inquiry(db, inquiry_id)
    if inquiry.status == "converted":
        raise Conflict("inquiry_closed", "The inquiry is already converted to a case", {"status": inquiry.status})
    _check_payment_term(db, data.get("payment_term"), data.get("ordering_before_payment_reason"))
    if data.get("exposure_estimate") is not None and not data.get("exposure_currency"):
        raise AppError("currency_required", "The exposure estimate needs a currency", status=422)
    if data["light"] != "yellow":
        data["confirmed"] = False
    decision = get_decision(db, inquiry_id)
    before = row_snapshot(decision) if decision else None
    if decision is None:
        decision = Decision(inquiry_id=inquiry_id, **data)
        db.add(decision)
    else:
        for key, value in data.items():
            setattr(decision, key, value)
    flush(db, "invalid_decision")
    if data["light"] == "red":
        old = inquiry.status
        inquiry.status, inquiry.reject_reason = "rejected", data["reason"]
        flush(db, "invalid_inquiry")
        events.record(db, "inquiry", inquiry.id, "reject", {"old_status": old, "reason": data["reason"],
                                                           "by_decision": True}, source, actor=actor)
    elif inquiry.status == "rejected":
        inquiry.status, inquiry.reject_reason = "ready_for_screening", None
        flush(db, "invalid_inquiry")
    elif inquiry.status in ("new", "needs_info"):
        inquiry.status = "ready_for_screening"
        flush(db, "invalid_inquiry")
    events.record(db, "inquiry", inquiry.id, "decision",
                  jsonable({"before": before, "after": row_snapshot(decision)}), source, actor=actor)
    return decision


def gate(db: Session, inquiry: Inquiry) -> dict:
    """Can the inquiry become a case? {ok, code, details} with the first blocking reason."""
    if inquiry.status == "converted":
        return {"ok": False, "code": "already_converted", "details": {}}
    decision = get_decision(db, inquiry.id)
    if decision is None:
        return {"ok": False, "code": "decision_required", "details": {}}
    failing = [c for c in HARD_CHECKS if getattr(decision, c) == "no"]
    if failing:
        return {"ok": False, "code": "hard_check_failed", "details": {"checks": failing}}
    if decision.light == "red":
        return {"ok": False, "code": "decision_red", "details": {"reason": decision.reason}}
    if decision.light == "yellow" and not decision.confirmed:
        return {"ok": False, "code": "confirmation_required", "details": {}}
    return {"ok": True, "code": None, "details": {}}


def convert(db: Session, inquiry_id: uuid.UUID, title: str | None, source: str, actor: str | None = None) -> Case:
    inquiry = get_inquiry(db, inquiry_id)
    result = gate(db, inquiry)
    if not result["ok"]:
        raise Conflict(result["code"], "The inquiry cannot be converted", result["details"])
    decision = get_decision(db, inquiry.id)
    item_rows = items_service.items_of(db, inquiry_id=inquiry.id)
    title = (title or "").strip() or inquiry.subject or (item_rows[0].name if item_rows else None) or "Case"
    case = Case(inquiry_id=inquiry.id, party_id=inquiry.party_id, title=title, payment_term=decision.payment_term,
                ordering_before_payment_reason=decision.ordering_before_payment_reason,
                exposure_estimate=decision.exposure_estimate, exposure_currency=decision.exposure_currency)
    db.add(case)
    flush(db, "invalid_case")
    for item in item_rows:
        item.case_id = case.id
    old = inquiry.status
    inquiry.status = "converted"
    flush(db, "invalid_inquiry")
    events.record(db, "case", case.id, "create", jsonable({
        "inquiry_id": inquiry.id, "party_id": case.party_id, "title": title, "items": [str(i.id) for i in item_rows],
        "decision": {"light": decision.light, "confirmed": decision.confirmed}}), source, actor=actor)
    events.record(db, "inquiry", inquiry.id, "convert", jsonable({"case_id": case.id, "old_status": old}), source,
                  actor=actor)
    if case.party_id:
        events.record(db, "party", case.party_id, "case_add", jsonable({"case_id": case.id}), source, actor=actor)
    return case


# ---- cases --------------------------------------------------------------------------------------

def get_case(db: Session, case_id: uuid.UUID) -> Case:
    row = db.get(Case, case_id)
    if row is None:
        raise NotFound("not_found", "Case not found")
    return row


def create_case(db: Session, data: dict, source: str, actor: str | None = None) -> Case:
    if data.get("party_id"):
        parties.get_party(db, data["party_id"])
    _check_payment_term(db, data.get("payment_term"), data.get("ordering_before_payment_reason"))
    data["title"] = data["title"].strip()
    if not data["title"]:
        raise AppError("title_required", "The case needs a title", status=422)
    case = Case(**data)
    db.add(case)
    flush(db, "invalid_case")
    events.record(db, "case", case.id, "create", jsonable({k: v for k, v in data.items() if v is not None}), source,
                  actor=actor)
    if case.party_id:
        events.record(db, "party", case.party_id, "case_add", jsonable({"case_id": case.id}), source, actor=actor)
    return case


def update_case(db: Session, case_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Case:
    case = get_case(db, case_id)
    if changes.get("party_id"):
        parties.get_party(db, changes["party_id"])
    for key in ("title", "status"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise AppError("title_required", "The case needs a title", status=422)
    term = changes.get("payment_term", case.payment_term)
    reason = changes.get("ordering_before_payment_reason", case.ordering_before_payment_reason)
    _check_payment_term(db, term, reason)
    changed = diff(case, changes)
    if changed:
        flush(db, "invalid_case")
        events.record(db, "case", case.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return case


def case_dependency_counts(db: Session, case_id: uuid.UUID) -> dict[str, int]:
    item_ids = [i.id for i in db.scalars(select(LineItem).where(LineItem.case_id == case_id))]
    return {
        "items": len(item_ids),
        "rfqs": db.scalar(select(func.count()).select_from(Rfq).where(Rfq.case_id == case_id)) or 0,
        "offers": db.scalar(select(func.count()).select_from(SupplierOffer).where(SupplierOffer.case_id == case_id)) or 0,
        "documents": document_count(db, "case", [case_id]) + document_count(db, "line_item", item_ids),
    }


def delete_case(db: Session, case_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Only an empty case (no items, RFQs, offers, documents) that did not come from an inquiry; else cancel it."""
    case = get_case(db, case_id)
    counts = case_dependency_counts(db, case_id)
    if case.inquiry_id:
        counts["inquiry"] = 1
    if any(counts.values()):
        raise Conflict("in_use", "The case has items, RFQs, offers or documents; cancel it instead", counts)
    snapshot = row_snapshot(case)
    db.delete(case)
    flush(db, "in_use")
    events.record(db, "case", case_id, "delete", {"deleted": snapshot}, source, actor=actor)


def list_cases(db: Session, *, q: str | None = None, status: str | None = None, party_id: uuid.UUID | None = None,
               page: int = 1, page_size: int = 50) -> tuple[list[Case], int]:
    query = select(Case)
    if status:
        query = query.where(Case.status == status)
    if party_id:
        query = query.where(Case.party_id == party_id)
    needle = normalize_fa(q or "") or ""
    if needle:
        db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"),
                   {"v": str(WORD_SIMILARITY)})
        like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(Case.title_norm.like(like), text('ops."case".title_norm %> :case_q')
                                .bindparams(case_q=needle)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Case.updated_at.desc(), Case.id.desc()).offset((page - 1) * page_size)
                      .limit(page_size))
    return list(rows), total


def payment_terms(db: Session) -> list[PaymentTerm]:
    return list(db.scalars(select(PaymentTerm).order_by(PaymentTerm.sort_order)))
