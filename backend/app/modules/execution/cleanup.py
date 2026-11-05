"""Case cascade delete (test-data cleanup): every execution row of the case (sales and purchase orders with items and
changes, milestones and payments, process checklists, shipments with items / events / documents, inspections,
receipts, deliveries, claims); the follow-ups BOMS created for them are cancelled. Files stay in the store."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.execution import followups
from app.modules.execution.models import (Claim, Delivery, DeliveryItem, ExecutionFollowup, Inspection, PaymentMilestone,
                                          PaymentRecord, Process, ProcessStep, PurchaseOrder, PurchaseOrderChange,
                                          PurchaseOrderItem, Receipt, ReceiptItem, SalesOrder, SalesOrderChange,
                                          SalesOrderItem, Shipment, ShipmentDocument, ShipmentEvent, ShipmentItem)
from app.modules.sourcing.common import flush, row_snapshot


def cleanup_case(db: Session, case_id: uuid.UUID, note: str, source: str, actor: str | None) -> dict:
    so_ids = list(db.scalars(select(SalesOrder.id).where(SalesOrder.case_id == case_id)))
    po_ids = list(db.scalars(select(PurchaseOrder.id).where(PurchaseOrder.case_id == case_id)))
    sh_ids = list(db.scalars(select(Shipment.id).where(Shipment.case_id == case_id)))
    pr_ids = list(db.scalars(select(Process.id).where(Process.case_id == case_id)))
    ms_ids = list(db.scalars(select(PaymentMilestone.id).where(PaymentMilestone.case_id == case_id)))
    rc_ids = list(db.scalars(select(Receipt.id).where(Receipt.purchase_order_id.in_(po_ids)))) if po_ids else []
    dl_ids = list(db.scalars(select(Delivery.id).where(Delivery.sales_order_id.in_(so_ids)))) if so_ids else []
    if not (so_ids or po_ids or sh_ids or pr_ids or ms_ids or db.scalar(select(Claim.id).where(Claim.case_id == case_id).limit(1))):
        return {"counts": {}}
    cancelled = followups.cancel(db, note, source, actor, case_id=case_id)
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids))):
        po.supersedes_id = None
    db.flush()
    groups = [
        ("execution_followups", select(ExecutionFollowup).where(ExecutionFollowup.case_id == case_id)),
        ("claims", select(Claim).where(Claim.case_id == case_id)),
        ("delivery_items", select(DeliveryItem).where(DeliveryItem.delivery_id.in_(dl_ids))),
        ("deliveries", select(Delivery).where(Delivery.id.in_(dl_ids))),
        ("receipt_items", select(ReceiptItem).where(ReceiptItem.receipt_id.in_(rc_ids))),
        ("receipts", select(Receipt).where(Receipt.id.in_(rc_ids))),
        ("inspections", select(Inspection).where(Inspection.case_id == case_id)),
        ("process_steps", select(ProcessStep).where(ProcessStep.process_id.in_(pr_ids))),
        ("processes", select(Process).where(Process.id.in_(pr_ids))),
        ("shipment_items", select(ShipmentItem).where(ShipmentItem.shipment_id.in_(sh_ids))),
        ("shipment_events", select(ShipmentEvent).where(ShipmentEvent.shipment_id.in_(sh_ids))),
        ("shipment_documents", select(ShipmentDocument).where(ShipmentDocument.shipment_id.in_(sh_ids))),
        ("shipments", select(Shipment).where(Shipment.id.in_(sh_ids))),
        ("payment_records", select(PaymentRecord).where(PaymentRecord.milestone_id.in_(ms_ids))),
        ("payment_milestones", select(PaymentMilestone).where(PaymentMilestone.id.in_(ms_ids))),
        ("purchase_order_changes", select(PurchaseOrderChange).where(PurchaseOrderChange.purchase_order_id.in_(po_ids))),
        ("purchase_order_items", select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id.in_(po_ids))),
        ("purchase_orders", select(PurchaseOrder).where(PurchaseOrder.id.in_(po_ids))),
        ("sales_order_changes", select(SalesOrderChange).where(SalesOrderChange.sales_order_id.in_(so_ids))),
        ("sales_order_items", select(SalesOrderItem).where(SalesOrderItem.sales_order_id.in_(so_ids))),
        ("sales_orders", select(SalesOrder).where(SalesOrder.id.in_(so_ids))),
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
    return {"counts": {k: v for k, v in counts.items() if v}, "cancelled_followups": [str(f) for f in cancelled],
            "rows": snapshot}
