"""The execution view of a case: its sales orders, the «Create sales order» prompt, the cash position, and (from
later milestones) purchase orders, the process checklist, shipments, inspections, receipts, claims and deliveries."""
import uuid

from sqlalchemy.orm import Session

from app.modules.execution import milestones, sales_orders
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing.common import jsonable

# later parts add their own sections: name -> fn(db, case_id) -> data
_sections: dict = {}


def register_section(name: str, fn) -> None:
    _sections[name] = fn


def case_execution(db: Session, case_id: uuid.UUID) -> dict:
    sourcing.get_case(db, case_id)
    orders = sales_orders.orders_of(db, case_id)
    out = {"sales_orders": [sales_orders.order_out(db, o) for o in orders],
           "candidates": sales_orders.candidates(db, case_id),
           "cash": milestones.cash_position(db, case_id),
           "milestones_out": [milestones.milestone_out(db, m) for m in milestones.milestones_of(db, case_id=case_id,
                                                                                               direction="out")]}
    from app.modules.execution import process, purchase_orders

    out["purchase_orders"] = [purchase_orders.po_out(db, po) for po in purchase_orders.orders_of(db, case_id)]
    out["processes"] = [process.process_out(db, p) for p in process.processes_of(db, case_id)]
    from app.modules.execution import claims, deliveries, logistics

    out["shipments"] = [logistics.shipment_out(db, s) for s in logistics.shipments_of(db, case_id)]
    out["inspections"] = [logistics.inspection_out(db, i) for i in logistics.inspections_of(db, case_id)]
    out["receipts"] = [logistics.receipt_out(db, r) for r in logistics.receipts_of(db, case_id=case_id)]
    out["claims"] = [claims.claim_out(db, c) for c in claims.claims_of(db, case_id=case_id)]
    out["deliveries"] = [deliveries.delivery_out(db, d) for o in orders for d in deliveries.deliveries_of(db, o.id)]
    out["warnings"] = logistics.delay_warnings(db, case_id)
    out["header"] = header(db, case_id, orders, out)
    for name, fn in _sections.items():
        out[name] = fn(db, case_id)
    return jsonable(out)


def header(db: Session, case_id: uuid.UUID, orders, out: dict) -> dict | None:
    """Case header facts: order status, delivery progress («۲ از ۳ قلم»), the next due step or date, the cash so far."""
    live = [o for o in orders if o.status != "cancelled"]
    if not live and not out.get("processes"):
        return None
    order = live[-1] if live else None
    progress = sales_orders.delivery_progress(db, order) if order else None
    nexts = [p["progress"]["next"] for p in out.get("processes", []) if p["progress"]["next"]]
    nexts = sorted(nexts, key=lambda n: (n["due_on"] is None, n["due_on"] or ""))
    candidates = []
    if nexts:
        candidates.append({"kind": "step", **nexts[0]})
    if order and order.delivery_due_on and order.status in ("confirmed", "in_progress"):
        candidates.append({"kind": "delivery_due", "due_on": order.delivery_due_on.isoformat(), "number": order.number})
    candidates = sorted(candidates, key=lambda c: (c.get("due_on") is None, str(c.get("due_on") or "")))
    from app.modules.execution.deliveries import warranty_ends_on

    return jsonable({"order": None if order is None else {"id": order.id, "number": order.number, "status": order.status,
                                                          "warranty_ends_on": warranty_ends_on(db, order)},
                     "items_delivered": progress["items_delivered"] if progress else 0,
                     "items_total": progress["items_total"] if progress else 0,
                     "next": candidates[0] if candidates else None, "cash": out.get("cash", {}).get("actual", {}),
                     "warnings": len(out.get("warnings", []))})
