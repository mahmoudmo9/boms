"""Command center section «مالی» (v0.8.0): receivables overdue; payables due within 7 days or overdue; delivered not
invoiced; received goods without a supplier invoice; Moadian not sent or rejected; payments without an FX rate; cases
ready to close (checklist passes)."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.finance import closing, purchase_invoices, sales_invoices, workspace
from app.modules.finance.common import base_currency
from app.modules.finance.models import SalesInvoice
from app.modules.sourcing.common import jsonable


def summary(db: Session, today: date) -> dict:
    from app.modules.execution.models import PaymentMilestone, PaymentRecord, PurchaseOrder, SalesOrder
    from app.modules.sourcing.models import Case

    titles: dict = {}

    def title(case_id):
        if case_id not in titles:
            case = db.get(Case, case_id)
            titles[case_id] = case.title if case else None
        return titles[case_id]

    rec = workspace.receivables(db, today)
    overdue = [r for r in rec["invoices"] if r["overdue"]]
    pay = workspace.payables(db, today)
    due = [r for r in pay["items"] if r["window"] in ("overdue", "due_7")]
    not_invoiced = []
    for so in db.scalars(select(SalesOrder).where(SalesOrder.status.in_(("confirmed", "in_progress", "delivered")))):
        qty = sales_invoices.delivered_not_invoiced(db, so.id)
        if qty > 0:
            not_invoiced.append({"sales_order_id": so.id, "case_id": so.case_id, "number": so.number, "quantity": qty,
                                 "case_title": title(so.case_id)})
    no_supplier_invoice = []
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.not_in(("draft", "cancelled", "superseded")))):
        rest = purchase_invoices.received_not_invoiced(db, po.id)
        if rest:
            no_supplier_invoice.append({"purchase_order_id": po.id, "case_id": po.case_id, "number": po.number,
                                        "items": len(rest), "case_title": title(po.case_id)})
    moadian = [{"invoice_id": i.id, "case_id": i.case_id, "number": i.number, "moadian_status": i.moadian_status,
                "case_title": title(i.case_id)}
               for i in db.scalars(select(SalesInvoice).where(SalesInvoice.status == "issued",
                                                              SalesInvoice.moadian_status.in_(("not_sent", "rejected")))
                                   .order_by(SalesInvoice.issue_date))]
    base = base_currency(db)
    no_rate = [{"record_id": r.id, "case_id": ms.case_id, "paid_on": r.paid_on, "amount": r.amount, "currency": r.amount_currency,
                "case_title": title(ms.case_id)}
               for r, ms in db.execute(select(PaymentRecord, PaymentMilestone)
                                       .join(PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id)
                                       .where(PaymentRecord.amount_currency != base, PaymentRecord.fx_rate_to_base.is_(None))
                                       .order_by(PaymentRecord.paid_on)).all()]
    ready = []
    for case in db.scalars(select(Case).where(Case.status.not_in(("closed", "cancelled", "lost")),
                                              Case.id.in_(select(SalesOrder.case_id).where(SalesOrder.status != "cancelled")))):
        if closing.checklist(db, case.id)["passes"]:
            ready.append({"case_id": case.id, "case_title": case.title})
    return jsonable({"receivables_overdue": overdue, "payables_due": due, "delivered_not_invoiced": not_invoiced,
                     "received_not_invoiced": no_supplier_invoice, "moadian_pending": moadian,
                     "payments_without_rate": no_rate, "ready_to_close": ready})
