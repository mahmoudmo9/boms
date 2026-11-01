"""Costs of taking part in a tender (documents purchase, guarantee fees, deposits, travel, other).

"Add to cost sheet" adds one case-level ``other`` line «هزینه شرکت در مناقصه» with the non-refundable total to the
case's current draft cost sheet (through the costing service); 422 ``no_draft_sheet`` when there is none.
"""
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.modules.costing import service as costing
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.tenders.common import get_tender
from app.modules.tenders.models import TenderCost

FIELDS = ("kind", "amount", "amount_currency", "paid_on", "refundable", "refunded_on", "note", "document_id")
SHEET_LINE_LABEL = "هزینه شرکت در مناقصه"


def get_cost(db: Session, cost_id: uuid.UUID) -> TenderCost:
    row = db.get(TenderCost, cost_id)
    if row is None:
        raise NotFound("not_found", "Tender cost not found")
    return row


def costs_of(db: Session, tender_id: uuid.UUID) -> list[TenderCost]:
    return list(db.scalars(select(TenderCost).where(TenderCost.tender_id == tender_id).order_by(TenderCost.created_at)))


def add_cost(db: Session, tender_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> TenderCost:
    tender = get_tender(db, tender_id)
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    refundable = data.get("refundable")
    if refundable is None:
        refundable = data.get("kind") == "deposit"   # a deposit comes back by default
    row = TenderCost(tender_id=tender.id, kind=data["kind"], amount=Decimal(data["amount"]),
                     amount_currency=data.get("amount_currency") or "IRR", refundable=bool(refundable),
                     **{k: data.get(k) for k in ("paid_on", "refunded_on", "note", "document_id") if data.get(k) is not None})
    db.add(row)
    flush(db, "invalid_tender_cost")
    events.record(db, "tender", tender.id, "cost_add", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def update_cost(db: Session, cost_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> TenderCost:
    row = get_cost(db, cost_id)
    if changes.get("document_id"):
        documents.get(db, changes["document_id"])
    changed = {}
    for key in FIELDS:
        if key in changes and changes[key] != getattr(row, key):
            if key in ("kind", "amount", "amount_currency", "refundable") and changes[key] is None:
                continue
            changed[key] = {"old": getattr(row, key), "new": changes[key]}
            setattr(row, key, changes[key])
    if changed:
        flush(db, "invalid_tender_cost")
        events.record(db, "tender", row.tender_id, "cost_update", jsonable({"cost_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def delete_cost(db: Session, cost_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_cost(db, cost_id)
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "tender", row.tender_id, "cost_delete", jsonable(snapshot), source, actor=actor)


def totals(rows: list[TenderCost]) -> dict[str, dict[str, str]]:
    """Per currency: spent (paid), refundable still outstanding (paid, refundable, not refunded yet), refunded,
    not paid yet, and the net cost (everything that does not come back)."""
    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: dict.fromkeys(
        ("spent", "refundable_outstanding", "refunded", "unpaid", "net"), Decimal(0)))
    for r in rows:
        t = out[r.amount_currency]
        if r.paid_on is None:
            t["unpaid"] += r.amount
        else:
            t["spent"] += r.amount
            if r.refundable and r.refunded_on is None:
                t["refundable_outstanding"] += r.amount
            if r.refundable and r.refunded_on is not None:
                t["refunded"] += r.amount
        if not r.refundable:
            t["net"] += r.amount
    return {cur: {k: str(v) for k, v in vals.items()} for cur, vals in out.items()}


def add_to_cost_sheet(db: Session, tender_id: uuid.UUID, source: str, actor: str | None = None) -> dict:
    """One ``other`` case line with the non-refundable total, per currency, on the current draft sheet."""
    tender = get_tender(db, tender_id)
    drafts = [s for s in costing.sheets_of(db, tender.case_id) if s.status == "draft"]
    if not drafts:
        raise AppError("no_draft_sheet", "The case has no draft cost sheet; create a new version first",
                       {"final_sheet": str(costing.current_sheet(db, tender.case_id).id)
                        if costing.current_sheet(db, tender.case_id) else None}, status=422)
    sheet = drafts[0]
    added = []
    for currency, t in totals(costs_of(db, tender.id)).items():
        net = Decimal(t["net"])
        if net <= 0:
            continue
        line = costing.add_line(db, sheet.id, {"kind": "other", "label": SHEET_LINE_LABEL, "scope": "case",
                                               "basis": "total", "amount": net, "currency": currency,
                                               "allocation": "by_value", "notes": f"tender {tender.tender_no or ''}".strip()},
                                source, actor)
        added.append({"line_id": str(line.id), "amount": str(net), "currency": currency})
    if not added:
        raise AppError("nothing_to_add", "There is no non-refundable tender cost to add", status=422)
    events.record(db, "tender", tender.id, "costs_to_sheet", {"sheet_id": str(sheet.id), "lines": added}, source,
                  actor=actor)
    return {"sheet_id": str(sheet.id), "lines": added}
