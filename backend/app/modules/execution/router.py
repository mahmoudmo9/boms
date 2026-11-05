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
from app.modules.execution.schemas import (AmendIn, ConfirmIn, MilestoneIn, MilestonePatch, OutputIn, PaymentIn,
                                           PoApproveIn, PoConfirmIn, PoReadyDateIn, PoSentIn, PoStatusIn, ProcessIn,
                                           ProcessTemplateIn, ProcessTemplatePatch, PurchaseOrderItemPatch,
                                           PurchaseOrderPatch, ReasonIn, SalesOrderFromProposal, SalesOrderFromQuote,
                                           SalesOrderItemPatch, SalesOrderManual, SalesOrderPatch, StepIn, StepOrderIn,
                                           StepPatch)
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


# ---- purchase orders (M2) ------------------------------------------------------------------------------------------------

def _po(db: Session, po_id: uuid.UUID) -> dict:
    from app.modules.execution import purchase_orders
    from app.modules.execution.common import get_purchase_order

    return purchase_orders.po_out(db, get_purchase_order(db, po_id))


@router.post("/sales-orders/{order_id}/purchase-orders", status_code=201)
def po_create(order_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    """"Create POs": one draft per supplier of the items' selected offers; items without one are listed."""
    from app.modules.execution import purchase_orders

    result = purchase_orders.create_from_sales_order(db, order_id, user.calendar, request_source(request), user.username)
    db.commit()
    return {"created": [_po(db, po.id) for po in result["created"]], "unresolved": result["unresolved"]}


@router.get("/purchase-orders/{po_id}")
def po_get(po_id: uuid.UUID, _: CurrentUser, db: Db):
    return _po(db, po_id)


@router.patch("/purchase-orders/{po_id}")
def po_patch(po_id: uuid.UUID, body: PurchaseOrderPatch, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    purchase_orders.update_order(db, po_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return _po(db, po_id)


@router.delete("/purchase-orders/{po_id}", status_code=204)
def po_delete(po_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    purchase_orders.delete_order(db, po_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


@router.patch("/purchase-order-items/{item_id}")
def po_item_patch(item_id: uuid.UUID, body: PurchaseOrderItemPatch, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    row = purchase_orders.update_item(db, item_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return _po(db, row.purchase_order_id)


@router.delete("/purchase-order-items/{item_id}")
def po_item_delete(item_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    po = purchase_orders.remove_item(db, item_id, request_source(request), user.username)
    db.commit()
    return _po(db, po.id)


@router.post("/purchase-orders/{po_id}/approve")
def po_approve(po_id: uuid.UUID, request: Request, user: CurrentUser, db: Db, body: PoApproveIn | None = None):
    from app.modules.execution import purchase_orders

    purchase_orders.approve(db, po_id, body.model_dump() if body else {}, request_source(request), user.username)
    db.commit()
    return _po(db, po_id)


@router.post("/purchase-orders/{po_id}/mark-sent")
def po_sent(po_id: uuid.UUID, body: PoSentIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    purchase_orders.mark_sent(db, po_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return _po(db, po_id)


@router.post("/purchase-orders/{po_id}/confirm")
def po_confirm(po_id: uuid.UUID, body: PoConfirmIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    purchase_orders.confirm(db, po_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return _po(db, po_id)


@router.post("/purchase-orders/{po_id}/ready-date")
def po_ready_date(po_id: uuid.UUID, body: PoReadyDateIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    purchase_orders.change_ready_date(db, po_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return _po(db, po_id)


@router.post("/purchase-orders/{po_id}/status")
def po_status(po_id: uuid.UUID, body: PoStatusIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    purchase_orders.set_status(db, po_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return _po(db, po_id)


@router.post("/purchase-orders/{po_id}/revise", status_code=201)
def po_revise(po_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    new = purchase_orders.revise(db, po_id, request_source(request), user.username)
    db.commit()
    return _po(db, new.id)


@router.post("/purchase-orders/{po_id}/cancel")
def po_cancel(po_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import purchase_orders

    purchase_orders.cancel(db, po_id, body.reason, request_source(request), user.username)
    db.commit()
    return _po(db, po_id)


@router.get("/purchase-orders/{po_id}/print", response_class=HTMLResponse)
def po_print(po_id: uuid.UUID, _: CurrentUser, db: Db):
    from app.modules.execution.common import get_purchase_order

    return HTMLResponse(output.render_html(output.purchase_order_context(db, get_purchase_order(db, po_id))))


@router.post("/purchase-orders/{po_id}/outputs", status_code=201)
def po_output(po_id: uuid.UUID, body: OutputIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution.common import get_purchase_order

    po = get_purchase_order(db, po_id)
    result = output.generate(db, "purchase_order", po, output.purchase_order_context(db, po), body.format,
                             request_source(request), user.username)
    db.commit()
    return result


# ---- process checklists (M2) ----------------------------------------------------------------------------------------------

@router.get("/process-templates")
def pt_list(_: CurrentUser, db: Db, include_archived: bool = False):
    from app.modules.execution import process

    return [process.template_out(db, t) for t in process.list_templates(db, include_archived)]


@router.post("/process-templates", status_code=201)
def pt_create(body: ProcessTemplateIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process

    row = process.create_template(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return process.template_out(db, row)


@router.patch("/process-templates/{template_id}")
def pt_patch(template_id: uuid.UUID, body: ProcessTemplatePatch, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process

    data = body.model_dump(exclude_unset=True)
    if body.steps is not None:
        data["steps"] = [s.model_dump() for s in body.steps]
    row = process.update_template(db, template_id, data, request_source(request), user.username)
    db.commit()
    return process.template_out(db, row)


@router.delete("/process-templates/{template_id}", status_code=204)
def pt_delete(template_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process

    process.delete_template(db, template_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


@router.post("/cases/{case_id}/processes", status_code=201)
def process_create(case_id: uuid.UUID, body: ProcessIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process

    row = process.create_process(db, case_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return process.process_out(db, row)


@router.get("/processes/{process_id}")
def process_get(process_id: uuid.UUID, _: CurrentUser, db: Db):
    from app.modules.execution import process
    from app.modules.execution.common import get
    from app.modules.execution.models import Process

    return process.process_out(db, get(db, Process, process_id, "Process"))


@router.post("/processes/{process_id}/steps", status_code=201)
def step_add(process_id: uuid.UUID, body: StepIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process
    from app.modules.execution.common import get
    from app.modules.execution.models import Process

    process.add_step(db, process_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return process.process_out(db, get(db, Process, process_id, "Process"))


@router.post("/processes/{process_id}/reorder")
def step_reorder(process_id: uuid.UUID, body: StepOrderIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process
    from app.modules.execution.common import get
    from app.modules.execution.models import Process

    process.reorder(db, process_id, body.step_ids, request_source(request), user.username)
    db.commit()
    return process.process_out(db, get(db, Process, process_id, "Process"))


@router.patch("/process-steps/{step_id}")
def step_patch(step_id: uuid.UUID, body: StepPatch, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process
    from app.modules.execution.common import get
    from app.modules.execution.models import Process

    step = process.update_step(db, step_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return process.process_out(db, get(db, Process, step.process_id, "Process"))


@router.delete("/process-steps/{step_id}")
def step_delete(step_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    from app.modules.execution import process
    from app.modules.execution.common import get
    from app.modules.execution.models import Process, ProcessStep

    process_id = get(db, ProcessStep, step_id, "Process step").process_id
    process.remove_step(db, step_id, request_source(request), user.username)
    db.commit()
    return process.process_out(db, get(db, Process, process_id, "Process"))


ROUTERS = [router]
__all__ = ["ROUTERS", "jsonable", "row_snapshot"]
