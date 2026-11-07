"""Deliveries to the customer (v0.7.0), item by item.

A delivery (date, place, receiver, the receipt «رسید انبار» / «صورتجلسه تحویل») lists quantities per sales order item;
the delivered quantity of an item never exceeds the ordered one (422). An item fully delivered becomes ``delivered``
through ``recompute_item_status`` (the registered delivered check); when every item of the order is delivered the order
becomes ``delivered`` and BOMS creates the task «صدور فاکتور و پیگیری تسویه», the warranty end (``warranty_months``)
as a task on its date plus one ``execution.warranty_remind_days`` before it (v0.8.0), and the release reminder of a linked performance guarantee
(Phase 7b reminders). A delivery is reversed (deleted with a reason) while the order is not closed; statuses recompute.
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.execution import followups, sales_orders
from app.modules.execution.common import ZERO, get, get_sales_order, reason_required, today
from app.modules.execution.models import Delivery, DeliveryItem, SalesOrder, SalesOrderItem
from app.modules.parties import clock
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.system import settings


def deliveries_of(db: Session, sales_order_id: uuid.UUID) -> list[Delivery]:
    return list(db.scalars(select(Delivery).where(Delivery.sales_order_id == sales_order_id)
                           .order_by(Delivery.delivered_on, Delivery.created_at)))


def delivery_items(db: Session, delivery_id: uuid.UUID) -> list[DeliveryItem]:
    return list(db.scalars(select(DeliveryItem).where(DeliveryItem.delivery_id == delivery_id).order_by(DeliveryItem.created_at)))


def add_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    y, m = day.year + y, m + 1
    import calendar

    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def is_delivered(db: Session, line_item_id: uuid.UUID) -> bool | None:
    """Registered with sourcing's status function: True when fully delivered on a live sales order, False when on one
    and not fully delivered, None when on none."""
    rows = db.execute(select(SalesOrderItem).join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id).where(
        SalesOrderItem.line_item_id == line_item_id, SalesOrder.status != "cancelled")).scalars().all()
    if not rows:
        return None
    for row in rows:
        done = sales_orders.delivered_quantities(db, row.sales_order_id).get(row.id, ZERO)
        if done >= row.quantity:
            return True
    return False


def _after_change(db: Session, order: SalesOrder, source: str, actor: str | None) -> None:
    items = sales_orders.items_of(db, order.id)
    sourcing_items.recompute_items(db, [r.line_item_id for r in items], source, actor, cause="delivery")
    delivered = sales_orders.delivered_quantities(db, order.id)
    complete = all(delivered.get(r.id, ZERO) >= r.quantity for r in items)
    if complete and order.status in ("confirmed", "in_progress"):
        order.status, order.delivered_at = "delivered", clock.now()
        flush(db, "invalid_sales_order")
        events.record(db, "sales_order", order.id, "status", {"old_status": "in_progress", "new_status": "delivered",
                                                               "cause": "all items delivered"}, source, actor=actor)
        _on_delivered(db, order, source, actor)
    elif not complete and order.status == "delivered":
        order.status, order.delivered_at = "in_progress", None
        flush(db, "invalid_sales_order")
        events.record(db, "sales_order", order.id, "status", {"old_status": "delivered", "new_status": "in_progress",
                                                               "cause": "delivery reversed"}, source, actor=actor)
        followups.cancel(db, "delivery reversed", source, actor, ref_id=order.id, purposes=("invoice", "warranty_end", "warranty_remind"))
        if order.performance_guarantee_id:
            from app.modules.tenders import reminders as tender_reminders

            tender_reminders.cancel(db, "delivery reversed", source, actor, ref_id=order.performance_guarantee_id,
                                    purposes=("guarantee_release",))
    else:
        sales_orders.set_in_progress(db, order, "delivery", source, actor)


def _on_delivered(db: Session, order: SalesOrder, source: str, actor: str | None) -> None:
    days = settings.get(db, "execution.invoice_followup_days")
    followups.create(db, case_id=order.case_id, purpose="invoice", ref_id=order.id, party_id=order.customer_party_id,
                     action=f"صدور فاکتور و پیگیری تسویه {order.number}", due_on=today() + timedelta(days=days),
                     source=source, actor=actor)
    if order.warranty_months:
        last = max((d.delivered_on for d in deliveries_of(db, order.id)), default=today())
        ends = add_months(last, order.warranty_months)
        followups.create(db, case_id=order.case_id, purpose="warranty_end", ref_id=order.id, party_id=order.customer_party_id,
                         action=f"پایان گارانتی {order.number}", due_on=ends, source=source, actor=actor)
        before = settings.get(db, "execution.warranty_remind_days")
        if before and ends - timedelta(days=before) >= today():
            followups.create(db, case_id=order.case_id, purpose="warranty_remind", ref_id=order.id,
                             party_id=order.customer_party_id, action=f"یادآوری پایان گارانتی {order.number}",
                             due_on=ends - timedelta(days=before), days_before=before, remind_of_due=ends,
                             source=source, actor=actor)
    if order.performance_guarantee_id:
        from app.modules.tenders import guarantees

        g = guarantees.get_guarantee(db, order.performance_guarantee_id)
        days_left = (g.valid_until - today()).days if g.valid_until and g.valid_until > today() else None
        guarantees.schedule_release(db, g, days_left, source, actor)


def create_delivery(db: Session, data: dict, source: str, actor: str | None = None) -> Delivery:
    order = get_sales_order(db, data["sales_order_id"])
    if order.status not in ("confirmed", "in_progress"):
        raise Conflict("sales_order_not_open", f"The sales order is {order.status}", {"status": order.status})
    if data.get("receipt_document_id"):
        documents.get(db, data["receipt_document_id"])
    if data.get("shipment_id"):
        from app.modules.execution.logistics import get_shipment

        get_shipment(db, data["shipment_id"])
    lines = data.get("items") or []
    if not lines:
        raise AppError("no_items", "A delivery lists what was delivered", status=422)
    by_id = {r.id: r for r in sales_orders.items_of(db, order.id)}
    delivered = sales_orders.delivered_quantities(db, order.id)
    row = Delivery(sales_order_id=order.id, shipment_id=data.get("shipment_id"), delivered_on=data["delivered_on"],
                   delivery_place=data.get("delivery_place") or order.delivery_place, receiver_name=data.get("receiver_name"),
                   receipt_document_id=data.get("receipt_document_id"), note=data.get("note"))
    db.add(row)
    flush(db, "invalid_delivery")
    for line in lines:
        item = by_id.get(line["sales_order_item_id"])
        if item is None:
            raise AppError("item_not_of_order", "The item belongs to another order",
                           {"sales_order_item_id": str(line["sales_order_item_id"])}, status=422)
        done = delivered.get(item.id, ZERO)
        if done + line["quantity"] > item.quantity:
            raise AppError("over_delivered", "More than the ordered quantity would be delivered",
                           {"sales_order_item_id": str(item.id), "ordered": str(item.quantity), "delivered": str(done),
                            "quantity": str(line["quantity"])}, status=422)
        delivered[item.id] = done + line["quantity"]
        db.add(DeliveryItem(delivery_id=row.id, sales_order_item_id=item.id, quantity=line["quantity"]))
    flush(db, "invalid_delivery_item")
    events.record(db, "delivery", row.id, "create", jsonable({
        "sales_order_id": order.id, "delivered_on": row.delivered_on, "receiver_name": row.receiver_name,
        "receipt_document_id": row.receipt_document_id,
        "items": [{"sales_order_item_id": x["sales_order_item_id"], "quantity": x["quantity"]} for x in lines]}),
        source, actor=actor)
    _after_change(db, order, source, actor)
    return row


def reverse(db: Session, delivery_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> SalesOrder:
    row = get(db, Delivery, delivery_id, "Delivery")
    reason = reason_required(reason, "reason_required", "Reversing a delivery needs a reason")
    order = get_sales_order(db, row.sales_order_id)
    if order.status in ("closed", "cancelled"):
        raise Conflict("sales_order_closed", "A delivery of a closed sales order is never reversed", {"status": order.status})
    snapshot = {"delivery": row_snapshot(row), "items": [row_snapshot(i) for i in delivery_items(db, row.id)]}
    for line in delivery_items(db, row.id):
        db.delete(line)
    db.flush()
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "delivery", delivery_id, "reverse", jsonable({"deleted": snapshot, "reason": reason}), source, actor=actor)
    _after_change(db, order, source, actor)
    return order


def delivery_out(db: Session, row: Delivery) -> dict:
    return jsonable({**row_snapshot(row), "items": [row_snapshot(i) for i in delivery_items(db, row.id)]})


def warranty_ends_on(db: Session, order: SalesOrder) -> date | None:
    if not order.warranty_months or order.status not in ("delivered", "closed"):
        return None
    last = max((d.delivered_on for d in deliveries_of(db, order.id)), default=None)
    return add_months(last, order.warranty_months) if last else None
