"""Case cascade delete (test data, v0.8.0): every finance row of the case — allocations, invoices with lines and notes,
supplier invoices, actual costs, the deal result and ratings — before execution's rows (order 0). A closed case's rows
are deleted too (the read-only guard is lifted for the cascade)."""
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.modules.finance.models import (ActualCost, DealResult, PartyRating, PaymentAllocation, PurchaseInvoice,
                                        PurchaseInvoiceLine, SalesInvoice, SalesInvoiceLine)
from app.modules.sourcing.common import flush, row_snapshot


def cleanup_case(db: Session, case_id: uuid.UUID, note: str, source: str, actor: str | None) -> dict:
    db.info["finance_closing"] = True       # the cascade of a closed deal (test data) is allowed
    si = list(db.scalars(select(SalesInvoice.id).where(SalesInvoice.case_id == case_id)))
    pi = list(db.scalars(select(PurchaseInvoice.id).where(PurchaseInvoice.case_id == case_id)))
    ac = list(db.scalars(select(ActualCost.id).where(ActualCost.case_id == case_id)))
    from app.modules.execution.models import PaymentMilestone, PaymentRecord

    records = select(PaymentRecord.id).join(PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id) \
        .where(PaymentMilestone.case_id == case_id)
    conditions = [PaymentAllocation.payment_record_id.in_(records)]
    if si:
        conditions.append(PaymentAllocation.sales_invoice_id.in_(si))
    if pi:
        conditions.append(PaymentAllocation.purchase_invoice_id.in_(pi))
    if ac:
        conditions.append(PaymentAllocation.actual_cost_id.in_(ac))
    groups = [
        ("payment_allocations", select(PaymentAllocation).where(or_(*conditions))),
        ("sales_invoice_lines", select(SalesInvoiceLine).where(SalesInvoiceLine.sales_invoice_id.in_(si))),
        ("sales_invoice_notes", select(SalesInvoice).where(SalesInvoice.id.in_(si), SalesInvoice.corrects_invoice_id.is_not(None))),
        ("sales_invoices", select(SalesInvoice).where(SalesInvoice.id.in_(si), SalesInvoice.corrects_invoice_id.is_(None))),
        ("purchase_invoice_lines", select(PurchaseInvoiceLine).where(PurchaseInvoiceLine.purchase_invoice_id.in_(pi))),
        ("purchase_invoices", select(PurchaseInvoice).where(PurchaseInvoice.id.in_(pi))),
        ("actual_costs", select(ActualCost).where(ActualCost.id.in_(ac))),
        ("deal_results", select(DealResult).where(DealResult.case_id == case_id)),
        ("party_ratings", select(PartyRating).where(PartyRating.case_id == case_id)),
    ]
    snapshot: dict = {}
    counts: dict[str, int] = {}
    for name, query in groups:
        rows = list(db.scalars(query))
        snapshot[name] = [row_snapshot(r) for r in rows]
        counts[name] = len(rows)
        for r in rows:
            db.delete(r)
        flush(db, "in_use")
    return {"counts": {k: v for k, v in counts.items() if v}, "rows": snapshot}
