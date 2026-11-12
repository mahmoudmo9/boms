"""Shipments, inspections and goods received (v0.7.0).

A case has any number of shipments (partial deliveries), inbound (supplier -> us / the customer, on a PO) or outbound
(us -> customer, on a sales order), tracked by hand: carrier, transport document, containers, ETD / ETA / ATD / ATA,
events (a changed ETA or ETD writes one automatically) and documents by kind. Shipped quantities of a PO item never
exceed its ordered quantity (422). Delay warnings: ETA passed without ATA; ETA later than the first ETA by more than
``execution.delay_warning_days``; a PO ready date passed while the PO is not ready. Inspections record a result; a
failed one offers a prefilled claim. Receipts of goods from suppliers update the PO items' received quantities (the PO
becomes ``received`` when everything arrived); damaged or short lines offer a claim. A PO delivered directly to the
customer (``direct_to_customer``) needs no receipt.
"""
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.execution.common import ZERO, get, get_purchase_order, get_sales_order, today
from app.modules.execution.models import (Inspection, PurchaseOrder, PurchaseOrderItem, Receipt, ReceiptItem, Shipment,
                                          ShipmentDocument, ShipmentEvent, ShipmentItem, SalesOrderItem)
from app.modules.parties import clock
from app.modules.parties import service as parties
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings

SHIPMENT_FIELDS = ("mode", "carrier_party_id", "forwarder_party_id", "transport_doc_kind", "transport_doc_no", "containers",
                   "vessel_or_flight", "origin", "destination", "incoterm", "etd", "eta", "atd", "ata", "status",
                   "insurer_party_id", "policy_no", "insured_amount", "insured_amount_currency", "notes",
                   "origin_location_id", "destination_location_id")
EVENT_SUGGESTIONS = ("booked", "loaded", "departed", "transshipment", "arrived", "customs_entry", "released", "delivered",
                     "delay", "other")
STATUS_EVENT = {"booked": "booked", "in_transit": "departed", "arrived": "arrived", "at_customs": "customs_entry",
                "cleared": "released", "delivered": "delivered"}
INSPECTION_FIELDS = ("kind", "inspector_party_id", "planned_on", "done_on", "result", "report_document_id", "items", "notes",
                     "shipment_id", "purchase_order_id")


def _tehran_noon(day: date) -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.combine(day, time(12, 0), ZoneInfo("Asia/Tehran"))


# ---- shipments ---------------------------------------------------------------------------------------------------------

def get_shipment(db: Session, shipment_id: uuid.UUID) -> Shipment:
    return get(db, Shipment, shipment_id, "Shipment")


def shipments_of(db: Session, case_id: uuid.UUID) -> list[Shipment]:
    return list(db.scalars(select(Shipment).where(Shipment.case_id == case_id).order_by(Shipment.created_at)))


def shipment_items(db: Session, shipment_id: uuid.UUID) -> list[ShipmentItem]:
    return list(db.scalars(select(ShipmentItem).where(ShipmentItem.shipment_id == shipment_id).order_by(ShipmentItem.created_at)))


def shipment_events(db: Session, shipment_id: uuid.UUID) -> list[ShipmentEvent]:
    return list(db.scalars(select(ShipmentEvent).where(ShipmentEvent.shipment_id == shipment_id).order_by(ShipmentEvent.at)))


def shipment_documents(db: Session, shipment_id: uuid.UUID) -> list[ShipmentDocument]:
    return list(db.scalars(select(ShipmentDocument).where(ShipmentDocument.shipment_id == shipment_id)
                           .order_by(ShipmentDocument.kind, ShipmentDocument.created_at)))


def _check_parties(db: Session, data: dict) -> None:
    for key in ("carrier_party_id", "forwarder_party_id", "insurer_party_id", "inspector_party_id"):
        if data.get(key):
            parties.get_party(db, data[key])


def _shipped(db: Session, po_item_id: uuid.UUID, exclude: uuid.UUID | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(ShipmentItem.quantity), 0)).join(Shipment, Shipment.id == ShipmentItem.shipment_id) \
        .where(ShipmentItem.purchase_order_item_id == po_item_id, Shipment.status != "cancelled")
    if exclude is not None:
        query = query.where(ShipmentItem.id != exclude)
    return Decimal(db.scalar(query))


def _set_items(db: Session, shipment: Shipment, rows: list[dict]) -> None:
    for row in shipment_items(db, shipment.id):
        db.delete(row)
    db.flush()
    for data in rows:
        qty = data["quantity"]
        po_item_id, so_item_id = data.get("purchase_order_item_id"), data.get("sales_order_item_id")
        if po_item_id:
            po_item = get(db, PurchaseOrderItem, po_item_id, "Purchase order item")
            po = get_purchase_order(db, po_item.purchase_order_id)
            if po.case_id != shipment.case_id:
                raise AppError("item_not_of_case", "The PO item belongs to another case", status=422)
            already = _shipped(db, po_item.id)
            if already + qty > po_item.quantity:
                raise AppError("over_shipped", "More than the PO quantity would be shipped",
                               {"purchase_order_item_id": str(po_item.id), "ordered": str(po_item.quantity),
                                "already_shipped": str(already), "quantity": str(qty)}, status=422)
            so_item_id = so_item_id or po_item.sales_order_item_id
        elif so_item_id:
            so_item = get(db, SalesOrderItem, so_item_id, "Sales order item")
            if get_sales_order(db, so_item.sales_order_id).case_id != shipment.case_id:
                raise AppError("item_not_of_case", "The order item belongs to another case", status=422)
        else:
            raise AppError("item_link_required", "A shipped line names its PO item or sales order item", status=422)
        db.add(ShipmentItem(shipment_id=shipment.id, purchase_order_item_id=po_item_id, sales_order_item_id=so_item_id,
                            quantity=qty))
    flush(db, "invalid_shipment_item")


def _add_event(db: Session, shipment: Shipment, kind: str, note: str | None, at: datetime | None = None,
               document_id=None) -> ShipmentEvent:
    row = ShipmentEvent(shipment_id=shipment.id, at=at or clock.now(), kind=kind, note=note, document_id=document_id)
    db.add(row)
    db.flush()
    return row


def create_shipment(db: Session, data: dict, source: str, actor: str | None = None) -> Shipment:
    po = get_purchase_order(db, data["purchase_order_id"]) if data.get("purchase_order_id") else None
    so = get_sales_order(db, data["sales_order_id"]) if data.get("sales_order_id") else None
    case_id = po.case_id if po else so.case_id if so else data.get("case_id")
    if case_id is None:
        raise AppError("case_required", "A shipment belongs to a case, a PO or a sales order", status=422)
    sourcing.get_case(db, case_id)
    _check_parties(db, data)
    direction = data.get("direction") or ("inbound" if po else "outbound")
    shipment = Shipment(case_id=case_id, direction=direction, purchase_order_id=po.id if po else None,
                        sales_order_id=so.id if so else (po.sales_order_id if po else None),
                        **{k: data[k] for k in SHIPMENT_FIELDS if data.get(k) is not None})
    shipment.incoterm = shipment.incoterm or (po.incoterm if po else None)
    shipment.first_eta = shipment.eta
    db.add(shipment)
    flush(db, "invalid_shipment")
    _set_items(db, shipment, data.get("items") or [])
    _check_locations(db, shipment)
    if data.get("container_units") is not None:
        _set_containers(db, shipment, data["container_units"])
    events.record(db, "shipment", shipment.id, "create", jsonable({**row_snapshot(shipment), "items": data.get("items") or []}),
                  source, actor=actor)
    return shipment


def update_shipment(db: Session, shipment_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Shipment:
    """Changing ETA or ETD writes a shipment event with old -> new; a status change writes its event too."""
    shipment = get_shipment(db, shipment_id)
    _check_parties(db, changes)
    items = changes.pop("items", None)
    units = changes.pop("container_units", None)
    old = {k: getattr(shipment, k) for k in ("eta", "etd", "status")}
    changed = diff(shipment, {k: v for k, v in changes.items() if k in SHIPMENT_FIELDS})
    if shipment.first_eta is None and shipment.eta is not None:
        shipment.first_eta = shipment.eta
    flush(db, "invalid_shipment")
    for field in ("etd", "eta"):
        new = getattr(shipment, field)
        if field in changed and old[field] is not None:
            later = field == "eta" and new is not None and new > old[field]
            _add_event(db, shipment, "delay" if later else f"{field}_change",
                       f"{field.upper()}: {old[field].isoformat()} → {new.isoformat() if new else '—'}")
    if "status" in changed and shipment.status in STATUS_EVENT:
        _add_event(db, shipment, STATUS_EVENT[shipment.status], None)
    if items is not None:
        _set_items(db, shipment, items)
        changed["items"] = len(items)
    _check_locations(db, shipment)
    if units is not None:
        _set_containers(db, shipment, units)
        changed["container_units"] = [u["number"] for u in units]
    if changed:
        events.record(db, "shipment", shipment.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return shipment


def add_event(db: Session, shipment_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> ShipmentEvent:
    shipment = get_shipment(db, shipment_id)
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    kind = (data.get("kind") or "").strip()
    if not kind:
        raise AppError("kind_required", "What happened?", status=422)
    row = _add_event(db, shipment, kind, data.get("note"), data.get("at"), data.get("document_id"))
    if data.get("location_id"):
        from app.modules.reference import service as reference

        row.location_id = reference.get_location(db, data["location_id"]).id
    flush(db, "invalid_shipment_event")
    events.record(db, "shipment", shipment.id, "event", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def add_document(db: Session, shipment_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> ShipmentDocument:
    shipment = get_shipment(db, shipment_id)
    documents.get(db, data["document_id"])
    row = ShipmentDocument(shipment_id=shipment.id, **{k: data.get(k) for k in ("kind", "document_id", "number", "issued_on")})
    db.add(row)
    flush(db, "invalid_shipment_document")
    if data["kind"] in ("bl", "awb", "cmr") and data.get("number") and not shipment.transport_doc_no:
        shipment.transport_doc_kind = data["kind"]
        shipment.transport_doc_no = data["number"]
        flush(db, "invalid_shipment")
    events.record(db, "shipment", shipment.id, "document_add", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def remove_document(db: Session, row_id: uuid.UUID, source: str, actor: str | None = None) -> uuid.UUID:
    row = get(db, ShipmentDocument, row_id, "Shipment document")
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "shipment", row.shipment_id, "document_remove", jsonable(snapshot), source, actor=actor)
    return row.shipment_id


def delete_shipment(db: Session, shipment_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Only a shipment nothing refers to (no receipt, delivery, inspection or claim); otherwise cancel it."""
    from app.modules.execution.models import Claim, Delivery

    shipment = get_shipment(db, shipment_id)
    for model, name in ((Receipt, "receipts"), (Delivery, "deliveries"), (Inspection, "inspections"), (Claim, "claims")):
        count = db.scalar(select(func.count()).select_from(model).where(model.shipment_id == shipment.id))
        if count:
            raise Conflict("in_use", "Other records refer to this shipment; cancel it instead", {name: count})
    snapshot = {"shipment": row_snapshot(shipment), "items": [row_snapshot(i) for i in shipment_items(db, shipment.id)]}
    for model in (ShipmentItem, ShipmentEvent, ShipmentDocument):
        for row in db.scalars(select(model).where(model.shipment_id == shipment.id)):
            db.delete(row)
    db.flush()
    db.delete(shipment)
    flush(db, "in_use")
    events.record(db, "shipment", shipment_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def delay_warnings(db: Session, case_id: uuid.UUID | None = None, on: date | None = None) -> list[dict]:
    """The three warnings, for one case or all: ETA passed without ATA; ETA moved later than the first ETA by more
    than ``execution.delay_warning_days``; a PO ready date passed while the PO is not ready."""
    on = on or today()
    limit = settings.get(db, "execution.delay_warning_days")
    out = []
    query = select(Shipment).where(Shipment.status.notin_(("delivered", "cancelled")))
    if case_id:
        query = query.where(Shipment.case_id == case_id)
    for s in db.scalars(query):
        if s.eta and s.ata is None and s.eta < on:
            out.append({"kind": "eta_passed", "case_id": s.case_id, "shipment_id": s.id, "eta": s.eta,
                        "days": (on - s.eta).days, "transport_doc_no": s.transport_doc_no})
        if s.eta and s.first_eta and (s.eta - s.first_eta).days > limit:
            out.append({"kind": "eta_moved", "case_id": s.case_id, "shipment_id": s.id, "eta": s.eta,
                        "first_eta": s.first_eta, "days": (s.eta - s.first_eta).days, "transport_doc_no": s.transport_doc_no})
    query = select(PurchaseOrder).where(PurchaseOrder.status.in_(("sent", "confirmed", "in_production")),
                                        PurchaseOrder.ready_due_on < on)
    if case_id:
        query = query.where(PurchaseOrder.case_id == case_id)
    for po in db.scalars(query):
        out.append({"kind": "ready_passed", "case_id": po.case_id, "purchase_order_id": po.id, "number": po.number,
                    "ready_due_on": po.ready_due_on, "days": (on - po.ready_due_on).days})
    return jsonable(out)


def _check_locations(db: Session, shipment: Shipment) -> None:
    from app.modules.reference import service as reference

    for loc_id in (shipment.origin_location_id, shipment.destination_location_id):
        if loc_id:
            reference.get_location(db, loc_id)


def _set_containers(db: Session, shipment: Shipment, units: list[dict]) -> None:
    """v0.9.0: container numbers (ISO 6346, check digit validated) with their size/type; the plain ``containers``
    list follows them so older screens keep working."""
    from app.modules.execution.models import ShipmentContainer
    from app.modules.reference import service as reference

    numbers = []
    for row in db.scalars(select(ShipmentContainer).where(ShipmentContainer.shipment_id == shipment.id)):
        db.delete(row)
    db.flush()
    for unit in units:
        number = reference.normalize_container(unit["number"])
        if number in numbers:
            raise AppError("duplicate_container", "A container number is listed twice", {"number": number}, status=422)
        numbers.append(number)
        db.add(ShipmentContainer(shipment_id=shipment.id, number=number, container_type=unit.get("container_type"),
                                 seal_no=unit.get("seal_no")))
    flush(db, "invalid_container")
    shipment.containers = numbers
    flush(db, "invalid_shipment")


def shipment_containers(db: Session, shipment_id) -> list:
    from app.modules.execution.models import ShipmentContainer

    return list(db.scalars(select(ShipmentContainer).where(ShipmentContainer.shipment_id == shipment_id)
                           .order_by(ShipmentContainer.created_at, ShipmentContainer.number)))


def route_out(db: Session, s: Shipment) -> dict | None:
    """v0.9.0 display rule: «شانگهای SHA ← بوشهر BUZ» / "Shanghai SHA → Bushehr BUZ"; air by IATA code."""
    if not (s.origin_location_id or s.destination_location_id):
        return None
    from app.modules.reference import service as reference
    from app.modules.reference.models import Location

    o = db.get(Location, s.origin_location_id) if s.origin_location_id else None
    d = db.get(Location, s.destination_location_id) if s.destination_location_id else None
    return {"fa": reference.route_label(db, o, d, s.mode, "fa"), "en": reference.route_label(db, o, d, s.mode, "en"),
            "origin": o and {"id": o.id, "unlocode": o.unlocode, "name": o.name, "name_fa": o.name_fa},
            "destination": d and {"id": d.id, "unlocode": d.unlocode, "name": d.name, "name_fa": d.name_fa},
            "stops": route_stops(db, s, o, d)}


def route_stops(db: Session, s: Shipment, origin, destination) -> list[dict]:
    """v0.10.0: the route as recorded, for the route diagram: the origin, every shipment event recorded at a place (a
    transshipment port), the destination; each with its UN/LOCODE (IATA code for air) and the time of its latest
    event. ``last`` marks where the most recent event at a place happened. Read only; nothing is inferred."""
    from app.modules.reference import service as reference
    from app.modules.reference.models import Location

    def stop(loc, role):
        code = (reference.airport_code(db, loc) if s.mode == "air" else None) or loc.unlocode
        return {"role": role, "location_id": str(loc.id), "code": code, "name": loc.name, "name_fa": loc.name_fa, "at": None, "event": None}

    stops: list[dict] = [stop(origin, "origin")] if origin else []
    events = [e for e in shipment_events(db, s.id) if e.location_id]
    for e in sorted(events, key=lambda e: e.at):
        loc = db.get(Location, e.location_id)
        if loc is None:
            continue
        same = next((x for x in stops if x["location_id"] == str(loc.id)), None)
        if same is None:
            same = stop(loc, "destination" if destination is not None and loc.id == destination.id else "via")
            stops.append(same)
        same["at"], same["event"] = e.at.isoformat(), e.kind
    if destination is not None and not any(x["location_id"] == str(destination.id) for x in stops):
        stops.append(stop(destination, "destination"))
    # the origin first, the destination last, the rest in the order they were reached
    stops.sort(key=lambda x: (x["role"] == "destination", x["role"] != "origin"))
    if s.atd and stops and stops[0]["role"] == "origin" and stops[0]["at"] is None:
        stops[0]["at"], stops[0]["event"] = s.atd.isoformat() if hasattr(s.atd, "isoformat") else str(s.atd), "departed"
    if s.ata and stops and stops[-1]["role"] == "destination" and stops[-1]["at"] is None:
        stops[-1]["at"], stops[-1]["event"] = s.ata.isoformat() if hasattr(s.ata, "isoformat") else str(s.ata), "arrived"
    reached = [i for i, x in enumerate(stops) if x["at"]]
    for i, x in enumerate(stops):
        x["state"] = "last" if reached and i == reached[-1] else "done" if reached and i < reached[-1] else "upcoming"
    return stops


def shipment_out(db: Session, s: Shipment) -> dict:
    return jsonable({**row_snapshot(s), "items": [row_snapshot(i) for i in shipment_items(db, s.id)],
                     "events": [row_snapshot(e) for e in shipment_events(db, s.id)],
                     "documents": [row_snapshot(d) for d in shipment_documents(db, s.id)],
                     "container_units": [row_snapshot(c) for c in shipment_containers(db, s.id)], "route": route_out(db, s)})


# ---- inspections ------------------------------------------------------------------------------------------------------

def inspections_of(db: Session, case_id: uuid.UUID) -> list[Inspection]:
    return list(db.scalars(select(Inspection).where(Inspection.case_id == case_id).order_by(Inspection.created_at)))


def claim_suggestion(db: Session, *, inspection: Inspection | None = None, receipt: Receipt | None = None) -> dict | None:
    """The prefilled claim a failed inspection or a damaged / short receipt offers ("Open claim")."""
    if inspection is not None:
        if inspection.result != "fail":
            return None
        po = get_purchase_order(db, inspection.purchase_order_id) if inspection.purchase_order_id else None
        if po is None and inspection.shipment_id:
            sh = get_shipment(db, inspection.shipment_id)
            po = get_purchase_order(db, sh.purchase_order_id) if sh.purchase_order_id else None
        return jsonable({"case_id": inspection.case_id, "direction": "against_supplier", "kind": "defect",
                         "counterparty_id": po.supplier_party_id if po else None, "purchase_order_id": po.id if po else None,
                         "shipment_id": inspection.shipment_id, "inspection_id": inspection.id,
                         "items": [i for i in (inspection.items or []) if i.get("result") == "fail"] or inspection.items or [],
                         "opened_on": today(), "notes": inspection.notes})
    if receipt is not None:
        bad = [r for r in receipt_items(db, receipt.id) if r.condition in ("damaged", "short")]
        if not bad:
            return None
        po = get_purchase_order(db, receipt.purchase_order_id)
        kind = "damage" if any(r.condition == "damaged" for r in bad) else "shortage"
        return jsonable({"case_id": po.case_id, "direction": "against_supplier", "kind": kind,
                         "counterparty_id": po.supplier_party_id, "purchase_order_id": po.id, "shipment_id": receipt.shipment_id,
                         "receipt_id": receipt.id, "opened_on": today(),
                         "items": [{"purchase_order_item_id": str(r.purchase_order_item_id), "quantity": str(r.quantity),
                                    "condition": r.condition, "note": r.note} for r in bad]})
    return None


def create_inspection(db: Session, data: dict, source: str, actor: str | None = None) -> Inspection:
    shipment = get_shipment(db, data["shipment_id"]) if data.get("shipment_id") else None
    po = get_purchase_order(db, data["purchase_order_id"]) if data.get("purchase_order_id") else None
    case_id = shipment.case_id if shipment else po.case_id if po else data.get("case_id")
    if case_id is None:
        raise AppError("case_required", "An inspection belongs to a case, a shipment or a PO", status=422)
    sourcing.get_case(db, case_id)
    _check_parties(db, data)
    if data.get("report_document_id"):
        documents.get(db, data["report_document_id"])
    row = Inspection(case_id=case_id, **{k: data[k] for k in INSPECTION_FIELDS if data.get(k) is not None})
    db.add(row)
    flush(db, "invalid_inspection")
    events.record(db, "inspection", row.id, "create", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def update_inspection(db: Session, inspection_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Inspection:
    row = get(db, Inspection, inspection_id, "Inspection")
    _check_parties(db, changes)
    if changes.get("report_document_id"):
        documents.get(db, changes["report_document_id"])
    old_result = row.result
    changed = diff(row, {k: v for k, v in changes.items() if k in INSPECTION_FIELDS})
    if "result" in changed and row.result != "pending" and row.done_on is None:
        row.done_on = today()
    flush(db, "invalid_inspection")
    if changed:
        events.record(db, "inspection", row.id, "result" if "result" in changed else "update",
                      jsonable({"changes": changed, "old_result": old_result}), source, actor=actor)
    return row


def delete_inspection(db: Session, inspection_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get(db, Inspection, inspection_id, "Inspection")
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "inspection", inspection_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def inspection_out(db: Session, row: Inspection) -> dict:
    return jsonable({**row_snapshot(row), "claim_suggestion": claim_suggestion(db, inspection=row)})


# ---- receipts (goods received from suppliers) --------------------------------------------------------------------------------

def receipts_of(db: Session, *, case_id=None, purchase_order_id=None) -> list[Receipt]:
    query = select(Receipt)
    if purchase_order_id:
        query = query.where(Receipt.purchase_order_id == purchase_order_id)
    if case_id:
        query = query.join(PurchaseOrder, PurchaseOrder.id == Receipt.purchase_order_id).where(PurchaseOrder.case_id == case_id)
    return list(db.scalars(query.order_by(Receipt.received_on, Receipt.created_at)))


def receipt_items(db: Session, receipt_id: uuid.UUID) -> list[ReceiptItem]:
    return list(db.scalars(select(ReceiptItem).where(ReceiptItem.receipt_id == receipt_id).order_by(ReceiptItem.created_at)))


def _recompute_received(db: Session, po: PurchaseOrder, source: str, actor: str | None) -> None:
    """Received quantity per PO item (conditions ok and damaged count as received; short lines record what came);
    the PO becomes ``received`` when every item is fully received, and goes back when a receipt is removed."""
    totals: dict = defaultdict(lambda: ZERO)
    for r in receipts_of(db, purchase_order_id=po.id):
        for line in receipt_items(db, r.id):
            totals[line.purchase_order_item_id] += line.quantity
    rows = items_of_po(db, po.id)
    for row in rows:
        row.received_quantity = totals.get(row.id, ZERO)
    db.flush()
    complete = bool(rows) and all(r.received_quantity >= r.quantity for r in rows)
    old = po.status
    if complete and po.status in ("sent", "confirmed", "in_production", "ready", "shipped"):
        po.status = "received"
    elif not complete and po.status == "received":
        po.status = "shipped"
    if po.status != old:
        flush(db, "invalid_purchase_order")
        events.record(db, "purchase_order", po.id, "status", {"old_status": old, "new_status": po.status,
                                                               "cause": "receipts"}, source, actor=actor)


def items_of_po(db: Session, po_id: uuid.UUID) -> list[PurchaseOrderItem]:
    from app.modules.execution.purchase_orders import items_of

    return items_of(db, po_id)


def create_receipt(db: Session, data: dict, source: str, actor: str | None = None) -> Receipt:
    po = get_purchase_order(db, data["purchase_order_id"])
    if po.direct_to_customer:
        raise Conflict("direct_to_customer", "This PO is delivered directly to the customer; record the delivery instead")
    if po.status in ("draft", "approved", "cancelled", "superseded"):
        raise Conflict("purchase_order_not_sent", f"The purchase order is {po.status}", {"status": po.status})
    if data.get("shipment_id"):
        get_shipment(db, data["shipment_id"])
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    lines = data.get("items") or []
    if not lines:
        raise AppError("no_items", "A receipt lists what arrived", status=422)
    by_id = {r.id: r for r in items_of_po(db, po.id)}
    receipt = Receipt(purchase_order_id=po.id, shipment_id=data.get("shipment_id"), received_on=data["received_on"],
                      document_id=data.get("document_id"), note=data.get("note"))
    db.add(receipt)
    flush(db, "invalid_receipt")
    for line in lines:
        item = by_id.get(line["purchase_order_item_id"])
        if item is None:
            raise AppError("item_not_of_order", "The item belongs to another PO",
                           {"purchase_order_item_id": str(line["purchase_order_item_id"])}, status=422)
        if item.received_quantity + line["quantity"] > item.quantity:
            raise AppError("over_received", "More than the ordered quantity would be received",
                           {"purchase_order_item_id": str(item.id), "ordered": str(item.quantity),
                            "received": str(item.received_quantity)}, status=422)
        db.add(ReceiptItem(receipt_id=receipt.id, purchase_order_item_id=item.id, quantity=line["quantity"],
                           condition=line.get("condition") or "ok", note=line.get("note")))
        item.received_quantity += line["quantity"]
    flush(db, "invalid_receipt_item")
    _recompute_received(db, po, source, actor)
    events.record(db, "receipt", receipt.id, "create", jsonable({
        "purchase_order_id": po.id, "received_on": receipt.received_on,
        "items": [{"purchase_order_item_id": line["purchase_order_item_id"], "quantity": line["quantity"],
                   "condition": line.get("condition") or "ok"} for line in lines]}), source, actor=actor)
    return receipt


def delete_receipt(db: Session, receipt_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> None:
    from app.modules.execution.common import reason_required

    receipt = get(db, Receipt, receipt_id, "Receipt")
    reason = reason_required(reason)
    po = get_purchase_order(db, receipt.purchase_order_id)
    snapshot = {"receipt": row_snapshot(receipt), "items": [row_snapshot(i) for i in receipt_items(db, receipt.id)]}
    for line in receipt_items(db, receipt.id):
        db.delete(line)
    db.flush()
    db.delete(receipt)
    flush(db, "in_use")
    _recompute_received(db, po, source, actor)
    events.record(db, "receipt", receipt_id, "delete", jsonable({"deleted": snapshot, "reason": reason}), source, actor=actor)


def receipt_out(db: Session, r: Receipt) -> dict:
    return jsonable({**row_snapshot(r), "items": [row_snapshot(i) for i in receipt_items(db, r.id)],
                     "claim_suggestion": claim_suggestion(db, receipt=r)})


__all__ = ["EVENT_SUGGESTIONS", "timedelta"]
