"""Per-case coverage, the comparison matrix and the selected offer per item.

No currency conversion (there is no FX table): offers are grouped by currency, then by unit group (units of the
same convertible kind in ``sys.unit`` form one group). Inside a group the lowest normalized price is highlighted
unless the group mixes Incoterms: then every row gets a "not directly comparable" badge and no ranking.
"""

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.parties import service as parties
from app.modules.sourcing import items as items_service
from app.modules.sourcing.common import flush, jsonable, linked_documents
from app.modules.sourcing.dashboard import SELECTION_LOST_DAYS
from app.modules.sourcing.inquiries import get_case
from app.modules.sourcing.models import LineItem, OfferItem, SupplierOffer
from app.modules.sourcing.offers import is_valid
from app.modules.system.models import Unit

EXPIRING_DAYS = 7


def unit_index(db: Session) -> dict[str, Unit]:
    return {u.code: u for u in db.scalars(select(Unit))}


def unit_group(unit_code: str | None, unit_text: str | None, units: dict[str, Unit]) -> tuple[str, Decimal | None]:
    """(group key, factor to the group's base unit). Units of kind 'other' (box, drum…) and free-text units only
    compare with exactly the same unit."""
    unit = units.get(unit_code or "")
    if unit is not None and unit.kind != "other":
        return f"kind:{unit.kind}", Decimal(unit.base_factor)
    if unit is not None:
        return f"unit:{unit.code}", Decimal(1)
    if unit_text:
        return f"text:{unit_text.strip().lower()}", Decimal(1)
    return "none", Decimal(1)


def normalized_price(unit_price: Decimal | None, price_per_quantity: Decimal, factor: Decimal | None) -> Decimal | None:
    """Price per one base unit: unit_price / price_per_quantity / factor."""
    if unit_price is None or not factor:
        return None
    return unit_price / price_per_quantity / factor


def _offer_rows(db: Session, case_id: uuid.UUID) -> list[tuple[OfferItem, SupplierOffer]]:
    return list(db.execute(select(OfferItem, SupplierOffer).join(SupplierOffer, SupplierOffer.id == OfferItem.offer_id)
                           .where(SupplierOffer.case_id == case_id).order_by(SupplierOffer.received_at)).all())


def group_offers(rows: list[dict]) -> list[dict]:
    """rows: [{currency, unit_group, incoterm, normalized_price, ...}] -> currency groups with flags set on rows.

    Pure function (no database), used by both the API and the tests."""
    by_currency: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_currency[row["currency"]].append(row)
    groups = []
    for currency in sorted(by_currency):
        currency_rows = by_currency[currency]
        by_unit: dict[str, list[dict]] = defaultdict(list)
        for row in currency_rows:
            by_unit[row["unit_group"]].append(row)
        unit_groups = []
        for key in sorted(by_unit):
            members = by_unit[key]
            incoterms = {r.get("incoterm") or "" for r in members}
            comparable = len(incoterms) <= 1
            for row in members:
                row["lowest"] = False
                row["badges"] = [b for b in row.get("badges", []) if b not in ("incoterm_differs", "unit_differs")]
                if not comparable:
                    row["badges"].append("incoterm_differs")
                if len(by_unit) > 1:
                    row["badges"].append("unit_differs")
            priced = [r for r in members if r.get("normalized_price") is not None]
            if comparable and priced:
                best = min(r["normalized_price"] for r in priced)
                for row in priced:
                    row["lowest"] = row["normalized_price"] == best
            unit_groups.append({"unit_group": key, "comparable": comparable, "rows": members})
        groups.append({"currency": currency, "unit_groups": unit_groups})
    return groups


def comparison(db: Session, case_id: uuid.UUID, item_id: uuid.UUID | None = None, today: date | None = None) -> dict:
    case = get_case(db, case_id)
    today = today or clock.today()
    units = unit_index(db)
    items = [i for i in items_service.items_of(db, case_id=case.id) if item_id is None or i.id == item_id]
    if item_id and not items:
        raise NotFound("not_found", "Item not found in this case")
    party_names = {}
    per_item: dict[uuid.UUID, list[dict]] = defaultdict(list)
    offer_docs: dict[str, list] = {}
    for offer_item, offer in _offer_rows(db, case.id):
        if not is_valid(offer, today) or not offer_item.available:
            continue
        if offer.party_id not in party_names:
            party = parties.get_party(db, offer.party_id)
            party_names[offer.party_id] = (party.name_fa, party.name_en)
        key, factor = unit_group(offer_item.unit_code, offer_item.unit_text, units)
        oid = str(offer.id)
        if oid not in offer_docs:
            offer_docs[oid] = linked_documents(db, "offer", [offer.id])
        per_item[offer_item.line_item_id].append({
            "offer_item_id": str(offer_item.id), "offer_id": oid, "party_id": str(offer.party_id),
            "party_name_fa": party_names[offer.party_id][0], "party_name_en": party_names[offer.party_id][1],
            "unit_price": offer_item.unit_price, "currency": offer.currency,
            "price_per_quantity": offer_item.price_per_quantity, "unit_code": offer_item.unit_code,
            "unit_text": offer_item.unit_text, "unit_group": key, "normalized_price": normalized_price(offer_item.unit_price, offer_item.price_per_quantity, factor),
            "incoterm": offer.incoterm, "incoterm_place": offer.incoterm_place, "moq": offer_item.moq,
            "moq_unit": offer_item.moq_unit, "lead_time_days": offer_item.lead_time_days or offer.lead_time_days,
            "payment_terms": offer.payment_terms, "valid_until": offer.valid_until,
            "days_left": (offer.valid_until - today).days if offer.valid_until else None,
            "expiring": bool(offer.valid_until and (offer.valid_until - today).days < EXPIRING_DAYS),
            "compliance_notes": offer.compliance_notes, "spec_deviation": offer_item.spec_deviation,
            "packaging": offer_item.packaging, "notes": offer_item.notes, "documents": offer_docs[oid],
            "received_at": offer.received_at, "badges": [],
        })
    result = []
    for item in items:
        rows = per_item.get(item.id, [])
        for row in rows:
            row["selected"] = item.selected_offer_item_id is not None and row["offer_item_id"] == str(item.selected_offer_item_id)
        result.append({"item_id": str(item.id), "position": item.position, "name": item.name, "status": item.status,
                       "quantity": item.quantity, "unit_code": item.unit_code, "unit_text": item.unit_text,
                       "selected_offer_item_id": item.selected_offer_item_id, "groups": group_offers(rows)})
    return jsonable({"case_id": case.id, "items": result})


def selection_lost_ids(db: Session, item_ids: list[uuid.UUID], today: date) -> set[uuid.UUID]:
    """Items with a ``selection_lost`` event in the last 14 days (same window as the command center)."""
    if not item_ids:
        return set()
    rows = db.execute(text(
        "SELECT DISTINCT entity_id FROM core.event WHERE entity_type = 'line_item' AND action = 'selection_lost' "
        "AND occurred_at >= :since AND entity_id = ANY(:ids)"
    ), {"since": today - timedelta(days=SELECTION_LOST_DAYS), "ids": [str(i) for i in item_ids]}).scalars()
    return {uuid.UUID(r) for r in rows}


def coverage(db: Session, case_id: uuid.UUID, today: date | None = None) -> dict:
    case = get_case(db, case_id)
    today = today or clock.today()
    units = unit_index(db)
    rows = _offer_rows(db, case.id)
    per_item: dict[uuid.UUID, list[tuple[OfferItem, SupplierOffer]]] = defaultdict(list)
    for offer_item, offer in rows:
        if is_valid(offer, today) and offer_item.available:
            per_item[offer_item.line_item_id].append((offer_item, offer))
    items_out, missing = [], []
    case_items = items_service.items_of(db, case_id=case.id)
    lost = selection_lost_ids(db, [i.id for i in case_items], today)
    for item in case_items:
        valid = per_item.get(item.id, [])
        best: dict[str, dict] = {}
        for offer_item, offer in valid:
            key, factor = unit_group(offer_item.unit_code, offer_item.unit_text, units)
            price = normalized_price(offer_item.unit_price, offer_item.price_per_quantity, factor)
            group = f"{offer.currency}|{key}"
            if price is not None and (group not in best or price < best[group]["normalized_price"]):
                best[group] = {"currency": offer.currency, "unit_group": key, "normalized_price": price,
                               "unit_price": offer_item.unit_price, "price_per_quantity": offer_item.price_per_quantity,
                               "unit_code": offer_item.unit_code, "unit_text": offer_item.unit_text,
                               "offer_id": offer.id, "party_id": offer.party_id}
        done = item.status in ("selected", "cancelled") or item.no_coverage_confirmed
        if not done:
            missing.append({"item_id": item.id, "name": item.name, "status": item.status,
                            "valid_offers": len(valid)})
        items_out.append({"item_id": item.id, "position": item.position, "name": item.name, "status": item.status,
                          "no_coverage_confirmed": item.no_coverage_confirmed,
                          "no_coverage_reason": item.no_coverage_reason, "valid_offers": len(valid),
                          "best_prices": sorted(best.values(), key=lambda b: (b["currency"], b["unit_group"])),
                          "selected_offer_item_id": item.selected_offer_item_id,
                          "selection_lost": item.id in lost and item.selected_offer_item_id is None
                          and item.status != "cancelled"})
    return jsonable({"case_id": case.id, "items": items_out,
                     "gate": {"ok": not missing and bool(items_out), "missing": missing}})


def select_offer(db: Session, item_id: uuid.UUID, offer_item_id: uuid.UUID | None, reason: str | None, source: str,
                 actor: str | None = None) -> LineItem:
    """Choose (or clear) the offer for an item. Changing an earlier choice needs a reason."""
    item = items_service.get_item(db, item_id)
    if item.status == "cancelled":
        raise Conflict("item_cancelled", "The item is cancelled")
    reason = (reason or "").strip() or None
    old = item.selected_offer_item_id
    if old == offer_item_id:
        return item
    if old is not None and not reason:
        raise AppError("reason_required", "Changing the selected offer needs a reason", status=422)
    if offer_item_id is not None:
        offer_item = db.get(OfferItem, offer_item_id)
        if offer_item is None or offer_item.line_item_id != item.id:
            raise AppError("offer_not_for_item", "The offer row is for another item", status=422)
        offer = db.get(SupplierOffer, offer_item.offer_id)
        if not is_valid(offer) or not offer_item.available:
            raise Conflict("offer_not_valid", f"The offer is {offer.status} or not available",
                           {"status": offer.status, "valid_until": str(offer.valid_until)})
    item.selected_offer_item_id = offer_item_id
    old_status = item.status
    flush(db, "invalid_item")
    items_service.recompute_item_status(db, item, source, actor, cause="select_offer" if offer_item_id else "unselect_offer")
    events.record(db, "line_item", item.id, "select_offer" if offer_item_id else "unselect_offer", jsonable({
        "old_offer_item_id": old, "new_offer_item_id": offer_item_id, "reason": reason,
        "old_status": old_status, "new_status": item.status}), source, actor=actor)
    return item
