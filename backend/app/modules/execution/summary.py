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
    for name, fn in _sections.items():
        out[name] = fn(db, case_id)
    return jsonable(out)
