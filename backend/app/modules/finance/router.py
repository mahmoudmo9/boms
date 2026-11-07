"""Finance API (v0.8.0): sales invoices (with notes, Moadian, outputs) and supplier invoices with matching (M1);
payments, allocation, actual costs, profit, closing, ratings and the workspace are added by later milestones."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from app.modules.finance import output, purchase_invoices, sales_invoices
from app.modules.finance.schemas import (ApproveIn, DisputeIn, IssueIn, MoadianIn, NoteIn, OutputIn, PurchaseInvoiceIn,
                                         PurchaseInvoicePatch, ReasonIn, SalesInvoiceIn, SalesInvoicePatch)
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


ROUTERS = [router]
