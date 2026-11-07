"""Claims (v0.7.0): against a supplier, a carrier or an insurer, or from the customer.

Linked to the PO, shipment, receipt, delivery or inspection it is about, with items and quantities; amounts are
informational in this phase (Phase 9 books them). Status: open -> submitted -> negotiating -> resolved (with a
resolution) / rejected / withdrawn; every change is an event. While a claim is open (open, submitted, negotiating)
there is always one open follow-up «پیگیری ادعا» on the counterparty, due every ``execution.claim_followup_days``
(the next one is created when the previous is done; hourly job ``execution.claim_followups``).
"""
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.execution import followups
from app.modules.execution.common import get, get_purchase_order, today
from app.modules.execution.models import Claim, Delivery, Inspection, Receipt, Shipment
from app.modules.parties import service as parties
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings

OPEN = ("open", "submitted", "negotiating")
FIELDS = ("direction", "counterparty_id", "kind", "purchase_order_id", "shipment_id", "receipt_id", "delivery_id",
          "inspection_id", "items", "claimed_amount", "claimed_amount_currency", "opened_on", "notes")
LINKS = {"purchase_order_id": "PurchaseOrder", "shipment_id": Shipment, "receipt_id": Receipt, "delivery_id": Delivery,
         "inspection_id": Inspection}


def get_claim(db: Session, claim_id: uuid.UUID) -> Claim:
    return get(db, Claim, claim_id, "Claim")


def claims_of(db: Session, *, case_id=None, party_id=None) -> list[Claim]:
    query = select(Claim)
    if case_id:
        query = query.where(Claim.case_id == case_id)
    if party_id:
        query = query.where(Claim.counterparty_id == party_id)
    return list(db.scalars(query.order_by(Claim.opened_on.desc(), Claim.created_at.desc())))


def _case_of_links(db: Session, data: dict):
    if data.get("purchase_order_id"):
        return get_purchase_order(db, data["purchase_order_id"]).case_id
    for key, model in (("shipment_id", Shipment), ("inspection_id", Inspection)):
        if data.get(key):
            return get(db, model, data[key], key).case_id
    if data.get("receipt_id"):
        return get_purchase_order(db, get(db, Receipt, data["receipt_id"], "Receipt").purchase_order_id).case_id
    if data.get("delivery_id"):
        from app.modules.execution.common import get_sales_order

        return get_sales_order(db, get(db, Delivery, data["delivery_id"], "Delivery").sales_order_id).case_id
    return data.get("case_id")


def _ensure_followup(db: Session, claim: Claim, source: str, actor: str | None) -> None:
    if claim.status not in OPEN or followups.links(db, purpose="claim", ref_id=claim.id):
        return
    days = settings.get(db, "execution.claim_followup_days")
    followups.create(db, case_id=claim.case_id, purpose="claim", ref_id=claim.id, party_id=claim.counterparty_id,
                     action=f"پیگیری ادعا ({claim.kind})", due_on=today() + timedelta(days=days), source=source, actor=actor)


def default_counterparty(db: Session, data: dict):
    """v0.8.0: a claim from a PO, receipt or inspection is against the PO's supplier; from a shipment, its carrier;
    from a delivery, the customer. The owner can change it."""
    if data.get("delivery_id"):
        from app.modules.execution.common import get_sales_order

        return get_sales_order(db, get(db, Delivery, data["delivery_id"], "Delivery").sales_order_id).customer_party_id
    po_id = data.get("purchase_order_id")
    if not po_id and data.get("receipt_id"):
        po_id = get(db, Receipt, data["receipt_id"], "Receipt").purchase_order_id
    if not po_id and data.get("inspection_id"):
        po_id = get(db, Inspection, data["inspection_id"], "Inspection").purchase_order_id
    if po_id:
        return get_purchase_order(db, po_id).supplier_party_id
    if data.get("shipment_id"):
        return get(db, Shipment, data["shipment_id"], "Shipment").carrier_party_id
    return None


def create(db: Session, data: dict, source: str, actor: str | None = None) -> Claim:
    if not data.get("counterparty_id"):
        data = {**data, "counterparty_id": default_counterparty(db, data)}
    case_id = _case_of_links(db, data)
    if data.get("case_id") and case_id != data["case_id"]:
        raise AppError("link_not_of_case", "A linked record belongs to another case", status=422)
    if case_id is None:
        raise AppError("case_required", "A claim belongs to a case", status=422)
    sourcing.get_case(db, case_id)
    if not data.get("counterparty_id"):
        raise AppError("counterparty_required", "Against whom is the claim?", status=422)
    parties.get_party(db, data["counterparty_id"])
    for key in LINKS:
        if data.get(key):
            linked_case = _case_of_links(db, {key: data[key]})
            if linked_case != case_id:
                raise AppError("link_not_of_case", "A linked record belongs to another case", {"link": key}, status=422)
    claim = Claim(case_id=case_id, status="open", **{k: data[k] for k in FIELDS if data.get(k) is not None})
    claim.opened_on = claim.opened_on or today()
    db.add(claim)
    flush(db, "invalid_claim")
    _ensure_followup(db, claim, source, actor)
    events.record(db, "claim", claim.id, "create", jsonable(row_snapshot(claim)), source, actor=actor)
    return claim


def update(db: Session, claim_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Claim:
    claim = get_claim(db, claim_id)
    if changes.get("counterparty_id"):
        parties.get_party(db, changes["counterparty_id"])
    changed = diff(claim, {k: v for k, v in changes.items() if k in FIELDS and k not in ("purchase_order_id",)})
    flush(db, "invalid_claim")
    if "counterparty_id" in changed:
        followups.cancel(db, "claim counterparty changed", source, actor, purposes=("claim",), ref_id=claim.id)
        _ensure_followup(db, claim, source, actor)
    if changed:
        events.record(db, "claim", claim.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return claim


def set_status(db: Session, claim_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> Claim:
    claim = get_claim(db, claim_id)
    status = data["status"]
    if status == claim.status:
        raise AppError("nothing_to_change", "The claim already has this status", status=422)
    if status == "resolved" and not data.get("resolution"):
        raise AppError("resolution_required", "A resolved claim needs its resolution", status=422)
    old = claim.status
    claim.status = status
    if status == "resolved":
        claim.resolution = data["resolution"]
        claim.resolution_amount = data.get("resolution_amount")
        claim.resolution_amount_currency = data.get("resolution_amount_currency") or (
            claim.claimed_amount_currency if data.get("resolution_amount") is not None else None)
        claim.resolved_on = data.get("resolved_on") or today()
    elif status in OPEN:
        claim.resolved_on = None
    flush(db, "invalid_claim")
    if status in OPEN:
        _ensure_followup(db, claim, source, actor)
    else:
        followups.cancel(db, f"claim {status}", source, actor, purposes=("claim",), ref_id=claim.id)
    events.record(db, "claim", claim.id, "status", jsonable({
        "old_status": old, "new_status": status, "note": data.get("note"), "resolution": claim.resolution,
        "resolution_amount": claim.resolution_amount}), source, actor=actor)
    return claim


def delete(db: Session, claim_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    claim = get_claim(db, claim_id)
    if claim.status not in ("open", "withdrawn"):
        raise Conflict("claim_in_progress", "Only an open or withdrawn claim is deleted", {"status": claim.status})
    followups.cancel(db, "claim deleted", source, actor, ref_id=claim.id)
    snapshot = row_snapshot(claim)
    db.delete(claim)
    flush(db, "in_use")
    events.record(db, "claim", claim_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def refresh_followups(db: Session, source: str = "worker") -> int:
    """Every open claim keeps one open «پیگیری ادعا» (the next one after the previous was done)."""
    created = 0
    for claim in db.scalars(select(Claim).where(Claim.status.in_(OPEN))):
        if not followups.links(db, purpose="claim", ref_id=claim.id):
            _ensure_followup(db, claim, source, None)
            created += 1
    return created


def claim_out(db: Session, claim: Claim) -> dict:
    p = parties.get_party(db, claim.counterparty_id)
    return jsonable({**row_snapshot(claim), "counterparty": {"id": p.id, "name_fa": p.name_fa, "name_en": p.name_en},
                     "followups": [{"id": f.id, "due_on": f.due_on, "action": f.action}
                                   for _l, f in followups.links(db, purpose="claim", ref_id=claim.id)],
                     "documents": parties.linked_documents(db, "claim", [str(claim.id)])})
