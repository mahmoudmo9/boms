"""Sales orders, POs, claims, shipments and payment milestones that point at a party (customer, supplier, carrier,
counterparty, payer / payee) or contact block their delete (``parties.references``)."""

from sqlalchemy import func, or_, select

from app.modules.execution.models import Claim, Inspection, PaymentMilestone, PurchaseOrder, SalesOrder, Shipment
from app.modules.parties.references import register_reference_counter


def _count(db, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(or_(*conditions))) or 0


def party_counts(db, party_id) -> dict[str, int]:
    return {
        "sales_orders": _count(db, SalesOrder, SalesOrder.customer_party_id == party_id),
        "purchase_orders": _count(db, PurchaseOrder, PurchaseOrder.supplier_party_id == party_id),
        "claims": _count(db, Claim, Claim.counterparty_id == party_id),
        "shipments": _count(db, Shipment, Shipment.carrier_party_id == party_id, Shipment.forwarder_party_id == party_id,
                            Shipment.insurer_party_id == party_id),
        "inspections": _count(db, Inspection, Inspection.inspector_party_id == party_id),
        "payment_milestones": _count(db, PaymentMilestone, PaymentMilestone.party_id == party_id),
    }


def contact_counts(db, contact_id) -> dict[str, int]:
    return {"sales_orders": _count(db, SalesOrder, SalesOrder.contact_id == contact_id),
            "purchase_orders": _count(db, PurchaseOrder, PurchaseOrder.contact_id == contact_id)}


register_reference_counter("execution", party_counts, contact_fn=contact_counts)
