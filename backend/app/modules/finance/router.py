"""Finance API (v0.8.0): sales invoices (with notes, Moadian, outputs) and supplier invoices with matching (M1);
payments, allocation, actual costs, profit, closing, ratings and the workspace are added by later milestones."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from app.modules.finance import costs, output, payments, profit, purchase_invoices, sales_invoices
from app.modules.finance.schemas import (ActualCostIn, ActualCostPatch, AllocationsIn, ApproveIn, DisputeIn, IssueIn,
                                         MoadianIn, NoteIn, OutputIn, PurchaseInvoiceIn, PurchaseInvoicePatch, ReasonIn,
                                         SalesInvoiceIn, SalesInvoicePatch)
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api", tags=["finance"])


def _lines(body) -> list[dict] | None:
    return None if body.lines is None else [line.model_dump(exclude_unset=True) for line in body.lines]


def _si(db: Session, invoice_id: uuid.UUID) -> dict:
    return sales_invoices.invoice_out(db, sales_invoices.get_invoice(db, invoice_id))


def _pi(db: Session, invoice_id: uuid.UUID) -> dict:
    return purchase_invoices.invoice_out(db, purchase_invoices.get_invoice(db, invoice_id))


# ---- sales invoices ---------------------------------------------------------------------------------------------------

@router.get("/sales-orders/{order_id}/invoicing")
def order_invoicing(order_id: uuid.UUID, _: CurrentUser, db: Db):
    return {"items": sales_invoices.invoicing_out(db, order_id),
            "invoices": [sales_invoices.invoice_out(db, i) for i in sales_invoices.invoices_of(db, sales_order_id=order_id)]}


@router.post("/sales-invoices", status_code=201)
def create_sales_invoice(body: SalesInvoiceIn, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True, exclude={"lines"})
    data["lines"] = _lines(body)
    row = sales_invoices.create_from_order(db, data.pop("sales_order_id"), data, request_source(request), user.username)
    db.commit()
    return _si(db, row.id)


@router.post("/sales-orders/{order_id}/invoice-rest", status_code=201)
def invoice_the_rest(order_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    """«Invoice the rest»: a draft with every delivered but not yet invoiced quantity."""
    row = sales_invoices.create_from_order(db, order_id, {}, request_source(request), user.username)
    db.commit()
    return _si(db, row.id)


@router.get("/sales-invoices/{invoice_id}")
def get_sales_invoice(invoice_id: uuid.UUID, _: CurrentUser, db: Db):
    return _si(db, invoice_id)


@router.patch("/sales-invoices/{invoice_id}")
def patch_sales_invoice(invoice_id: uuid.UUID, body: SalesInvoicePatch, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True, exclude={"lines"})
    if body.lines is not None:
        data["lines"] = _lines(body)
    sales_invoices.update_draft(db, invoice_id, data, request_source(request), user.username)
    db.commit()
    return _si(db, invoice_id)


@router.delete("/sales-invoices/{invoice_id}", status_code=204)
def delete_sales_invoice(invoice_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    sales_invoices.delete_draft(db, invoice_id, request_source(request), user.username)
    db.commit()


@router.post("/sales-invoices/{invoice_id}/issue")
def issue_sales_invoice(invoice_id: uuid.UUID, request: Request, user: CurrentUser, db: Db, body: IssueIn | None = None):
    sales_invoices.issue(db, invoice_id, body.model_dump(exclude_unset=True) if body else {}, user.calendar,
                         request_source(request), user.username)
    db.commit()
    return _si(db, invoice_id)


@router.post("/sales-invoices/{invoice_id}/cancel")
def cancel_sales_invoice(invoice_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    sales_invoices.cancel(db, invoice_id, body.reason, request_source(request), user.username)
    db.commit()
    return _si(db, invoice_id)


@router.post("/sales-invoices/{invoice_id}/credit-note", status_code=201)
def credit_note(invoice_id: uuid.UUID, body: NoteIn, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True, exclude={"lines"})
    data["lines"] = _lines(body)
    row = sales_invoices.create_note(db, invoice_id, "credit_note", data, request_source(request), user.username)
    db.commit()
    return _si(db, row.id)


@router.post("/sales-invoices/{invoice_id}/debit-note", status_code=201)
def debit_note(invoice_id: uuid.UUID, body: NoteIn, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True, exclude={"lines"})
    data["lines"] = _lines(body)
    row = sales_invoices.create_note(db, invoice_id, "debit_note", data, request_source(request), user.username)
    db.commit()
    return _si(db, row.id)


@router.post("/sales-invoices/{invoice_id}/moadian")
def moadian(invoice_id: uuid.UUID, body: MoadianIn, request: Request, user: CurrentUser, db: Db):
    sales_invoices.set_moadian(db, invoice_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return _si(db, invoice_id)


@router.get("/sales-invoices/{invoice_id}/print", response_class=HTMLResponse)
def print_sales_invoice(invoice_id: uuid.UUID, _: CurrentUser, db: Db):
    return HTMLResponse(output.render_html(output.build_context(db, sales_invoices.get_invoice(db, invoice_id))))


@router.post("/sales-invoices/{invoice_id}/outputs", status_code=201)
def output_sales_invoice(invoice_id: uuid.UUID, body: OutputIn, request: Request, user: CurrentUser, db: Db):
    result = output.generate(db, sales_invoices.get_invoice(db, invoice_id), body.format, request_source(request), user.username)
    db.commit()
    return result


# ---- supplier invoices -------------------------------------------------------------------------------------------------

@router.post("/purchase-invoices", status_code=201)
def create_purchase_invoice(body: PurchaseInvoiceIn, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True, exclude={"lines"})
    data["lines"] = _lines(body)
    row = purchase_invoices.create(db, data, request_source(request), user.username)
    db.commit()
    return _pi(db, row.id)


@router.get("/purchase-invoices/{invoice_id}")
def get_purchase_invoice(invoice_id: uuid.UUID, _: CurrentUser, db: Db):
    return _pi(db, invoice_id)


@router.patch("/purchase-invoices/{invoice_id}")
def patch_purchase_invoice(invoice_id: uuid.UUID, body: PurchaseInvoicePatch, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True, exclude={"lines"})
    if body.lines is not None:
        data["lines"] = _lines(body)
    purchase_invoices.update(db, invoice_id, data, request_source(request), user.username)
    db.commit()
    return _pi(db, invoice_id)


@router.delete("/purchase-invoices/{invoice_id}", status_code=204)
def delete_purchase_invoice(invoice_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    purchase_invoices.delete(db, invoice_id, request_source(request), user.username)
    db.commit()


@router.post("/purchase-invoices/{invoice_id}/approve")
def approve_purchase_invoice(invoice_id: uuid.UUID, request: Request, user: CurrentUser, db: Db, body: ApproveIn | None = None):
    purchase_invoices.approve(db, invoice_id, body.reason if body else None, request_source(request), user.username)
    db.commit()
    return _pi(db, invoice_id)


@router.post("/purchase-invoices/{invoice_id}/dispute")
def dispute_purchase_invoice(invoice_id: uuid.UUID, body: DisputeIn, request: Request, user: CurrentUser, db: Db):
    purchase_invoices.dispute(db, invoice_id, body.reason, body.claim_id, request_source(request), user.username)
    db.commit()
    return _pi(db, invoice_id)


@router.post("/purchase-invoices/{invoice_id}/cancel")
def cancel_purchase_invoice(invoice_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    purchase_invoices.cancel(db, invoice_id, body.reason, request_source(request), user.username)
    db.commit()
    return _pi(db, invoice_id)


# ---- the case ------------------------------------------------------------------------------------------------------

@router.get("/cases/{case_id}/finance")
def case_finance(case_id: uuid.UUID, _: CurrentUser, db: Db):
    """The case's «مالی» tab: invoices, supplier invoices, actual costs, payments with allocations, the profit table."""
    from app.modules.sourcing import inquiries as sourcing

    sourcing.get_case(db, case_id)
    return {"sales_invoices": [sales_invoices.invoice_out(db, i) for i in sales_invoices.invoices_of(db, case_id=case_id)],
            "purchase_invoices": [purchase_invoices.invoice_out(db, i) for i in purchase_invoices.invoices_of(db, case_id=case_id)],
            "actual_costs": costs.all_rows(db, case_id), "payments": payments.records_of_case(db, case_id),
            "advances": payments.unallocated_advances(db, case_id), "profit": profit.result(db, case_id)}


@router.get("/cases/{case_id}/profit")
def case_profit(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return profit.result(db, case_id)


# ---- actual costs ------------------------------------------------------------------------------------------------------

@router.post("/cases/{case_id}/actual-costs", status_code=201)
def create_cost(case_id: uuid.UUID, body: ActualCostIn, request: Request, user: CurrentUser, db: Db):
    row = costs.create(db, case_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return costs.cost_out(db, row)


@router.patch("/actual-costs/{cost_id}")
def patch_cost(cost_id: uuid.UUID, body: ActualCostPatch, request: Request, user: CurrentUser, db: Db):
    row = costs.update(db, cost_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return costs.cost_out(db, row)


@router.delete("/actual-costs/{cost_id}", status_code=204)
def delete_cost(cost_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    costs.delete(db, cost_id, request_source(request), user.username)
    db.commit()


# ---- allocation ----------------------------------------------------------------------------------------------------------

@router.get("/payment-records/{record_id}/allocation")
def allocation_view(record_id: uuid.UUID, _: CurrentUser, db: Db):
    from app.modules.execution.models import PaymentRecord

    record = db.get(PaymentRecord, record_id)
    if record is None:
        from app.core.errors import NotFound

        raise NotFound("not_found", "Payment record not found")
    return {"record": payments.record_out(db, record), "suggestion": payments.suggest(db, record_id)}


@router.post("/payment-records/{record_id}/allocations", status_code=201)
def allocate(record_id: uuid.UUID, body: AllocationsIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution.models import PaymentRecord

    payments.allocate_many(db, record_id, [a.model_dump(exclude_unset=True) for a in body.allocations],
                           request_source(request), user.username)
    db.commit()
    return payments.record_out(db, db.get(PaymentRecord, record_id))


@router.post("/payment-allocations/{allocation_id}/reverse", status_code=204)
def reverse_allocation(allocation_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    payments.reverse(db, allocation_id, body.reason, request_source(request), user.username)
    db.commit()


ROUTERS = [router]
