"""Sales invoices, supplier invoices, actual costs and ratings that point at a party block its delete
(``parties.references``; 409 with the counts)."""
from sqlalchemy import func, select

from app.modules.finance.models import ActualCost, PartyRating, PurchaseInvoice, SalesInvoice
from app.modules.parties.references import register_reference_counter


def _count(db, model, condition) -> int:
    return db.scalar(select(func.count()).select_from(model).where(condition)) or 0


def party_counts(db, party_id) -> dict[str, int]:
    return {"sales_invoices": _count(db, SalesInvoice, SalesInvoice.customer_party_id == party_id),
            "purchase_invoices": _count(db, PurchaseInvoice, PurchaseInvoice.supplier_party_id == party_id),
            "actual_costs": _count(db, ActualCost, ActualCost.party_id == party_id),
            "ratings": _count(db, PartyRating, PartyRating.party_id == party_id)}


register_reference_counter("finance", party_counts)
