"""Envelopes A/B/C of a tender: a checklist copied from a template, edited per tender (add, remove, reorder).

Statuses follow SetadSuite (not ready / in progress / needs signature / ready / submitted). An item that uses an
expired library document cannot be ``ready``; the bid bond item of envelope A is ``ready`` only when its guarantee
is issued or later, and follows the guarantee's status.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.tenders import library
from app.modules.tenders.common import get_tender
from app.modules.tenders.models import EnvelopeItem, Guarantee

ENVELOPES = ("A", "B", "C")
DONE = ("ready", "submitted")
ISSUED_OR_LATER = ("issued", "ready_to_upload", "submitted", "extended")


def get_item(db: Session, item_id: uuid.UUID) -> EnvelopeItem:
    row = db.get(EnvelopeItem, item_id)
    if row is None:
        raise NotFound("not_found", "Envelope item not found")
    return row


def items_of(db: Session, tender_id: uuid.UUID) -> list[EnvelopeItem]:
    order = {e: i for i, e in enumerate(ENVELOPES)}
    rows = list(db.scalars(select(EnvelopeItem).where(EnvelopeItem.tender_id == tender_id)))
    return sorted(rows, key=lambda r: (order[r.envelope], r.position))


def progress(items: list[EnvelopeItem]) -> dict:
    """{envelope: [done, total]} plus "all" (SetadSuite envelope_progress)."""
    out = {e: [0, 0] for e in ENVELOPES}
    for it in items:
        out[it.envelope][1] += 1
        if it.status in DONE:
            out[it.envelope][0] += 1
    out["all"] = [sum(v[0] for v in out.values()), sum(v[1] for v in out.values())]
    return out


def item_out(db: Session, row: EnvelopeItem) -> dict:
    out = row_snapshot(row)
    if row.company_document_id:
        doc = library.get_document(db, row.company_document_id)
        state, days = library.doc_expiry(doc.expires_on)
        out["company_document"] = {"id": doc.id, "title": doc.title, "expires_on": doc.expires_on, "expiry": state,
                                   "days_left": days, "document_id": doc.document_id}
    else:
        out["company_document"] = None
    return jsonable(out)


def copy_template(db: Session, tender_id: uuid.UUID, template_id: uuid.UUID | None, source: str,
                  actor: str | None = None) -> list[EnvelopeItem]:
    """The tender's checklist from a template (the default when none is given); added after existing items."""
    tender = get_tender(db, tender_id)
    template = library.get_template(db, template_id) if template_id else library.default_template(db)
    if template is None:
        return []
    bid = db.scalar(select(Guarantee).where(Guarantee.tender_id == tender.id, Guarantee.purpose == "bid",
                                            Guarantee.status != "cancelled").limit(1))
    added = []
    for line in library.template_lines(db, template.id):
        position = _next_position(db, tender.id, line.envelope)
        row = EnvelopeItem(tender_id=tender.id, envelope=line.envelope, position=position, title=line.title,
                           kind=line.kind, status="not_ready", guarantee_id=bid.id if bid and line.kind == "bid_bond" else None)
        db.add(row)
        db.flush()
        added.append(row)
    events.record(db, "tender", tender.id, "envelopes_from_template", {"template": template.name, "items": len(added)},
                  source, actor=actor)
    return added


def _next_position(db: Session, tender_id: uuid.UUID, envelope: str) -> int:
    return (db.scalar(select(func.max(EnvelopeItem.position)).where(EnvelopeItem.tender_id == tender_id,
                                                                    EnvelopeItem.envelope == envelope)) or 0) + 1


def add_item(db: Session, tender_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> EnvelopeItem:
    tender = get_tender(db, tender_id)
    title = (data.get("title") or "").strip()
    if not title:
        raise AppError("title_required", "The item needs a title", status=422)
    row = EnvelopeItem(tender_id=tender.id, envelope=data["envelope"], title=title, kind=data.get("kind") or "document",
                       position=_next_position(db, tender.id, data["envelope"]), status="not_ready", note=data.get("note"))
    db.add(row)
    flush(db, "invalid_envelope_item")
    if data.get("company_document_id") or data.get("document_id") or data.get("status"):
        update_item(db, row.id, {k: data.get(k) for k in ("company_document_id", "document_id", "status")
                                 if data.get(k) is not None}, source, actor)
    events.record(db, "tender", tender.id, "envelope_item_add", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def _check_ready(db: Session, row: EnvelopeItem, status: str) -> None:
    if status not in DONE:
        return
    if row.company_document_id:
        doc = library.get_document(db, row.company_document_id)
        if library.doc_expiry(doc.expires_on)[0] == "expired":
            raise AppError("company_document_expired", "The library document has expired; renew it first",
                           {"title": doc.title, "expires_on": doc.expires_on.isoformat()}, status=422)
    if row.kind == "bid_bond":
        g = db.get(Guarantee, row.guarantee_id) if row.guarantee_id else None
        if g is None or g.status not in ISSUED_OR_LATER:
            raise AppError("guarantee_not_issued", "The bid bond is not issued yet",
                           {"guarantee_status": g.status if g else None}, status=422)


def update_item(db: Session, item_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> EnvelopeItem:
    row = get_item(db, item_id)
    if changes.get("company_document_id"):
        doc = library.get_document(db, changes["company_document_id"])
        # picking a library document fills the item (its file); an expired one leaves the item not ready
        if "document_id" not in changes and doc.document_id:
            changes["document_id"] = doc.document_id
        if "status" not in changes and row.status not in DONE and doc.document_id and \
                library.doc_expiry(doc.expires_on)[0] != "expired":
            changes["status"] = "ready"
    if changes.get("document_id"):
        documents.get(db, changes["document_id"])
    if changes.get("title") is not None:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise AppError("title_required", "The item needs a title", status=422)
    changed = {}
    for key in ("title", "note", "company_document_id", "document_id", "guarantee_id"):
        if key in changes and changes[key] != getattr(row, key):
            changed[key] = {"old": getattr(row, key), "new": changes[key]}
            setattr(row, key, changes[key])
    if "status" in changes and changes["status"] and changes["status"] != row.status:
        _check_ready(db, row, changes["status"])
        changed["status"] = {"old": row.status, "new": changes["status"]}
        row.status = changes["status"]
    if changed:
        flush(db, "invalid_envelope_item")
        events.record(db, "tender", row.tender_id, "envelope_item_update", jsonable({"item_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def remove_item(db: Session, item_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_item(db, item_id)
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    for i, other in enumerate([x for x in items_of(db, row.tender_id) if x.envelope == row.envelope], start=1):
        other.position = i
    db.flush()
    events.record(db, "tender", row.tender_id, "envelope_item_remove", jsonable(snapshot), source, actor=actor)


def reorder(db: Session, tender_id: uuid.UUID, envelope: str, item_ids: list[uuid.UUID], source: str,
            actor: str | None = None) -> list[EnvelopeItem]:
    current = [x for x in items_of(db, tender_id) if x.envelope == envelope]
    if sorted(map(str, item_ids)) != sorted(str(x.id) for x in current):
        raise AppError("invalid_order", "Give every item of the envelope exactly once", status=422)
    by_id = {str(x.id): x for x in current}
    for i, item_id in enumerate(item_ids, start=1):
        by_id[str(item_id)].position = i
    flush(db, "invalid_envelope_item")
    events.record(db, "tender", tender_id, "envelope_reorder", {"envelope": envelope, "items": [str(i) for i in item_ids]},
                  source, actor=actor)
    return [by_id[str(i)] for i in item_ids]


def follow_guarantee(db: Session, guarantee: Guarantee, source: str, actor: str | None) -> None:
    """The bid bond item follows its guarantee: issued (or later) -> ready, submitted -> submitted, back to
    requested -> in progress."""
    target = {"to_request": "not_ready", "requested": "in_progress", "issued": "ready", "ready_to_upload": "ready",
              "extended": "ready", "submitted": "submitted"}.get(guarantee.status)
    if target is None or guarantee.tender_id is None:
        return
    for row in db.scalars(select(EnvelopeItem).where(EnvelopeItem.tender_id == guarantee.tender_id,
                                                     EnvelopeItem.kind == "bid_bond")):
        if row.guarantee_id is None and guarantee.purpose == "bid":
            row.guarantee_id = guarantee.id
        if row.guarantee_id != guarantee.id or row.status == target:
            continue
        if row.status == "submitted" and target != "submitted":
            continue
        old, row.status = row.status, target
        db.flush()
        events.record(db, "tender", row.tender_id, "envelope_item_update", jsonable({
            "item_id": row.id, "changes": {"status": {"old": old, "new": target}}, "reason": "guarantee status"}),
            source, actor=actor)


def expired_documents(db: Session, tender_id: uuid.UUID) -> list[dict]:
    """Library documents linked to the tender's items that have expired (a submission blocker)."""
    out = []
    for row in items_of(db, tender_id):
        if row.company_document_id:
            doc = library.get_document(db, row.company_document_id)
            if library.doc_expiry(doc.expires_on)[0] == "expired":
                out.append({"item_id": str(row.id), "title": doc.title, "expires_on": doc.expires_on.isoformat()})
    return out
