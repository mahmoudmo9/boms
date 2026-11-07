"""Read-only closed deals (v0.8.0): any insert, update or delete of an execution or finance row of a closed case is
refused with 409 ``case_closed`` (a ``before_flush`` check on every session), except while finance itself closes,
reopens or cascade-deletes the case (``db.info["finance_closing"]``). Notes, ratings, documents, tasks and the case's
own fields stay writable."""
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict

PARENTS = (("sales_order_id", "SalesOrder"), ("purchase_order_id", "PurchaseOrder"), ("sales_invoice_id", "SalesInvoice"),
           ("purchase_invoice_id", "PurchaseInvoice"), ("shipment_id", "Shipment"), ("delivery_id", "Delivery"),
           ("receipt_id", "Receipt"), ("process_id", "Process"), ("milestone_id", "PaymentMilestone"),
           ("payment_record_id", "PaymentRecord"))
_guarded: tuple = ()
_models: dict = {}


def _load() -> None:
    global _guarded
    if _guarded:
        return
    from app.modules.execution import models as ex
    from app.modules.finance import models as fi

    skip = {"ProcessTemplate", "ProcessTemplateStep", "ExecutionFollowup", "SalesOrderSequence", "PurchaseOrderSequence",
            "InvoiceSequence", "DealResult", "PartyRating"}
    found = []
    for module in (ex, fi):
        for name in dir(module):
            cls = getattr(module, name)
            if isinstance(cls, type) and hasattr(cls, "__tablename__") and name not in skip and cls.__module__ == module.__name__:
                found.append(cls)
                _models[name] = cls
    _guarded = tuple(found)


def _case_of(session: Session, obj, depth: int = 0):
    case_id = getattr(obj, "case_id", None)
    if case_id is not None or depth > 3:
        return case_id
    for attr, model in PARENTS:
        value = getattr(obj, attr, None)
        if value is not None and model in _models:
            parent = session.get(_models[model], value)
            if parent is not None:
                return _case_of(session, parent, depth + 1)
    return None


def before_flush(session: Session, _context, _instances) -> None:
    if session.info.get("finance_closing"):
        return
    _load()
    objects = [o for o in list(session.new) + list(session.dirty) + list(session.deleted) if isinstance(o, _guarded)]
    if not objects:
        return
    from app.modules.sourcing.models import Case

    with session.no_autoflush:
        case_ids = {cid for cid in (_case_of(session, o) for o in objects) if cid is not None}
        if not case_ids:
            return
        closed = session.scalars(select(Case.id).where(Case.id.in_(case_ids), Case.status == "closed")).all()
    if closed:
        from app.modules.finance.models import DealResult

        with session.no_autoflush:
            frozen = session.scalars(select(DealResult.case_id).where(DealResult.case_id.in_(closed))).all()
        if frozen:
            raise Conflict("case_closed", "The deal is closed; reopen it (with a reason) to change it",
                           {"case_id": str(frozen[0])})


def install() -> None:
    if not event.contains(Session, "before_flush", before_flush):
        event.listen(Session, "before_flush", before_flush)
