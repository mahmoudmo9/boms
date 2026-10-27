"""Supplier offers (responses to RFQs, or unsolicited).

Recording an offer creates an INCOMING interaction for the supplier (parties public service, with the Phase 3
next-action rule), recomputes the offered items' status, marks the RFQ recipient ``replied`` and updates the
RFQ status. A newer offer can supersede an older one of the same supplier; the old one stays visible.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.time import ensure_aware
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.parties import interactions as party_interactions
from app.modules.parties import service as parties
from app.modules.sourcing import items as items_service
from app.modules.sourcing import rfq as rfq_service
from app.modules.sourcing.common import diff, document_count, flush, jsonable, row_snapshot
from app.modules.sourcing.inquiries import get_case
from app.modules.sourcing.models import OfferItem, Rfq, RfqRecipient, SupplierOffer

CHANNEL_TO_INTERACTION = {"email": "email", "whatsapp": "whatsapp", "wechat": "other", "phone": "call",
                          "letter": "other", "other": "other"}
ITEM_FIELDS = ("available", "unit_price", "price_per_quantity", "unit_code", "unit_text", "moq", "moq_unit",
               "lead_time_days", "spec_deviation", "packaging", "notes")
HEADER_FIELDS = ("contact_id", "received_at", "channel", "valid_until", "currency", "incoterm", "incoterm_place",
                 "payment_terms", "lead_time_days", "compliance_notes", "notes")


def get_offer(db: Session, offer_id: uuid.UUID) -> SupplierOffer:
    row = db.get(SupplierOffer, offer_id)
    if row is None:
        raise NotFound("not_found", "Offer not found")
    return row


def get_offer_item(db: Session, offer_item_id: uuid.UUID) -> OfferItem | None:
    return db.get(OfferItem, offer_item_id)


def offer_items(db: Session, offer_id: uuid.UUID) -> list[OfferItem]:
    return list(db.scalars(select(OfferItem).where(OfferItem.offer_id == offer_id).order_by(OfferItem.created_at)))


def is_valid(offer: SupplierOffer, today: date | None = None) -> bool:
    """Counts as a valid offer: active and not past valid_until."""
    today = today or clock.today()
    return offer.status == "active" and (offer.valid_until is None or offer.valid_until >= today)


def _match_recipient(db: Session, case_id: uuid.UUID, party_id: uuid.UUID, recipient_id: uuid.UUID | None):
    if recipient_id:
        recipient = rfq_service.get_recipient(db, recipient_id)
        rfq = rfq_service.get_rfq(db, recipient.rfq_id)
        if rfq.case_id != case_id or recipient.party_id != party_id:
            raise AppError("recipient_mismatch", "The RFQ recipient is another supplier or case", status=422)
        if recipient.status == "draft":  # v0.4.0: was a 500 (a sent date is required before "replied")
            raise AppError("recipient_not_sent", "Mark the RFQ as sent to this supplier first, or record the offer "
                           "without an RFQ", {"recipient_id": str(recipient.id)}, status=422)
        return recipient
    candidates = db.scalars(select(RfqRecipient).join(Rfq, Rfq.id == RfqRecipient.rfq_id).where(
        Rfq.case_id == case_id, RfqRecipient.party_id == party_id,
        RfqRecipient.status.in_(("sent", "no_response")))).all()
    return candidates[0] if len(candidates) == 1 else None


def _check_items(db: Session, case_id: uuid.UUID, rows: list[dict]) -> None:
    seen = set()
    for row in rows:
        item = items_service.get_item(db, row["line_item_id"])
        if item.case_id != case_id:
            raise AppError("item_not_of_case", "The item belongs to another case",
                           {"item_id": str(row["line_item_id"])}, status=422)
        if row["line_item_id"] in seen:
            raise AppError("duplicate_item", "An item appears twice in the offer", status=422)
        seen.add(row["line_item_id"])
        if row.get("available", True) and row.get("unit_price") is None:
            raise AppError("price_required", "An available item needs a unit price",
                           {"item_id": str(row["line_item_id"])}, status=422)


def record_offer(db: Session, data: dict, source: str, actor: str | None = None) -> SupplierOffer:
    case = get_case(db, data["case_id"])
    party = parties.get_party(db, data["party_id"])
    if data.get("contact_id") and parties.get_contact(db, data["contact_id"]).party_id != party.id:
        raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)
    rows = data.get("items") or []
    if not rows:
        raise AppError("items_required", "An offer needs at least one item row", status=422)
    _check_items(db, case.id, rows)
    recipient = _match_recipient(db, case.id, party.id, data.get("rfq_recipient_id"))
    previous = None
    if data.get("supersedes_offer_id"):
        previous = get_offer(db, data["supersedes_offer_id"])
        if previous.case_id != case.id or previous.party_id != party.id:
            raise AppError("supersede_mismatch", "Only an offer of the same supplier and case can be superseded",
                           status=422)
        if previous.status != "active":
            raise Conflict("offer_not_active", f"The previous offer is {previous.status}", {"status": previous.status})
    try:
        received_at = ensure_aware(data.get("received_at") or clock.now())
    except ValueError:
        raise AppError("naive_datetime", "received_at needs a timezone", status=422) from None

    # incoming interaction first: it enforces the follow-up / no-follow-up rule
    subject = "WeChat" if data["channel"] == "wechat" else f"Offer: {case.title}"
    body = data.get("raw_text") or data.get("notes") or subject
    interaction, _ = party_interactions.create_interaction(db, {
        "party_id": party.id, "contact_id": data.get("contact_id"), "channel": CHANNEL_TO_INTERACTION[data["channel"]],
        "direction": "in", "occurred_at": received_at, "subject": subject, "body": body,
        "followup": data.get("followup"), "no_followup_reason": data.get("no_followup_reason")}, source, actor)

    offer = SupplierOffer(case_id=case.id, party_id=party.id, rfq_recipient_id=recipient.id if recipient else None,
                          received_at=received_at, interaction_id=interaction.id, raw_text=data.get("raw_text"),
                          **{k: data.get(k) for k in HEADER_FIELDS if k != "received_at"})
    db.add(offer)
    flush(db, "invalid_offer")
    for row in rows:
        db.add(OfferItem(offer_id=offer.id, line_item_id=row["line_item_id"],
                         **{k: row[k] for k in ITEM_FIELDS if row.get(k) is not None}))
    flush(db, "invalid_offer")
    events.record(db, "offer", offer.id, "create", jsonable({
        "case_id": case.id, "party_id": party.id, "currency": offer.currency, "incoterm": offer.incoterm,
        "valid_until": offer.valid_until, "rfq_recipient_id": offer.rfq_recipient_id, "interaction_id": interaction.id,
        "items": [{k: row.get(k) for k in ("line_item_id", "available", "unit_price", "price_per_quantity")}
                  for row in rows]}), source, actor=actor)
    events.record(db, "case", case.id, "offer_add", jsonable({"offer_id": offer.id, "party_id": party.id}), source,
                  actor=actor)

    if recipient is not None and recipient.status in ("sent", "no_response"):
        rfq_service.set_recipient_status(db, recipient, "replied", source, actor, f"offer {offer.id}")
        rfq_service.refresh_status(db, rfq_service.get_rfq(db, recipient.rfq_id), source, actor)
    if previous is not None:
        previous.status, previous.superseded_by_id = "superseded", offer.id
        flush(db, "invalid_offer")
        events.record(db, "offer", previous.id, "superseded", jsonable({"superseded_by": offer.id}), source,
                      actor=actor)
    affected = [row["line_item_id"] for row in rows]
    if previous is not None:
        affected += [r.line_item_id for r in offer_items(db, previous.id)]
    items_service.recompute_items(db, affected, source, actor)
    for document_id in dict.fromkeys(data.get("document_ids") or []):
        parties.link_document(db, "offer", offer.id, document_id, source, actor)
    return offer


def update_offer(db: Session, offer_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> SupplierOffer:
    offer = get_offer(db, offer_id)
    if changes.get("contact_id") and parties.get_contact(db, changes["contact_id"]).party_id != offer.party_id:
        raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)
    if "received_at" in changes:
        if changes["received_at"] is None:
            changes.pop("received_at")
        else:
            changes["received_at"] = ensure_aware(changes["received_at"])
    for key in ("channel", "currency"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    changed = diff(offer, {k: v for k, v in changes.items() if k in HEADER_FIELDS})
    if changed:
        flush(db, "invalid_offer")
        events.record(db, "offer", offer.id, "update", jsonable({"changes": changed}), source, actor=actor)
        if "valid_until" in changed:
            items_service.recompute_items(db, [r.line_item_id for r in offer_items(db, offer.id)], source, actor)
    return offer


def update_offer_item(db: Session, offer_item_id: uuid.UUID, changes: dict, source: str,
                      actor: str | None = None) -> OfferItem:
    row = db.get(OfferItem, offer_item_id)
    if row is None:
        raise NotFound("not_found", "Offer item not found")
    if "price_per_quantity" in changes and changes["price_per_quantity"] is None:
        changes.pop("price_per_quantity")
    if "available" in changes and changes["available"] is None:
        changes.pop("available")
    changed = diff(row, {k: v for k, v in changes.items() if k in ITEM_FIELDS})
    if changed:
        flush(db, "invalid_offer")
        events.record(db, "offer", row.offer_id, "item_update",
                      jsonable({"offer_item_id": row.id, "line_item_id": row.line_item_id, "changes": changed}),
                      source, actor=actor)
        items_service.recompute_items(db, [row.line_item_id], source, actor)
    return row


def set_offer_status(db: Session, offer_id: uuid.UUID, status: str, note: str | None, source: str,
                     actor: str | None = None) -> SupplierOffer:
    offer = get_offer(db, offer_id)
    if offer.status != status:
        old = offer.status
        offer.status = status
        flush(db, "invalid_offer")
        events.record(db, "offer", offer.id, "status", {"old_status": old, "new_status": status, "note": note},
                      source, actor=actor)
        # reactivation recomputes too; a lost selection is NOT restored
        items_service.recompute_items(db, [r.line_item_id for r in offer_items(db, offer.id)], source, actor)
    return offer


def delete_offer(db: Session, offer_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Only when nothing supersedes it and no document is attached. A selection of one of its rows is cleared
    (event ``selection_lost``, cause ``deleted``) and the items' status is recomputed."""
    offer = get_offer(db, offer_id)
    rows = offer_items(db, offer.id)
    counts = {
        "superseded_offers": len(db.scalars(select(SupplierOffer.id).where(
            SupplierOffer.superseded_by_id == offer.id)).all()),
        "documents": document_count(db, "offer", [offer.id]),
    }
    if any(counts.values()):
        raise Conflict("in_use", "The offer is selected, superseding another offer or has documents; withdraw it",
                       counts)
    snapshot = {"offer": row_snapshot(offer, skip=("raw_norm",)), "items": [row_snapshot(r) for r in rows]}
    items_service.recompute_items(db, [r.line_item_id for r in rows], source, actor,
                                  exclude_offer_items={r.id for r in rows}, cause="deleted")
    for row in rows:
        db.delete(row)
    db.flush()
    db.delete(offer)
    flush(db, "in_use")
    events.record(db, "offer", offer_id, "delete", {"deleted": snapshot}, source, actor=actor)


def expire_offers(db: Session, today: date | None = None, source: str = "worker") -> list[uuid.UUID]:
    """valid_until passed -> expired (status + event only)."""
    today = today or clock.today()
    rows = db.scalars(select(SupplierOffer).where(SupplierOffer.status == "active",
                                                  SupplierOffer.valid_until < today)).all()
    affected: list[uuid.UUID] = []
    for offer in rows:
        offer.status = "expired"
        db.flush()
        events.record(db, "offer", offer.id, "status", {"old_status": "active", "new_status": "expired",
                                                        "note": "valid_until passed"}, source)
        affected += [r.line_item_id for r in offer_items(db, offer.id)]
    items_service.recompute_items(db, affected, source, today=today)
    return [o.id for o in rows]


def list_offers(db: Session, case_id: uuid.UUID | None = None, party_id: uuid.UUID | None = None) -> list[SupplierOffer]:
    query = select(SupplierOffer).order_by(SupplierOffer.received_at.desc())
    if case_id:
        query = query.where(SupplierOffer.case_id == case_id)
    if party_id:
        query = query.where(SupplierOffer.party_id == party_id)
    return list(db.scalars(query))
