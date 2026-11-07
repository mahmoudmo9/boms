"""Payments and allocation (v0.8.0).

A payment record (Phase 8, module execution) still belongs to its milestone; allocation is the new link to what it
pays: a sales invoice (money in from the customer), a supplier invoice or an actual cost (money out). The amount is
in the payment's currency; a target in another currency needs ``fx_rate`` (1 payment unit in the target currency).
Over-allocation of the payment or of the target is refused (422). Prepayments received before an invoice stay
unallocated advances until allocated; allocation is suggested oldest-first and confirmed by the owner.
"""
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.finance import purchase_invoices, sales_invoices
from app.modules.finance.common import ZERO, base_currency, get, money, reason_required, round_to
from app.modules.finance.models import ActualCost, PaymentAllocation, PurchaseInvoice, SalesInvoice
from app.modules.sourcing.common import flush, jsonable, row_snapshot


def _record(db: Session, record_id: uuid.UUID):
    from app.modules.execution.models import PaymentMilestone, PaymentRecord

    row = get(db, PaymentRecord, record_id, "Payment record")
    return row, db.get(PaymentMilestone, row.milestone_id)


def allocations_of(db: Session, *, record_id=None, sales_invoice_id=None, purchase_invoice_id=None,
                   actual_cost_id=None) -> list[PaymentAllocation]:
    query = select(PaymentAllocation)
    for col, value in ((PaymentAllocation.payment_record_id, record_id), (PaymentAllocation.sales_invoice_id, sales_invoice_id),
                       (PaymentAllocation.purchase_invoice_id, purchase_invoice_id),
                       (PaymentAllocation.actual_cost_id, actual_cost_id)):
        if value is not None:
            query = query.where(col == value)
    return list(db.scalars(query.order_by(PaymentAllocation.created_at)))


def allocated_of_record(db: Session, record_id: uuid.UUID) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
                     .where(PaymentAllocation.payment_record_id == record_id)) or ZERO


def cost_allocated(db: Session, cost_id: uuid.UUID) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(PaymentAllocation.target_amount), 0))
                     .where(PaymentAllocation.actual_cost_id == cost_id)) or ZERO


def cost_balance(db: Session, cost: ActualCost) -> Decimal:
    return money(cost.amount + (cost.vat_amount or ZERO) - cost_allocated(db, cost.id))


def derive_cost_status(db: Session, cost: ActualCost) -> None:
    """``paid`` follows the allocations; otherwise the owner's expected / incurred stays."""
    if cost_balance(db, cost) <= 0:
        cost.status = "paid"
    elif cost.status == "paid":
        cost.status = "incurred"
    db.flush()


def _target(db: Session, data: dict):
    keys = [k for k in ("sales_invoice_id", "purchase_invoice_id", "actual_cost_id") if data.get(k)]
    if len(keys) != 1:
        raise AppError("one_target", "Allocate to exactly one invoice or cost", status=422)
    key = keys[0]
    if key == "sales_invoice_id":
        inv = sales_invoices.get_invoice(db, data[key])
        if inv.status != "issued" or inv.kind == "credit_note":
            raise Conflict("invoice_not_issued", "Only an issued invoice or debit note takes payments", {"status": inv.status})
        return key, inv, "in", inv.customer_party_id, inv.currency, sales_invoices.balance_due(db, inv) if inv.kind == "invoice" \
            else money(inv.total - sales_invoices.allocated(db, inv.id))
    if key == "purchase_invoice_id":
        inv = purchase_invoices.get_invoice(db, data[key])
        if inv.status == "cancelled":
            raise Conflict("invoice_cancelled", "The supplier invoice is cancelled")
        return key, inv, "out", inv.supplier_party_id, inv.currency, purchase_invoices.balance_due(db, inv)
    cost = get(db, ActualCost, data[key], "Actual cost")
    return key, cost, "out", None, cost.currency, cost_balance(db, cost)


def allocate(db: Session, record_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PaymentAllocation:
    record, ms = _record(db, record_id)
    key, target, direction, party_id, currency, balance = _target(db, data)
    if ms.direction != direction:
        raise AppError("wrong_direction", "Money in pays sales invoices; money out pays supplier invoices and costs",
                       {"payment_direction": ms.direction}, status=422)
    if party_id is not None and ms.party_id != party_id:
        raise AppError("party_mismatch", "The payment is from another party than the invoice's", status=422)
    if target.case_id != ms.case_id:
        raise AppError("link_not_of_case", "The invoice belongs to another case", status=422)
    amount = Decimal(data["amount"])
    if record.amount_currency == currency:
        fx_rate, target_amount = None, amount
    else:
        if not data.get("fx_rate"):
            raise AppError("fx_rate_required", f"Allocating {record.amount_currency} to a {currency} invoice needs a rate",
                           {"from_currency": record.amount_currency, "to_currency": currency}, status=422)
        fx_rate = Decimal(data["fx_rate"])
        target_amount = round_to(db, amount * fx_rate, currency)
    free = money(record.amount - allocated_of_record(db, record.id))
    if amount > free:
        raise AppError("over_allocated_payment", "More than the payment's unallocated amount",
                       {"unallocated": str(free), "currency": record.amount_currency}, status=422)
    if target_amount > balance:
        raise AppError("over_allocated_invoice", "More than the invoice's open balance",
                       {"balance": str(balance), "currency": currency}, status=422)
    row = PaymentAllocation(payment_record_id=record.id, amount=amount, fx_rate=fx_rate, target_amount=target_amount,
                            note=data.get("note"), **{key: target.id})
    db.add(row)
    flush(db, "invalid_allocation")
    if key == "actual_cost_id":
        derive_cost_status(db, target)
    events.record(db, "payment_allocation", row.id, "create", jsonable({
        "payment_record_id": record.id, key: target.id, "amount": amount, "currency": record.amount_currency,
        "fx_rate": fx_rate, "target_amount": target_amount, "target_currency": currency}), source, actor=actor)
    return row


def allocate_many(db: Session, record_id: uuid.UUID, rows: list[dict], source: str, actor: str | None = None) -> list:
    """The owner confirms a suggestion (all or nothing: one transaction)."""
    if not rows:
        raise AppError("no_allocations", "Nothing to allocate", status=422)
    return [allocate(db, record_id, r, source, actor) for r in rows]


def reverse(db: Session, allocation_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> None:
    """An allocation made by mistake is reversed with a reason (the event keeps it); never on a closed case."""
    row = get(db, PaymentAllocation, allocation_id, "Allocation")
    reason = reason_required(reason)
    record, ms = _record(db, row.payment_record_id)
    from app.modules.finance.closing import ensure_open

    ensure_open(db, ms.case_id)
    snapshot = row_snapshot(row)
    cost = db.get(ActualCost, row.actual_cost_id) if row.actual_cost_id else None
    db.delete(row)
    flush(db, "in_use")
    if cost is not None:
        derive_cost_status(db, cost)
    events.record(db, "payment_allocation", allocation_id, "reverse", jsonable({"allocation": snapshot, "reason": reason}),
                  source, actor=actor)


def suggest(db: Session, record_id: uuid.UUID) -> list[dict]:
    """Oldest-first (due date, then date) over the open invoices / costs of the same party and case in the payment's
    currency; other currencies are listed with ``needs_rate`` and no amount."""
    record, ms = _record(db, record_id)
    free = money(record.amount - allocated_of_record(db, record.id))
    candidates = []
    if ms.direction == "in":
        for inv in sales_invoices.invoices_of(db, case_id=ms.case_id, customer_id=ms.party_id):
            if inv.status == "issued" and inv.kind != "credit_note":
                due = sales_invoices.balance_due(db, inv) if inv.kind == "invoice" else money(inv.total - sales_invoices.allocated(db, inv.id))
                if due > 0:
                    candidates.append(("sales_invoice_id", inv, inv.number, inv.due_date or inv.issue_date, inv.issue_date, inv.currency, due))
    else:
        for inv in purchase_invoices.invoices_of(db, case_id=ms.case_id, supplier_id=ms.party_id):
            due = purchase_invoices.balance_due(db, inv)
            if inv.status != "cancelled" and due > 0:
                candidates.append(("purchase_invoice_id", inv, inv.supplier_invoice_no, inv.due_date or inv.invoice_date,
                                   inv.invoice_date, inv.currency, due))
        for cost in db.scalars(select(ActualCost).where(ActualCost.case_id == ms.case_id, ActualCost.party_id == ms.party_id)):
            due = cost_balance(db, cost)
            if due > 0:
                candidates.append(("actual_cost_id", cost, cost.description, cost.due_date or cost.incurred_on,
                                   cost.incurred_on, cost.currency, due))
    candidates.sort(key=lambda c: (c[3] or c[4] or record.paid_on, c[4] or record.paid_on, str(c[1].id)))
    out = []
    for key, row, label, due_on, _on, currency, due in candidates:
        if currency != record.amount_currency:
            out.append({key: row.id, "label": label, "due_date": due_on, "currency": currency, "balance": due,
                        "needs_rate": True, "amount": None})
            continue
        take = min(free, due)
        if take > 0:
            out.append({key: row.id, "label": label, "due_date": due_on, "currency": currency, "balance": due,
                        "needs_rate": False, "amount": take})
            free -= take
    return jsonable(out)


def record_out(db: Session, record, ms=None) -> dict:
    from app.modules.execution.models import PaymentMilestone

    ms = ms or db.get(PaymentMilestone, record.milestone_id)
    allocated = allocated_of_record(db, record.id)
    base = base_currency(db)
    return jsonable({**row_snapshot(record), "direction": ms.direction, "case_id": ms.case_id, "party_id": ms.party_id,
                     "milestone_id": ms.id, "milestone_kind": ms.kind, "allocated": allocated,
                     "unallocated": money(record.amount - allocated),
                     "rate_missing": record.amount_currency != base and record.fx_rate_to_base is None,
                     "allocations": [row_snapshot(a) for a in allocations_of(db, record_id=record.id)]})


def records_of_case(db: Session, case_id: uuid.UUID) -> list[dict]:
    from app.modules.execution.models import PaymentMilestone, PaymentRecord

    rows = db.execute(select(PaymentRecord, PaymentMilestone).join(PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id)
                      .where(PaymentMilestone.case_id == case_id).order_by(PaymentRecord.paid_on, PaymentRecord.created_at)).all()
    return [record_out(db, r, ms) for r, ms in rows]


def unallocated_advances(db: Session, case_id: uuid.UUID | None = None) -> list[dict]:
    from app.modules.execution.models import PaymentMilestone, PaymentRecord

    query = select(PaymentRecord, PaymentMilestone).join(PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id) \
        .where(PaymentMilestone.direction == "in")
    if case_id:
        query = query.where(PaymentMilestone.case_id == case_id)
    out = []
    for r, ms in db.execute(query.order_by(PaymentRecord.paid_on)).all():
        free = money(r.amount - allocated_of_record(db, r.id))
        if free > 0:
            out.append({"record_id": r.id, "case_id": ms.case_id, "party_id": ms.party_id, "paid_on": r.paid_on,
                        "amount": r.amount, "currency": r.amount_currency, "unallocated": free})
    return jsonable(out)


__all__ = ["PurchaseInvoice", "SalesInvoice"]
