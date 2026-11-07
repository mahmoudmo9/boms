"""Finance API (v0.8.0): sales invoices (with notes, Moadian, outputs) and supplier invoices with matching (M1);
payments, allocation, actual costs, profit, closing, ratings and the workspace are added by later milestones."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi.responses import Response

from app.modules.finance import (closing, costs, output, payments, profit, purchase_invoices, ratings, sales_invoices,
                                 workspace)
from app.modules.finance.schemas import (ActualCostIn, ActualCostPatch, AllocationsIn, ApproveIn, CloseIn, DisputeIn,
                                         IssueIn, MoadianIn, NoteIn, OutputIn, PurchaseInvoiceIn, PurchaseInvoicePatch,
                                         RatingIn, ReasonIn, SalesInvoiceIn, SalesInvoicePatch)
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api", tags=["finance"])

from app.modules.finance import guard as _guard  # noqa: E402

_guard.install()   # a closed deal is read-only for every request (also installed with the hooks)


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


# ---- closing and ratings -----------------------------------------------------------------------------------------------

@router.get("/cases/{case_id}/close-checklist")
def close_checklist(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return closing.checklist(db, case_id)


@router.post("/cases/{case_id}/close")
def close_deal(case_id: uuid.UUID, body: CloseIn, request: Request, user: CurrentUser, db: Db):
    result = closing.close(db, case_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return result


@router.post("/cases/{case_id}/reopen")
def reopen_deal(case_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    closing.reopen(db, case_id, body.reason, request_source(request), user.username)
    db.commit()
    return profit.result(db, case_id)


@router.get("/cases/{case_id}/ratings")
def case_ratings(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return {"rateable": jsonable_list(ratings.rateable(db, case_id)), "ratings": ratings.ratings_of_case(db, case_id)}


@router.post("/cases/{case_id}/ratings")
def rate(case_id: uuid.UUID, body: RatingIn, request: Request, user: CurrentUser, db: Db):
    row = ratings.save(db, case_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    from app.modules.sourcing.common import row_snapshot

    return row_snapshot(row)


@router.get("/parties/{party_id}/finance")
def party_finance(party_id: uuid.UUID, _: CurrentUser, db: Db):
    """The party page's finance block: receivable / payable balances, overdue, invoices, ratings."""
    from app.modules.parties import service as parties

    parties.get_party(db, party_id)
    sales = workspace.invoices(db, kind="sales", party_id=party_id)
    purchases = workspace.invoices(db, kind="purchase", party_id=party_id)
    rec = [r for r in workspace.receivables(db)["invoices"] if r["party_id"] == str(party_id)]
    pay = [r for r in workspace.payables(db)["items"] if r["party_id"] == str(party_id)]

    def per_currency(rows, pred=lambda r: True):
        out: dict = {}
        for r in rows:
            if pred(r):
                out[r["currency"]] = out.get(r["currency"], Decimal(0)) + Decimal(r["balance"])
        return {k: str(v) for k, v in out.items()}

    return {"receivable": per_currency(rec), "receivable_overdue": per_currency(rec, lambda r: r["overdue"]),
            "payable": per_currency(pay), "payable_overdue": per_currency(pay, lambda r: r["window"] == "overdue"),
            "sales_invoices": sales[:20], "purchase_invoices": purchases[:20], "ratings": ratings.summary(db, party_id)}


# ---- the finance workspace and exports -------------------------------------------------------------------------------------

@router.get("/finance/receivables")
def fin_receivables(_: CurrentUser, db: Db):
    return workspace.receivables(db)


@router.get("/finance/payables")
def fin_payables(_: CurrentUser, db: Db):
    return workspace.payables(db)


@router.get("/finance/invoices")
def fin_invoices(_: CurrentUser, db: Db, kind: Literal["sales", "purchase"] = "sales", status: str | None = None,
                 moadian_status: str | None = None, date_from: date | None = None, date_to: date | None = None,
                 party_id: uuid.UUID | None = None, case_id: uuid.UUID | None = None):
    return workspace.invoices(db, kind=kind, status=status, moadian_status=moadian_status, date_from=date_from,
                              date_to=date_to, party_id=party_id, case_id=case_id)


@router.get("/finance/payments")
def fin_payments(_: CurrentUser, db: Db, date_from: date | None = None, date_to: date | None = None,
                 direction: Literal["in", "out"] | None = None):
    return workspace.payment_list(db, date_from=date_from, date_to=date_to, direction=direction)


@router.get("/finance/deals")
def fin_deals(_: CurrentUser, db: Db, state: Literal["open", "closed"] | None = None, date_from: date | None = None,
              date_to: date | None = None):
    return workspace.deals(db, state=state, date_from=date_from, date_to=date_to)


@router.get("/finance/vat")
def fin_vat(user: CurrentUser, db: Db, date_from: date | None = None, date_to: date | None = None):
    return workspace.vat(db, calendar=user.calendar, date_from=date_from, date_to=date_to)


EXPORTS = Literal["sales_invoices", "purchase_invoices", "payments", "actual_costs", "deals", "receivables"]


@router.get("/finance/exports/all.zip")
def fin_export_all(user: CurrentUser, db: Db, date_from: date | None = None, date_to: date | None = None):
    data = workspace.export_all(db, user.language, user.calendar, date_from, date_to)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="boms-finance-{date_from or "all"}-{date_to or "all"}.zip"'})


@router.get("/finance/exports/{name}.csv")
def fin_export(name: EXPORTS, user: CurrentUser, db: Db, date_from: date | None = None, date_to: date | None = None):
    data = workspace.export(db, name, user.language, user.calendar, date_from, date_to)
    return Response(data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


def jsonable_list(rows):
    from app.modules.sourcing.common import jsonable

    return jsonable(rows)


ROUTERS = [router]
