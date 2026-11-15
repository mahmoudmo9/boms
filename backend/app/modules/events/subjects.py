"""The object an event is about, for the generated sentence (v0.10.1 section 1.1): «سفارش خرید PO-1405-0007 ثبت شد».

An event on a case often concerns a child record (``purchase_order_add`` carries ``purchase_order_id``); otherwise the
event's own entity is the subject. Codes are read in one query per type for a page of events. Read-only.
"""
from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.orm import Session

# payload key → subject type (first match wins; the order puts the specific child records first)
DATA_KEYS = (
    ("purchase_order_id", "purchase_order"), ("sales_order_id", "sales_order"), ("quote_id", "quote"),
    ("cost_sheet_id", "cost_sheet"), ("rfq_id", "rfq"), ("offer_id", "offer"), ("tender_id", "tender"),
    ("process_id", "process"), ("shipment_id", "shipment"), ("inquiry_id", "inquiry"), ("case_id", "case"),
)

# subject type → SELECT id, code, name FROM … x (the caller adds WHERE x.id = ANY(:ids))
LOOKUPS = {
    "case": "SELECT x.id, x.code, x.title FROM ops.case x",
    "inquiry": "SELECT x.id, x.code, NULL FROM ops.inquiry x",
    "rfq": "SELECT x.id, x.code, x.title FROM ops.rfq x",
    "offer": "SELECT x.id, NULL, coalesce(p.name_fa, p.name_en) FROM ops.supplier_offer x JOIN core.party p ON p.id = x.party_id",
    "quote": "SELECT x.id, x.number, NULL FROM ops.quote x",
    "cost_sheet": "SELECT x.id, 'v' || x.version, NULL FROM ops.cost_sheet x",
    "process": "SELECT x.id, NULL, x.name FROM ops.process x",
    "tender": "SELECT x.id, x.code, NULL FROM ops.tender x",
    "sales_order": "SELECT x.id, x.number, NULL FROM ops.sales_order x",
    "purchase_order": "SELECT x.id, x.number, NULL FROM ops.purchase_order x",
    "shipment": "SELECT x.id, x.code, NULL FROM ops.shipment x",
    "sales_invoice": "SELECT x.id, x.number, NULL FROM ops.sales_invoice x",
    "purchase_invoice": "SELECT x.id, x.supplier_invoice_no, NULL FROM ops.purchase_invoice x",
    "guarantee": "SELECT x.id, coalesce(x.code, x.number), NULL FROM ops.guarantee x",
    "party": "SELECT x.id, x.code, coalesce(x.name_fa, x.name_en) FROM core.party x",
    "product": "SELECT x.id, x.code, coalesce(x.name_fa, x.name_en) FROM core.product x",
}


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def subject_ref(entity_type: str, entity_id, data: dict | None) -> tuple[str, str | None]:
    for key, kind in DATA_KEYS:
        if (data or {}).get(key) and kind != entity_type:
            return kind, str(data[key])
    return entity_type, entity_id


def subjects(db: Session, events) -> list[dict]:
    """One ``{type, id, code, name}`` per event, in order (code and name are None when unknown or deleted)."""
    refs = [subject_ref(e.entity_type, e.entity_id, e.data) for e in events]
    wanted: dict[str, set[uuid.UUID]] = defaultdict(set)
    for kind, ref in refs:
        if kind in LOOKUPS and (u := _uuid(ref)):
            wanted[kind].add(u)
    found: dict[tuple[str, str], tuple] = {}
    for kind, ids in wanted.items():
        for row in db.execute(text(LOOKUPS[kind] + " WHERE x.id = ANY(:ids)"), {"ids": list(ids)}).all():
            found[(kind, str(row[0]))] = (row[1], row[2])
    out = []
    for (kind, ref), e in zip(refs, events):
        code, name = found.get((kind, str(ref)), (None, None))
        if code is None and kind != e.entity_type:
            code = (e.data or {}).get("number")          # e.g. a deleted order still named by its event
        out.append({"type": kind, "id": ref, "code": code, "name": name})
    return out
