"""Payment milestones (v0.7.0, minimal; Phase 9 builds settlement on these rows).

Money in from the customer (``direction='in'``, on a sales order) and out to suppliers or others (``'out'``, on a PO
or the case). A milestone has a percent of its order's total or an amount with currency; it is ``expected`` until
payment records (partial payments) add up: ``partly`` then ``done``. ``cancelled`` with a reason. A milestone with
payments is never deleted (reverse the payment record instead). The cash position of a case (received, paid, net
tied up per currency) is computed from the records, next to the Phase 6 computed exposure (the plan). The ordering
gate: sending a PO while the customer's prepayment is still expected needs ``confirm_without_prepayment`` with a
reason (409 ``customer_prepayment_missing``).
"""
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.execution.common import ZERO, get, get_purchase_order, get_sales_order, money, reason_required
from app.modules.execution.models import PaymentMilestone, PaymentRecord
from app.modules.parties import service as parties
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot

FIELDS = ("kind", "label", "position", "percent", "amount", "amount_currency", "due_on", "due_event", "method",
          "reference", "receipt_document_id", "note", "party_id")
QUICK_ADD = {
    "prepayment": {"kind": "prepayment", "label_fa": "پیش‌پرداخت ٪", "label_en": "Prepayment %"},
    "balance_on_delivery": {"kind": "on_delivery", "label_fa": "مانده هنگام تحویل", "label_en": "Balance on delivery"},
}


def get_milestone(db: Session, milestone_id: uuid.UUID) -> PaymentMilestone:
    return get(db, PaymentMilestone, milestone_id, "Payment milestone")


def milestones_of(db: Session, *, case_id=None, sales_order_id=None, purchase_order_id=None,
                  direction: str | None = None) -> list[PaymentMilestone]:
    query = select(PaymentMilestone)
    if case_id:
        query = query.where(PaymentMilestone.case_id == case_id)
    if sales_order_id:
        query = query.where(PaymentMilestone.sales_order_id == sales_order_id)
    if purchase_order_id:
        query = query.where(PaymentMilestone.purchase_order_id == purchase_order_id)
    if direction:
        query = query.where(PaymentMilestone.direction == direction)
    return list(db.scalars(query.order_by(PaymentMilestone.position, PaymentMilestone.created_at)))


def records_of(db: Session, milestone_id: uuid.UUID) -> list[PaymentRecord]:
    return list(db.scalars(select(PaymentRecord).where(PaymentRecord.milestone_id == milestone_id)
                           .order_by(PaymentRecord.paid_on, PaymentRecord.created_at)))


def _order(db: Session, ms: PaymentMilestone):
    if ms.sales_order_id:
        return get_sales_order(db, ms.sales_order_id)
    if ms.purchase_order_id:
        return get_purchase_order(db, ms.purchase_order_id)
    return None


def expected_amount(db: Session, ms: PaymentMilestone) -> tuple[Decimal, str]:
    """The amount the milestone stands for: its amount, or its percent of the order total (in the order currency)."""
    if ms.amount is not None:
        return ms.amount, ms.amount_currency
    order = _order(db, ms)
    return money(order.total * ms.percent / Decimal(100)), order.currency


def _derive(db: Session, ms: PaymentMilestone) -> None:
    if ms.status == "cancelled":
        return
    records = records_of(db, ms.id)
    paid = sum((r.amount for r in records), ZERO)
    expected, currency = expected_amount(db, ms)
    ms.actual_amount = money(paid) if records else None
    ms.actual_amount_currency = currency if records else None
    ms.actual_on = records[-1].paid_on if records else None
    if records:
        last = records[-1]
        ms.method, ms.reference = last.method or ms.method, last.reference or ms.reference
        ms.receipt_document_id = last.document_id or ms.receipt_document_id
    ms.status = "done" if records and paid >= expected else "partly" if paid > 0 else "expected"


def _validate(db: Session, ms: PaymentMilestone) -> None:
    if ms.percent is None and ms.amount is None:
        raise AppError("amount_or_percent_required", "Give a percent of the order or an amount", status=422)
    if ms.percent is not None and ms.amount is not None:
        raise AppError("amount_or_percent_only", "Give either a percent or an amount, not both", status=422)
    if ms.percent is not None and _order(db, ms) is None:
        raise AppError("percent_needs_order", "A percent needs a sales order or purchase order", status=422)
    if ms.amount is not None and not ms.amount_currency:
        order = _order(db, ms)
        if order is None:
            raise AppError("currency_required", "An amount needs a currency", status=422)
        ms.amount_currency = order.currency
    if ms.receipt_document_id:
        documents.get(db, ms.receipt_document_id)


def create(db: Session, data: dict, source: str, actor: str | None = None) -> PaymentMilestone:
    so = get_sales_order(db, data["sales_order_id"]) if data.get("sales_order_id") else None
    po = get_purchase_order(db, data["purchase_order_id"]) if data.get("purchase_order_id") else None
    if so and po:
        raise AppError("one_order_only", "A milestone belongs to a sales order or a purchase order", status=422)
    case_id = so.case_id if so else po.case_id if po else data.get("case_id")
    if case_id is None:
        raise AppError("case_required", "A milestone needs a case or an order", status=422)
    sourcing.get_case(db, case_id)
    direction = data.get("direction") or ("in" if so else "out")
    if so and direction != "in" or po and direction != "out":
        raise AppError("direction_mismatch", "Money in belongs to a sales order, money out to a purchase order", status=422)
    party = data.get("party_id") or (so.customer_party_id if so else po.supplier_party_id if po else None)
    if party is None:
        raise AppError("party_required", "Who pays or is paid?", status=422)
    parties.get_party(db, party)
    position = data.get("position")
    if position is None:
        position = (db.scalar(select(func.max(PaymentMilestone.position)).where(PaymentMilestone.case_id == case_id)) or 0) + 1
    ms = PaymentMilestone(case_id=case_id, direction=direction, sales_order_id=so.id if so else None,
                          purchase_order_id=po.id if po else None, status="expected",
                          **{**{k: data.get(k) for k in FIELDS if k not in ("party_id", "position")},
                             "party_id": party, "position": position})
    _validate(db, ms)
    db.add(ms)
    flush(db, "invalid_milestone")
    events.record(db, "payment_milestone", ms.id, "create", jsonable(row_snapshot(ms)), source, actor=actor)
    return ms


def update(db: Session, milestone_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> PaymentMilestone:
    ms = get_milestone(db, milestone_id)
    if ms.status == "cancelled":
        raise Conflict("milestone_cancelled", "The milestone is cancelled")
    if ("percent" in changes or "amount" in changes) and records_of(db, ms.id):
        if changes.get("amount_currency") and changes["amount_currency"] != expected_amount(db, ms)[1]:
            raise AppError("currency_mismatch", "Payments were recorded in another currency", status=422)
    if "percent" in changes and changes["percent"] is not None:
        changes = {**changes, "amount": None, "amount_currency": None}
    if "amount" in changes and changes["amount"] is not None:
        changes = {**changes, "percent": None}
    changed = diff(ms, {k: v for k, v in changes.items() if k in FIELDS})
    _validate(db, ms)
    _derive(db, ms)
    flush(db, "invalid_milestone")
    if changed:
        events.record(db, "payment_milestone", ms.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return ms


def cancel(db: Session, milestone_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> PaymentMilestone:
    ms = get_milestone(db, milestone_id)
    if records_of(db, ms.id):
        raise Conflict("milestone_paid", "Payments were recorded; reverse them first")
    reason = reason_required(reason)
    old = ms.status
    ms.status, ms.cancel_reason = "cancelled", reason
    flush(db, "invalid_milestone")
    events.record(db, "payment_milestone", ms.id, "cancel", {"old_status": old, "reason": reason}, source, actor=actor)
    return ms


def delete(db: Session, milestone_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    ms = get_milestone(db, milestone_id)
    if records_of(db, ms.id):
        raise Conflict("milestone_paid", "A milestone with payments is never deleted; reverse the payments or cancel it")
    snapshot = row_snapshot(ms)
    db.delete(ms)
    flush(db, "in_use")
    events.record(db, "payment_milestone", milestone_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def add_record(db: Session, milestone_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PaymentRecord:
    ms = get_milestone(db, milestone_id)
    if ms.status == "cancelled":
        raise Conflict("milestone_cancelled", "The milestone is cancelled")
    currency = expected_amount(db, ms)[1]
    record_currency = data.get("amount_currency") or currency
    if record_currency != currency:
        raise AppError("currency_mismatch", "Record the payment in the milestone's currency",
                       {"currency": currency}, status=422)
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    row = PaymentRecord(milestone_id=ms.id, amount=data["amount"], amount_currency=record_currency,
                        paid_on=data["paid_on"], **{k: data.get(k) for k in ("method", "reference", "document_id", "note")})
    db.add(row)
    flush(db, "invalid_payment")
    old = ms.status
    _derive(db, ms)
    flush(db, "invalid_milestone")
    events.record(db, "payment_milestone", ms.id, "payment", jsonable({
        "record_id": row.id, "amount": row.amount, "currency": row.amount_currency, "paid_on": row.paid_on,
        "reference": row.reference, "old_status": old, "new_status": ms.status}), source, actor=actor)
    return row


def reverse_record(db: Session, record_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> PaymentMilestone:
    """Remove a payment recorded by mistake (reason required, kept in the event); the status recomputes."""
    row = get(db, PaymentRecord, record_id, "Payment record")
    reason = reason_required(reason)
    ms = get_milestone(db, row.milestone_id)
    snapshot = row_snapshot(row)
    db.delete(row)
    db.flush()
    old = ms.status
    _derive(db, ms)
    flush(db, "invalid_milestone")
    events.record(db, "payment_milestone", ms.id, "payment_reversed", jsonable({
        "record": snapshot, "reason": reason, "old_status": old, "new_status": ms.status}), source, actor=actor)
    return ms


def after_order_total_changed(db: Session, order) -> None:
    """A percent milestone follows its order's total (an amendment): its status re-derives."""
    from app.modules.execution.models import SalesOrder

    rows = (milestones_of(db, sales_order_id=order.id) if isinstance(order, SalesOrder)
            else milestones_of(db, purchase_order_id=order.id))
    for ms in rows:
        if ms.percent is not None:
            _derive(db, ms)
    db.flush()


def cancel_open_of_order(db: Session, order_id: uuid.UUID, reason: str, source: str, actor: str | None) -> None:
    for ms in db.scalars(select(PaymentMilestone).where(
            (PaymentMilestone.sales_order_id == order_id) | (PaymentMilestone.purchase_order_id == order_id))):
        if ms.status == "expected" and not records_of(db, ms.id):
            ms.status, ms.cancel_reason = "cancelled", reason
            db.flush()
            events.record(db, "payment_milestone", ms.id, "cancel", {"old_status": "expected", "reason": reason},
                          source, actor=actor)


def cash_position(db: Session, case_id: uuid.UUID) -> dict:
    """Actual so far, per currency: received from the customer, paid to suppliers and others, and the cash tied up
    now (paid minus received). The plan is the Phase 6 computed exposure of the current cost sheet."""
    from app.modules.costing import service as costing

    rows = db.execute(select(PaymentMilestone.direction, PaymentRecord.amount_currency, func.sum(PaymentRecord.amount))
                      .join(PaymentRecord, PaymentRecord.milestone_id == PaymentMilestone.id)
                      .where(PaymentMilestone.case_id == case_id)
                      .group_by(PaymentMilestone.direction, PaymentRecord.amount_currency)).all()
    per: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"received": ZERO, "paid": ZERO})
    for direction, currency, total in rows:
        per[currency]["received" if direction == "in" else "paid"] += total
    actual = {cur: {"received": money(v["received"]), "paid": money(v["paid"]),
                    "net_tied_up": money(v["paid"] - v["received"])} for cur, v in sorted(per.items())}
    expected = defaultdict(lambda: {"in": ZERO, "out": ZERO})
    for ms in milestones_of(db, case_id=case_id):
        if ms.status in ("expected", "partly"):
            amount, currency = expected_amount(db, ms)
            expected[currency][ms.direction] += amount - (ms.actual_amount or ZERO)
    current = costing.case_summary(db, case_id)["current"]
    plan = None if not current or current.get("error") else {"exposure": current["exposure"], "currency": current["currency"]}
    return jsonable({"actual": actual, "outstanding": {cur: {"in": money(v["in"]), "out": money(v["out"])}
                                                       for cur, v in sorted(expected.items())},
                     "plan": plan})


def prepayment_missing(db: Session, sales_order_id: uuid.UUID | None) -> list[PaymentMilestone]:
    """The customer's prepayment milestones of the order not fully received (``expected`` or only ``partly``)."""
    if sales_order_id is None:
        return []
    return [ms for ms in milestones_of(db, sales_order_id=sales_order_id, direction="in")
            if ms.kind == "prepayment" and ms.status in ("expected", "partly")]


def check_ordering_gate(db: Session, sales_order_id: uuid.UUID | None, confirm: bool, reason: str | None) -> str | None:
    """Ordering before payment needs your explicit approval line (the Phase 5 rule): 409 unless confirmed with a reason.
    The gate passes only when every prepayment milestone of the order is ``done`` (v0.8.0: a partly received one does
    not open it). Returns the reason used (to store and record), None when nothing was missing."""
    missing = prepayment_missing(db, sales_order_id)
    if not missing:
        return None
    text = (reason or "").strip()
    if not confirm or not text:
        details = []
        for ms in missing:
            expected, currency = expected_amount(db, ms)
            details.append({"id": str(ms.id), "status": ms.status, "received": str(ms.actual_amount or ZERO),
                            "expected": str(expected), "currency": currency})
        raise Conflict("customer_prepayment_missing",
                       "The customer's prepayment has not been fully received. Ordering before payment needs your "
                       "explicit approval line.", {"milestones": [d["id"] for d in details], "prepayments": details})
    return text


def milestone_out(db: Session, ms: PaymentMilestone) -> dict:
    expected, currency = expected_amount(db, ms)
    party = parties.get_party(db, ms.party_id)
    return jsonable({**row_snapshot(ms), "expected_amount": expected, "expected_currency": currency,
                     "party": {"id": party.id, "name_fa": party.name_fa, "name_en": party.name_en},
                     "records": [row_snapshot(r) for r in records_of(db, ms.id)]})
