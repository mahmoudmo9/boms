"""Execution API (v0.7.0): sales orders, amendments, payment milestones and the cash position (M1); purchase orders,
process checklists, shipments, inspections, receipts, claims and deliveries are added by later milestones."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from app.modules.execution import milestones, output, sales_orders
from app.modules.execution.common import get_sales_order
from app.modules.execution.schemas import (AmendIn, ConfirmIn, MilestoneIn, MilestonePatch, OutputIn, PaymentIn, ReasonIn,
                                           SalesOrderFromProposal, SalesOrderFromQuote, SalesOrderItemPatch,
                                           SalesOrderManual, SalesOrderPatch)
from app.modules.sourcing.common import jsonable, row_snapshot
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api", tags=["execution"])


def _so(db: Session, order_id: uuid.UUID) -> dict:
    return sales_orders.order_out(db, get_sales_order(db, order_id))


# ---- the case -----------------------------------------------------------------------------------------------------

@router.get("/cases/{case_id}/execution")
def case_execution(case_id: uuid.UUID, _: CurrentUser, db: Db):
    from app.modules.execution import summary

    return summary.case_execution(db, case_id)


@router.get("/cases/{case_id}/cash-position")
def cash_position(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return milestones.cash_position(db, case_id)


# ---- sales orders ---------------------------------------------------------------------------------------------------

@router.post("/sales-orders/from-quote", status_code=201)
def so_from_quote(body: SalesOrderFromQuote, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True)
    row = sales_orders.create_from_quote(db, data.pop("quote_id"), data, user.calendar, request_source(request), user.username)
    db.commit()
    return _so(db, row.id)


@router.post("/sales-orders/from-proposal", status_code=201)
def so_from_proposal(body: SalesOrderFromProposal, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_unset=True)
    row = sales_orders.create_from_proposal(db, data.pop("tender_proposal_id"), data, user.calendar,
                                            request_source(request), user.username)
    db.commit()
    return _so(db, row.id)


@router.post("/cases/{case_id}/sales-orders", status_code=201)
def so_manual(case_id: uuid.UUID, body: SalesOrderManual, request: Request, user: CurrentUser, db: Db):
    row = sales_orders.create_manual(db, case_id, body.model_dump(exclude_unset=True), user.calendar,
                                     request_source(request), user.username)
    db.commit()
    return _so(db, row.id)


@router.get("/sales-orders/{order_id}")
def so_get(order_id: uuid.UUID, _: CurrentUser, db: Db):
    return _so(db, order_id)


@router.patch("/sales-orders/{order_id}")
def so_patch(order_id: uuid.UUID, body: SalesOrderPatch, request: Request, user: CurrentUser, db: Db):
    sales_orders.update_order(db, order_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return _so(db, order_id)


@router.delete("/sales-orders/{order_id}", status_code=204)
def so_delete(order_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    sales_orders.delete_order(db, order_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


@router.patch("/sales-order-items/{item_id}")
def so_item_patch(item_id: uuid.UUID, body: SalesOrderItemPatch, request: Request, user: CurrentUser, db: Db):
    row = sales_orders.update_item(db, item_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return _so(db, row.sales_order_id)


@router.delete("/sales-order-items/{item_id}")
def so_item_delete(item_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution.common import get
    from app.modules.execution.models import SalesOrderItem

    order_id = get(db, SalesOrderItem, item_id, "Sales order item").sales_order_id
    sales_orders.remove_item(db, item_id, request_source(request), user.username)
    db.commit()
    return _so(db, order_id)


@router.post("/sales-orders/{order_id}/confirm")
def so_confirm(order_id: uuid.UUID, body: ConfirmIn, request: Request, user: CurrentUser, db: Db):
    sales_orders.confirm(db, order_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return _so(db, order_id)


@router.post("/sales-orders/{order_id}/amend")
def so_amend(order_id: uuid.UUID, body: AmendIn, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump()
    data["items"] = [i.model_dump(exclude_unset=True) for i in body.items]
    sales_orders.amend(db, order_id, data, request_source(request), user.username)
    db.commit()
    return _so(db, order_id)


@router.post("/sales-orders/{order_id}/cancel")
def so_cancel(order_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    sales_orders.cancel(db, order_id, body.reason, request_source(request), user.username)
    db.commit()
    return _so(db, order_id)


@router.get("/sales-orders/{order_id}/print", response_class=HTMLResponse)
def so_print(order_id: uuid.UUID, _: CurrentUser, db: Db, language: str | None = None):
    order = get_sales_order(db, order_id)
    return HTMLResponse(output.render_html(output.sales_order_context(db, order, language if language in ("fa", "en") else None)))


@router.post("/sales-orders/{order_id}/outputs", status_code=201)
def so_output(order_id: uuid.UUID, body: OutputIn, request: Request, user: CurrentUser, db: Db):
    order = get_sales_order(db, order_id)
    result = output.generate(db, "sales_order", order, output.sales_order_context(db, order, body.language), body.format,
                             request_source(request), user.username)
    db.commit()
    return result


# ---- payment milestones ---------------------------------------------------------------------------------------------

@router.post("/payment-milestones", status_code=201)
def ms_create(body: MilestoneIn, request: Request, user: CurrentUser, db: Db):
    row = milestones.create(db, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return milestones.milestone_out(db, row)


@router.get("/payment-milestones/quick-add")
def ms_quick_add(_: CurrentUser):
    return milestones.QUICK_ADD


@router.patch("/payment-milestones/{milestone_id}")
def ms_patch(milestone_id: uuid.UUID, body: MilestonePatch, request: Request, user: CurrentUser, db: Db):
    row = milestones.update(db, milestone_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return milestones.milestone_out(db, row)


@router.post("/payment-milestones/{milestone_id}/cancel")
def ms_cancel(milestone_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    row = milestones.cancel(db, milestone_id, body.reason, request_source(request), user.username)
    db.commit()
    return milestones.milestone_out(db, row)


@router.delete("/payment-milestones/{milestone_id}", status_code=204)
def ms_delete(milestone_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    milestones.delete(db, milestone_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


@router.post("/payment-milestones/{milestone_id}/payments", status_code=201)
def ms_payment(milestone_id: uuid.UUID, body: PaymentIn, request: Request, user: CurrentUser, db: Db):
    milestones.add_record(db, milestone_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return milestones.milestone_out(db, milestones.get_milestone(db, milestone_id))


@router.post("/payment-records/{record_id}/reverse")
def ms_reverse(record_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    row = milestones.reverse_record(db, record_id, body.reason, request_source(request), user.username)
    db.commit()
    return milestones.milestone_out(db, row)


ROUTERS = [router]
__all__ = ["ROUTERS", "jsonable", "row_snapshot"]
