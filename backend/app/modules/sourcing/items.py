"""Line items of any shape: owned by an inquiry and, after conversion, by its case (same rows, never copied).

``specs`` is a jsonb list of {key, value, unit?} pairs; keys are free text with suggestions from earlier use.
"""

import uuid
from collections import Counter

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.text import normalize_fa
from app.modules.events import service as events
from app.modules.sourcing.common import diff, document_count, flush, jsonable, row_snapshot
from app.modules.sourcing.models import Case, Inquiry, LineItem, OfferItem, RfqItem

OPEN_CASE = "open"
ITEM_FIELDS = ("position", "name", "description", "product_id", "quantity", "unit_code", "unit_text",
                  "target_price", "target_currency", "destination_country_iso2", "incoterm", "incoterm_place",
                  "required_by", "packaging", "hs_code", "route", "notes", "specs")


def key_norm(key: str) -> str:
    return (normalize_fa(key) or "").lower()


def clean_specs(specs: list[dict] | None) -> list[dict]:
    """Trim keys/values; drop rows without a key; later duplicates of a key (case-insensitive) win."""
    out: dict[str, dict] = {}
    for spec in specs or []:
        key = (spec.get("key") or "").strip()
        if not key:
            continue
        row = {"key": key, "value": (spec.get("value") or "").strip()}
        unit = (spec.get("unit") or "").strip()
        if unit:
            row["unit"] = unit
        out[key_norm(key)] = row
    return list(out.values())


def get_item(db: Session, item_id: uuid.UUID) -> LineItem:
    item = db.get(LineItem, item_id)
    if item is None:
        raise NotFound("not_found", "Line item not found")
    return item


def _owner(db: Session, inquiry_id: uuid.UUID | None, case_id: uuid.UUID | None) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    if not inquiry_id and not case_id:
        raise AppError("owner_required", "A line item belongs to an inquiry or a case", status=422)
    if inquiry_id:
        inquiry = db.get(Inquiry, inquiry_id)
        if inquiry is None:
            raise NotFound("not_found", "Inquiry not found")
        if inquiry.status == "converted":
            case = db.scalar(select(Case).where(Case.inquiry_id == inquiry.id))
            return inquiry.id, case.id if case else None
        return inquiry.id, case_id
    case = db.get(Case, case_id)
    if case is None:
        raise NotFound("not_found", "Case not found")
    return case.inquiry_id, case.id


def items_of(db: Session, *, inquiry_id: uuid.UUID | None = None, case_id: uuid.UUID | None = None,
             include_cancelled: bool = True) -> list[LineItem]:
    query = select(LineItem)
    if case_id:
        query = query.where(LineItem.case_id == case_id)
    elif inquiry_id:
        query = query.where(LineItem.inquiry_id == inquiry_id)
    else:
        return []
    if not include_cancelled:
        query = query.where(LineItem.status != "cancelled")
    return list(db.scalars(query.order_by(LineItem.position, LineItem.created_at)))


def duplicate_warnings(items: list[LineItem]) -> list[dict]:
    """Same name twice inside one inquiry/case: a warning, not an error."""
    seen = Counter((normalize_fa(i.name) or "").lower() for i in items if i.status != "cancelled")
    return [{"code": "duplicate_name", "item_id": str(i.id), "name": i.name}
            for i in items if i.status != "cancelled" and seen[(normalize_fa(i.name) or "").lower()] > 1]


def _check_product(db: Session, product_id: uuid.UUID | None) -> None:
    if product_id:
        from app.modules.catalog import service as catalog

        catalog.get_product(db, product_id)


def _prepare(data: dict) -> dict:
    data = {k: v for k, v in data.items() if k in ITEM_FIELDS}
    if "specs" in data:
        data["specs"] = clean_specs(data["specs"])
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise AppError("name_required", "The item needs a name", status=422)
    for key in ("unit_text", "incoterm_place", "packaging"):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip() or None
    if data.get("destination_country_iso2"):
        data["destination_country_iso2"] = data["destination_country_iso2"].upper()
    return data


def add_items(db: Session, inquiry_id: uuid.UUID | None, case_id: uuid.UUID | None, items: list[dict], source: str,
              actor: str | None = None) -> list[LineItem]:
    inquiry_id, case_id = _owner(db, inquiry_id, case_id)
    existing = items_of(db, inquiry_id=inquiry_id, case_id=case_id)
    position = max((i.position for i in existing), default=0)
    created = []
    for data in items:
        data = _prepare(data)
        _check_product(db, data.get("product_id"))
        if data.get("position") is None:
            position += 1
            data["position"] = position
        else:
            position = max(position, data["position"])
        data.setdefault("specs", [])
        data = {k: v for k, v in data.items() if v is not None}
        row = LineItem(inquiry_id=inquiry_id, case_id=case_id, **data)
        db.add(row)
        flush(db, "invalid_item")
        events.record(db, "line_item", row.id, "create", jsonable({
            "inquiry_id": inquiry_id, "case_id": case_id, "name": row.name, "quantity": row.quantity,
            "unit": row.unit_code or row.unit_text}), source, actor=actor)
        created.append(row)
    return created


def update_item(db: Session, item_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> LineItem:
    item = get_item(db, item_id)
    changes = _prepare(changes)
    if "product_id" in changes:
        _check_product(db, changes["product_id"])
    if "route" in changes and changes["route"] is None:
        changes.pop("route")
    if "specs" in changes and changes["specs"] is None:
        changes["specs"] = []
    if "name" in changes and changes["name"] is None:
        changes.pop("name")
    changed = diff(item, changes)
    if changed:
        flush(db, "invalid_item")
        events.record(db, "line_item", item.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return item


def dependency_counts(db: Session, item_id: uuid.UUID) -> dict[str, int]:
    return {
        "rfqs": db.scalar(select(func.count()).select_from(RfqItem).where(RfqItem.line_item_id == item_id)) or 0,
        "offers": db.scalar(select(func.count()).select_from(OfferItem).where(OfferItem.line_item_id == item_id)) or 0,
        "documents": document_count(db, "line_item", [item_id]),
    }


def delete_item(db: Session, item_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    item = get_item(db, item_id)
    counts = dependency_counts(db, item_id)
    if any(counts.values()):
        raise Conflict("in_use", "The item is used by RFQs, offers or documents; cancel it instead", counts)
    snapshot = row_snapshot(item)
    db.delete(item)
    flush(db, "in_use")
    events.record(db, "line_item", item_id, "delete", {"deleted": snapshot}, source, actor=actor)


def cancel_item(db: Session, item_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> LineItem:
    item = get_item(db, item_id)
    if item.status != "cancelled":
        old = item.status
        item.status = "cancelled"
        flush(db)
        events.record(db, "line_item", item.id, "cancel", {"old_status": old, "reason": reason.strip()}, source,
                      actor=actor)
    return item


def set_no_coverage(db: Session, item_id: uuid.UUID, reason: str | None, source: str,
                    actor: str | None = None) -> LineItem:
    """Explicitly mark an item as not coverable (reason required), or clear the mark (reason None)."""
    item = get_item(db, item_id)
    confirmed = reason is not None
    if confirmed and not reason.strip():
        raise AppError("reason_required", "A reason is required", status=422)
    item.no_coverage_confirmed = confirmed
    item.no_coverage_reason = reason.strip() if confirmed else None
    flush(db)
    events.record(db, "line_item", item.id, "no_coverage" if confirmed else "no_coverage_clear",
                  {"reason": item.no_coverage_reason}, source, actor=actor)
    return item


def set_status(db: Session, item: LineItem, status: str, source: str, actor: str | None, reason: str) -> None:
    """Status driven by RFQ/offer events. Never moves an item backwards or out of cancelled/selected."""
    order = {"uncovered": 0, "rfq_sent": 1, "has_offer": 2, "selected": 3}
    if item.status not in order or status not in order or order[status] <= order[item.status]:
        return
    old = item.status
    item.status = status
    db.flush()
    events.record(db, "line_item", item.id, "status", {"old_status": old, "new_status": status, "reason": reason},
                  source, actor=actor)


def spec_key_suggestions(db: Session, q: str | None = None, limit: int = 20) -> list[str]:
    """Keys used before (most used first), grouped case-insensitively after Persian normalization."""
    rows = db.execute(text(
        """
        SELECT s->>'key' AS key FROM ops.line_item, jsonb_array_elements(specs) s
        WHERE s->>'key' IS NOT NULL
        """
    )).scalars().all()
    counts: Counter = Counter()
    display: dict[str, str] = {}
    for key in rows:
        norm = key_norm(key)
        counts[norm] += 1
        display.setdefault(norm, key)
    needle = key_norm(q or "")
    keys = [k for k, _ in counts.most_common() if needle in k]
    return [display[k] for k in keys[:limit]]
