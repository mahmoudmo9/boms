"""Actual costs (v0.8.0): freight, insurance, customs, bank and other costs as they happen.

Each row has its amount and currency, its own real rate to the base currency (required when foreign) and the base
(rial) amount; ``vat_amount`` is the input VAT on top of ``amount`` (profit uses ``amount``). Status expected /
incurred is the owner's; ``paid`` follows the allocations. Read-only rows are added from their modules, not copied:
tender costs (Phase 7b; a refundable deposit once refunded is excluded), guarantee fees, and bank fees of payment
records. The purchase of goods is the supplier invoices, never an actual cost.
"""
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.finance.common import ZERO, base_currency, decimals, get, money
from app.modules.finance.models import ActualCost
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot

KINDS = ("freight_international", "insurance", "bank_fees", "customs_duty", "levy", "customs_clearance", "storage",
         "inspection", "freight_domestic", "export_clearance", "other")
FIELDS = ("kind", "description", "party_id", "amount", "currency", "fx_rate_to_base", "vat_amount", "incurred_on",
          "due_date", "document_id", "status", "shipment_id", "purchase_order_id", "notes")


def get_cost(db: Session, cost_id: uuid.UUID) -> ActualCost:
    return get(db, ActualCost, cost_id, "Actual cost")


def costs_of(db: Session, case_id: uuid.UUID) -> list[ActualCost]:
    return list(db.scalars(select(ActualCost).where(ActualCost.case_id == case_id)
                           .order_by(ActualCost.incurred_on, ActualCost.created_at)))


def _base(db: Session, row: ActualCost) -> None:
    base = base_currency(db)
    if row.currency == base:
        row.fx_rate_to_base, row.base_amount = None, row.amount
        return
    if row.fx_rate_to_base is None:
        raise AppError("fx_rate_required", f"A cost in {row.currency} needs its real rate to {base}",
                       {"currency": row.currency, "base_currency": base}, status=422)
    row.base_amount = money((row.amount * row.fx_rate_to_base).quantize(Decimal(1).scaleb(-decimals(db, base))))


def _links(db: Session, row: ActualCost) -> None:
    if row.kind not in KINDS:
        raise AppError("invalid_kind", "Unknown cost kind", {"kinds": list(KINDS)}, status=422)
    if row.status not in ("expected", "incurred"):
        raise AppError("invalid_status", "A cost is expected or incurred; paid follows the payments", status=422)
    from app.modules.execution.models import PurchaseOrder, Shipment

    for model, value, what in ((Shipment, row.shipment_id, "Shipment"), (PurchaseOrder, row.purchase_order_id, "Purchase order")):
        if value is not None and get(db, model, value, what).case_id != row.case_id:
            raise AppError("link_not_of_case", f"The {what.lower()} belongs to another case", status=422)


def create(db: Session, case_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> ActualCost:
    from app.modules.finance.closing import ensure_open
    from app.modules.sourcing import inquiries as sourcing

    sourcing.get_case(db, case_id)
    ensure_open(db, case_id)
    row = ActualCost(case_id=case_id, status=data.get("status") or "incurred",
                     **{k: data.get(k) for k in FIELDS if k != "status" and data.get(k) is not None})
    _links(db, row)
    _base(db, row)
    db.add(row)
    flush(db, "invalid_actual_cost")
    events.record(db, "actual_cost", row.id, "create", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def update(db: Session, cost_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> ActualCost:
    from app.modules.finance import payments
    from app.modules.finance.closing import ensure_open

    row = get_cost(db, cost_id)
    ensure_open(db, row.case_id)
    if payments.allocations_of(db, actual_cost_id=row.id) and {"amount", "currency", "fx_rate_to_base"} & set(changes):
        raise Conflict("cost_has_payments", "A cost with payments keeps its amount and currency")
    status = changes.pop("status", None)
    changed = diff(row, {k: v for k, v in changes.items() if k in FIELDS})
    if status is not None and row.status != "paid":
        if row.status != status:
            changed["status"] = {"old": row.status, "new": status}
        row.status = status
    _links(db, row)
    _base(db, row)
    flush(db, "invalid_actual_cost")
    payments.derive_cost_status(db, row)
    if changed:
        events.record(db, "actual_cost", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return row


def delete(db: Session, cost_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    from app.modules.finance import payments
    from app.modules.finance.closing import ensure_open

    row = get_cost(db, cost_id)
    ensure_open(db, row.case_id)
    if payments.allocations_of(db, actual_cost_id=row.id):
        raise Conflict("cost_has_payments", "Payments are allocated to this cost; reverse them first")
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "actual_cost", cost_id, "delete", jsonable(snapshot), source, actor=actor)


# ---- read-only rows from other modules ------------------------------------------------------------------------------

def sourced_rows(db: Session, case_id: uuid.UUID) -> list[dict]:
    """Tender costs, guarantee fees and payment bank fees of the case, as cost rows (read-only)."""
    from app.modules.execution.models import PaymentMilestone, PaymentRecord
    from app.modules.tenders.models import Guarantee, Tender, TenderCost

    base = base_currency(db)
    out = []
    for c in db.scalars(select(TenderCost).join(Tender, Tender.id == TenderCost.tender_id).where(Tender.case_id == case_id)):
        if c.refundable and c.refunded_on is not None:
            continue  # a refunded deposit is not a cost
        out.append({"source": "tender_cost", "source_id": c.id, "kind": "other", "description": f"tender: {c.kind}",
                    "amount": c.amount, "currency": c.amount_currency, "base_amount": c.amount if c.amount_currency == base else None,
                    "incurred_on": c.paid_on, "status": "paid" if c.paid_on else "incurred", "read_only": True})
    for g in db.scalars(select(Guarantee).where(Guarantee.case_id == case_id, Guarantee.fee.is_not(None))):
        if g.fee and g.fee > 0:
            out.append({"source": "guarantee_fee", "source_id": g.id, "kind": "bank_fees",
                        "description": f"guarantee fee ({g.purpose})", "amount": g.fee, "currency": g.fee_currency or base,
                        "base_amount": g.fee if (g.fee_currency or base) == base else None, "incurred_on": None,
                        "status": "paid", "read_only": True})
    rows = db.execute(select(PaymentRecord, PaymentMilestone).join(PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id)
                      .where(PaymentMilestone.case_id == case_id, PaymentRecord.bank_fee.is_not(None))).all()
    for r, _ms in rows:
        if r.bank_fee and r.bank_fee > 0:
            fee_cur = r.bank_fee_currency or r.amount_currency
            base_amount = r.bank_fee if fee_cur == base else (
                money(r.bank_fee * r.fx_rate_to_base) if fee_cur == r.amount_currency and r.fx_rate_to_base else None)
            out.append({"source": "payment_fee", "source_id": r.id, "kind": "bank_fees",
                        "description": f"bank fee {r.reference or ''}".strip(), "amount": r.bank_fee, "currency": fee_cur,
                        "base_amount": base_amount, "fx_rate_to_base": r.fx_rate_to_base if fee_cur == r.amount_currency else None,
                        "incurred_on": r.paid_on, "status": "paid", "read_only": True})
    return jsonable(out)


def cost_out(db: Session, row: ActualCost) -> dict:
    from app.modules.finance import payments

    return jsonable({**row_snapshot(row), "allocated": payments.cost_allocated(db, row.id),
                     "balance_due": payments.cost_balance(db, row), "read_only": False, "source": "actual_cost"})


def all_rows(db: Session, case_id: uuid.UUID) -> list[dict]:
    return [cost_out(db, r) for r in costs_of(db, case_id)] + sourced_rows(db, case_id)


__all__ = ["ZERO"]
