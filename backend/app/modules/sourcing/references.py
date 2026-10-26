"""Sourcing rows that point at a party or contact, registered with ``parties.references`` (v0.3.1).

Inquiries, cases, RFQ recipients and offers block a party delete (also a cascade one); capability tags do not:
they are removed with the party by ``_cleanup``.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.events import service as events
from app.modules.parties.references import register_reference_counter
from app.modules.sourcing.common import flush
from app.modules.sourcing.models import Case, Inquiry, PartyCapability, RfqRecipient, SupplierOffer


def _count(db: Session, model, column, value: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(model).where(column == value)) or 0


def party_counts(db: Session, party_id: uuid.UUID) -> dict[str, int]:
    return {
        "inquiries": _count(db, Inquiry, Inquiry.party_id, party_id),
        "cases": _count(db, Case, Case.party_id, party_id),
        "rfq_recipients": _count(db, RfqRecipient, RfqRecipient.party_id, party_id),
        "offers": _count(db, SupplierOffer, SupplierOffer.party_id, party_id),
        "capabilities": _count(db, PartyCapability, PartyCapability.party_id, party_id),
    }


def contact_counts(db: Session, contact_id: uuid.UUID) -> dict[str, int]:
    return {
        "rfq_recipients": _count(db, RfqRecipient, RfqRecipient.contact_id, contact_id),
        "offers": _count(db, SupplierOffer, SupplierOffer.contact_id, contact_id),
    }


def _cleanup(db: Session, party_id: uuid.UUID, source: str, actor: str | None) -> None:
    rows = list(db.scalars(select(PartyCapability).where(PartyCapability.party_id == party_id)))
    if not rows:
        return
    removed = [{"kind": r.kind, "code": r.code, "tag": r.tag_text} for r in rows]
    for row in rows:
        db.delete(row)
    flush(db, "in_use")
    events.record(db, "party", party_id, "capabilities_removed", {"removed": removed}, source, actor=actor)


register_reference_counter("sourcing", party_counts, cleanup=_cleanup, contact_fn=contact_counts,
                           non_blocking=("capabilities",))
