"""Quotes that point at a party (buyer) or contact block their delete (``parties.references``)."""

from sqlalchemy import func, select

from app.modules.parties.references import register_reference_counter
from app.modules.quotes.models import Quote


def party_counts(db, party_id) -> dict[str, int]:
    return {"quotes": db.scalar(select(func.count()).select_from(Quote).where(Quote.buyer_party_id == party_id)) or 0}


def contact_counts(db, contact_id) -> dict[str, int]:
    return {"quotes": db.scalar(select(func.count()).select_from(Quote).where(Quote.contact_id == contact_id)) or 0}


register_reference_counter("quotes", party_counts, contact_fn=contact_counts)
