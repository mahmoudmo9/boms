"""Sales orders (v0.7.0): what the customer ordered, with the signed contract or proforma, the dates and obligations.

Created from an accepted / partially accepted quote (its accepted items only), from a won tender's approved proposal
(the organizer as customer, the performance guarantee linked) or by hand from the case's ``sold`` items; one open order
per quote / proposal (409 ``order_exists``). Status: draft -> confirmed (needs the signed document or a reason
«بدون سند امضاشده») -> in_progress (a PO sent or a delivery recorded) -> delivered (every item delivered) -> closed
(Phase 9); cancelled with a reason. After confirmation, quantities, prices, delivery dates and terms change only
through an amendment (reason, optional document; ``ops.sales_order_change``).
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.execution.common import ZERO, get_sales_order, money, reason_required
from app.modules.execution.models import (Delivery, DeliveryItem, PaymentMilestone, PaymentRecord, PurchaseOrder,
                                          SalesOrder, SalesOrderChange, SalesOrderItem)
from app.modules.execution.numbering import next_number, numbering_year
from app.modules.parties import clock
from app.modules.parties import service as parties
from app.modules.quotes import service as quotes
from app.modules.quotes.models import Quote, QuoteItem
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot

OPEN = ("draft", "confirmed", "in_progress")
LIVE = ("confirmed", "in_progress", "delivered")
FREE_FIELDS = ("contact_id", "customer_ref", "contract_date", "signed_document_id", "delivery_place", "warranty_months",
               "performance_guarantee_id", "notes")
AMENDABLE = ("price_basis", "incoterm", "incoterm_place", "incoterm_place_location_id", "payment_terms", "delivery_terms", "delivery_due_on")
ITEM_AMENDABLE = ("quantity", "unit_price", "delivery_due_on")
NO_DOCUMENT = "بدون سند امضاشده"


def items_of(db: Session, order_id: uuid.UUID) -> list[SalesOrderItem]:
    return list(db.scalars(select(SalesOrderItem).where(SalesOrderItem.sales_order_id == order_id)
                           .order_by(SalesOrderItem.position)))


def orders_of(db: Session, case_id: uuid.UUID) -> list[SalesOrder]:
    return list(db.scalars(select(SalesOrder).where(SalesOrder.case_id == case_id).order_by(SalesOrder.created_at)))


def changes_of(db: Session, order_id: uuid.UUID) -> list[SalesOrderChange]:
    return list(db.scalars(select(SalesOrderChange).where(SalesOrderChange.sales_order_id == order_id)
                           .order_by(SalesOrderChange.created_at)))


def delivered_quantities(db: Session, order_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    rows = db.execute(select(DeliveryItem.sales_order_item_id, func.sum(DeliveryItem.quantity))
                      .join(Delivery, Delivery.id == DeliveryItem.delivery_id)
                      .where(Delivery.sales_order_id == order_id).group_by(DeliveryItem.sales_order_item_id)).all()
    return {item_id: qty for item_id, qty in rows}


def _existing(db: Session, *, quote_id=None, proposal_id=None) -> SalesOrder | None:
    query = select(SalesOrder).where(SalesOrder.status != "cancelled")
    query = query.where(SalesOrder.quote_id == quote_id) if quote_id else query.where(SalesOrder.tender_proposal_id == proposal_id)
    return db.scalar(query)


def _order_exists(row: SalesOrder) -> Conflict:
    return Conflict("order_exists", "An open sales order already exists for this source",
                    {"sales_order_id": str(row.id), "number": row.number})


def _check_customer(db: Session, party_id, contact_id) -> None:
    if party_id is None:
        raise AppError("customer_required", "The sales order needs a customer", status=422)
    parties.get_party(db, party_id)
    if contact_id and parties.get_contact(db, contact_id).party_id != party_id:
        raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)


def _unit_label(item) -> str | None:
    return getattr(item, "unit_text", None) or getattr(item, "unit_code", None)


def _totals(db: Session, order: SalesOrder) -> None:
    rows = items_of(db, order.id)
    order.subtotal = money(sum((r.total for r in rows), ZERO))
    order.vat_amount = money(sum((r.vat_amount for r in rows), ZERO))
    order.total = money(order.subtotal + order.vat_amount)


def _new(db: Session, case_id, data: dict, calendar: str, source: str, actor: str | None, rows: list[dict]) -> SalesOrder:
    case = sourcing.get_case(db, case_id)
    _check_customer(db, data.get("customer_party_id"), data.get("contact_id"))
    if not rows:
        raise AppError("no_items", "There are no items to order", status=422)
    order = SalesOrder(case_id=case.id, number=next_number(db, "sales_order", numbering_year(clock.today(), calendar)),
                       status="draft", **data)
    db.add(order)
    flush(db, "invalid_sales_order")
    for position, row in enumerate(rows, start=1):
        db.add(SalesOrderItem(sales_order_id=order.id, position=position, **row))
    flush(db, "invalid_sales_order_item")
    _totals(db, order)
    flush(db, "invalid_sales_order")
    events.record(db, "sales_order", order.id, "create", jsonable({
        "number": order.number, "case_id": case.id, "source": order.source, "quote_id": order.quote_id,
        "tender_proposal_id": order.tender_proposal_id, "customer_party_id": order.customer_party_id,
        "currency": order.currency, "total": order.total, "items": len(rows)}), source, actor=actor)
    events.record(db, "case", case.id, "sales_order_add", jsonable({"sales_order_id": order.id, "number": order.number}),
                  source, actor=actor)
    return order


def create_from_quote(db: Session, quote_id: uuid.UUID, data: dict, calendar: str, source: str,
                      actor: str | None = None) -> SalesOrder:
    quote = quotes.get_quote(db, quote_id)
    if quote.status not in ("accepted", "partially_accepted"):
        raise Conflict("quote_not_accepted", f"The quote is {quote.status}; record the customer's acceptance first",
                       {"status": quote.status})
    existing = _existing(db, quote_id=quote.id)
    if existing:
        raise _order_exists(existing)
    names = {i.id: getattr(i, f"canonical_{quote.language}", None) or i.name   # v0.9.0: canonical description
             for i in sourcing_items.items_of(db, case_id=quote.case_id)}
    rows = [{"line_item_id": q.line_item_id, "description": q.description_override or names.get(q.line_item_id, ""),
             "quantity": q.quantity, "unit": _unit_label(q), "unit_price": q.unit_price, "total": q.total,
             "vat_amount": q.vat_amount or ZERO}
            for q in quotes.items_of(db, quote.id) if q.outcome == "accepted"]
    head = {"source": "quote", "quote_id": quote.id, "customer_party_id": data.get("customer_party_id") or quote.buyer_party_id,
            "contact_id": data.get("contact_id") or quote.contact_id, "currency": quote.currency,
            "price_basis": quote.price_basis, "incoterm": quote.incoterm, "incoterm_place": quote.incoterm_place,
            "payment_terms": quote.payment_terms, "delivery_terms": quote.delivery_terms,
            **{k: data.get(k) for k in ("customer_ref", "contract_date", "delivery_due_on", "delivery_place",
                                        "warranty_months", "notes")}}
    return _new(db, quote.case_id, head, calendar, source, actor, rows)


def create_from_proposal(db: Session, proposal_id: uuid.UUID, data: dict, calendar: str, source: str,
                         actor: str | None = None) -> SalesOrder:
    from app.modules.tenders import proposal as tender_proposals
    from app.modules.tenders.common import get_tender
    from app.modules.tenders.guarantees import guarantees_of

    row = tender_proposals.get_proposal(db, proposal_id)
    tender = get_tender(db, row.tender_id)
    if row.status != "approved":
        raise Conflict("proposal_not_approved", "Only an approved proposal becomes a sales order", {"status": row.status})
    if tender.result != "won":
        raise Conflict("tender_not_won", "The tender is not won", {"result": tender.result})
    existing = _existing(db, proposal_id=row.id)
    if existing:
        raise _order_exists(existing)
    names = {i.id: i.canonical_fa or i.name for i in sourcing_items.items_of(db, case_id=tender.case_id)}
    lines = tender_proposals.lines_of(db, row.id)
    vat_rate = (row.vat_amount / row.subtotal) if row.subtotal else ZERO
    rows = [{"line_item_id": x.line_item_id, "description": names.get(x.line_item_id, ""), "quantity": x.quantity,
             "unit": _unit_label(x), "unit_price": x.unit_price, "total": x.total, "vat_amount": money(x.total * vat_rate)}
            for x in lines]
    performance = next((g for g in guarantees_of(db, case_id=tender.case_id)
                        if g.purpose == "performance" and g.status != "cancelled"), None)
    case = sourcing.get_case(db, tender.case_id)
    head = {"source": "tender_proposal", "tender_proposal_id": row.id,
            "customer_party_id": data.get("customer_party_id") or tender.organizer_party_id or case.party_id,
            "contact_id": data.get("contact_id"), "currency": row.currency, "price_basis": row.price_basis,
            "performance_guarantee_id": performance.id if performance else None,
            "customer_ref": data.get("customer_ref") or tender.tender_no,
            **{k: data.get(k) for k in ("contract_date", "delivery_due_on", "delivery_place", "warranty_months", "notes",
                                        "payment_terms", "delivery_terms")}}
    return _new(db, tender.case_id, head, calendar, source, actor, rows)


def _accepted_quote_item(db: Session, line_item_id: uuid.UUID) -> QuoteItem | None:
    return db.scalar(select(QuoteItem).join(Quote, Quote.id == QuoteItem.quote_id).where(
        QuoteItem.line_item_id == line_item_id, QuoteItem.outcome == "accepted",
        Quote.status.in_(("accepted", "partially_accepted"))).order_by(Quote.created_at.desc()).limit(1))


def create_manual(db: Session, case_id: uuid.UUID, data: dict, calendar: str, source: str,
                  actor: str | None = None) -> SalesOrder:
    """From the case's ``sold`` items (prices from the quote that sold them, else 0 to fill in)."""
    case = sourcing.get_case(db, case_id)
    rows = []
    for item in sourcing_items.items_of(db, case_id=case.id):
        if item.status != "sold":
            continue
        q = _accepted_quote_item(db, item.id)
        quantity = q.quantity if q else (item.quantity or Decimal(1))
        price = q.unit_price if q else ZERO
        rows.append({"line_item_id": item.id, "description": item.name, "quantity": quantity,
                     "unit": item.unit_text or item.unit_code, "unit_price": price, "total": money(quantity * price),
                     "vat_amount": q.vat_amount if q else ZERO})
    if not rows:
        raise AppError("no_sold_items", "The case has no sold items", status=422)
    currency = data.get("currency")
    if not currency:
        q = _accepted_quote_item(db, rows[0]["line_item_id"])
        currency = quotes.get_quote(db, q.quote_id).currency if q else None
    if not currency:
        raise AppError("currency_required", "Choose the order currency", status=422)
    head = {"source": "manual", "customer_party_id": data.get("customer_party_id") or case.party_id, "currency": currency,
            **{k: data.get(k) for k in ("contact_id", "price_basis", "incoterm", "incoterm_place", "payment_terms",
                                        "delivery_terms", "customer_ref", "contract_date", "delivery_due_on",
                                        "delivery_place", "warranty_months", "notes") if data.get(k) is not None}}
    return _new(db, case.id, head, calendar, source, actor, rows)


def candidates(db: Session, case_id: uuid.UUID) -> list[dict]:
    """The «Create sales order» prompt: accepted quotes and approved proposals of won tenders without an open order."""
    out = []
    for q in quotes.list_quotes(db, case_id=case_id):
        if q.status in ("accepted", "partially_accepted") and _existing(db, quote_id=q.id) is None:
            out.append({"source": "quote", "quote_id": q.id, "number": q.number, "status": q.status, "total": q.total,
                        "currency": q.currency})
    try:
        from app.modules.tenders import proposal as tender_proposals
        from app.modules.tenders.common import tender_of_case
    except ImportError:  # pragma: no cover
        return out
    tender = tender_of_case(db, case_id)
    if tender is not None and tender.result == "won":
        for p in tender_proposals.proposals_of(db, tender.id):
            if p.status == "approved" and _existing(db, proposal_id=p.id) is None:
                out.append({"source": "tender_proposal", "tender_proposal_id": p.id, "number": tender.tender_no,
                            "version": p.version, "total": p.total, "currency": p.currency})
    return jsonable(out)


# ---- editing, confirmation, amendments ----------------------------------------------------------------------------

def _check_refs(db: Session, order: SalesOrder, changes: dict) -> None:
    for key in ("signed_document_id",):
        if changes.get(key):
            documents.get(db, changes[key])
    if changes.get("contact_id") and parties.get_contact(db, changes["contact_id"]).party_id != order.customer_party_id:
        raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)
    if changes.get("performance_guarantee_id"):
        from app.modules.tenders.guarantees import get_guarantee

        g = get_guarantee(db, changes["performance_guarantee_id"])
        if g.purpose != "performance" or g.case_id != order.case_id:
            raise AppError("not_a_performance_guarantee", "Link a performance guarantee of this case", status=422)


def update_order(db: Session, order_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> SalesOrder:
    order = get_sales_order(db, order_id)
    if order.status in ("closed", "cancelled"):
        raise Conflict("sales_order_locked", f"The sales order is {order.status}", {"status": order.status})
    locked = [k for k in changes if k in AMENDABLE] if order.status != "draft" else []
    if locked:
        raise Conflict("amend_required", "After confirmation these fields change only through an amendment",
                       {"fields": locked})
    _check_refs(db, order, changes)
    changed = diff(order, {k: v for k, v in changes.items() if k in FREE_FIELDS + AMENDABLE})
    flush(db, "invalid_sales_order")
    if changed:
        events.record(db, "sales_order", order.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return order


def update_item(db: Session, item_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> SalesOrderItem:
    from app.modules.execution.common import get

    row = get(db, SalesOrderItem, item_id, "Sales order item")
    order = get_sales_order(db, row.sales_order_id)
    if order.status != "draft":
        raise Conflict("amend_required", "After confirmation items change only through an amendment",
                       {"fields": list(changes)})
    old_total = row.total
    changed = diff(row, {k: v for k, v in changes.items() if k in ITEM_AMENDABLE + ("description", "unit")})
    _reprice(row, old_total)
    flush(db, "invalid_sales_order_item")
    _totals(db, order)
    flush(db, "invalid_sales_order")
    if changed:
        events.record(db, "sales_order", order.id, "item_update", jsonable({"item_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def _reprice(row: SalesOrderItem, old_total: Decimal) -> None:
    rate = (row.vat_amount / old_total) if old_total else ZERO
    row.total = money(row.quantity * row.unit_price)
    row.vat_amount = money(row.total * rate)


def remove_item(db: Session, item_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    from app.modules.execution.common import get

    row = get(db, SalesOrderItem, item_id, "Sales order item")
    order = get_sales_order(db, row.sales_order_id)
    if order.status != "draft":
        raise Conflict("sales_order_not_draft", "Items are removed only from a draft order", {"status": order.status})
    if len(items_of(db, order.id)) == 1:
        raise AppError("no_items", "A sales order keeps at least one item", status=422)
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    _totals(db, order)
    flush(db, "invalid_sales_order")
    events.record(db, "sales_order", order.id, "item_remove", jsonable({"item": snapshot}), source, actor=actor)


def confirm(db: Session, order_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> SalesOrder:
    """Needs the signed contract / proforma, or the explicit reason «بدون سند امضاشده» (kept and in the event)."""
    order = get_sales_order(db, order_id)
    if order.status != "draft":
        raise Conflict("sales_order_not_draft", f"The sales order is {order.status}", {"status": order.status})
    if data.get("signed_document_id"):
        documents.get(db, data["signed_document_id"])
        order.signed_document_id = data["signed_document_id"]
    reason = (data.get("no_document_reason") or "").strip() or None
    if order.signed_document_id is None and not reason:
        raise AppError("signed_document_required",
                       "Attach the signed contract or proforma, or confirm «بدون سند امضاشده» with a reason", status=422)
    order.no_document_reason = None if order.signed_document_id else reason
    order.status, order.confirmed_at = "confirmed", clock.now()
    flush(db, "invalid_sales_order")
    events.record(db, "sales_order", order.id, "confirm", jsonable({
        "signed_document_id": order.signed_document_id, "no_document_reason": order.no_document_reason,
        "without_signed_document": order.signed_document_id is None}), source, actor=actor)
    from app.core.modules import load_hooks

    load_hooks()
    for hook in _confirmed_hooks:
        hook(db, order, source, actor)
    return order


_confirmed_hooks: list = []


def register_order_confirmed(fn) -> None:
    """``fn(db, order, source, actor)`` after a sales order is confirmed (the process checklist is created there)."""
    if fn not in _confirmed_hooks:
        _confirmed_hooks.append(fn)


def _text(value) -> str | None:
    return None if value is None else str(value)


def amend(db: Session, order_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> SalesOrder:
    """Change quantities, prices, delivery dates or terms of a confirmed order: one change row per field (old, new,
    reason, document); totals follow. A quantity never goes below what was already delivered."""
    order = get_sales_order(db, order_id)
    if order.status not in ("confirmed", "in_progress"):
        raise Conflict("sales_order_not_amendable", f"A {order.status} sales order is not amended", {"status": order.status})
    reason = reason_required(data.get("reason"), "reason_required", "An amendment needs a reason")
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    changes = []
    for field, value in (data.get("changes") or {}).items():
        if field not in AMENDABLE:
            raise AppError("not_amendable", "This field is not changed by an amendment", {"field": field}, status=422)
        if field == "delivery_due_on" and isinstance(value, str):
            try:
                value = date.fromisoformat(value)
            except ValueError:
                raise AppError("invalid_date", "delivery_due_on is a date", status=422) from None
        old = getattr(order, field)
        if old != value:
            setattr(order, field, value)
            changes.append(SalesOrderChange(sales_order_id=order.id, field=field, old_value=_text(old),
                                            new_value=_text(value), reason=reason, document_id=data.get("document_id")))
    by_id = {r.id: r for r in items_of(db, order.id)}
    delivered = delivered_quantities(db, order.id)
    for spec in data.get("items") or []:
        row = by_id.get(spec["sales_order_item_id"])
        if row is None:
            raise AppError("item_not_of_order", "The item belongs to another order",
                           {"sales_order_item_id": str(spec["sales_order_item_id"])}, status=422)
        old_total = row.total
        for field in ITEM_AMENDABLE:
            if field not in spec or spec[field] is None and field != "delivery_due_on":
                continue
            old, value = getattr(row, field), spec[field]
            if field == "quantity" and value < delivered.get(row.id, ZERO):
                raise AppError("below_delivered", "The quantity is below what was already delivered",
                               {"sales_order_item_id": str(row.id), "delivered": str(delivered[row.id])}, status=422)
            if old != value:
                setattr(row, field, value)
                changes.append(SalesOrderChange(sales_order_id=order.id, sales_order_item_id=row.id, field=field,
                                                old_value=_text(old), new_value=_text(value), reason=reason,
                                                document_id=data.get("document_id")))
        _reprice(row, old_total)
    if not changes:
        raise AppError("nothing_to_amend", "The amendment changes nothing", status=422)
    for change in changes:
        db.add(change)
    flush(db, "invalid_sales_order_item")
    _totals(db, order)
    flush(db, "invalid_sales_order")
    events.record(db, "sales_order", order.id, "amend", jsonable({
        "reason": reason, "document_id": data.get("document_id"),
        "changes": [{"field": c.field, "item_id": c.sales_order_item_id, "old": c.old_value, "new": c.new_value}
                    for c in changes]}), source, actor=actor)
    from app.modules.execution import milestones

    milestones.after_order_total_changed(db, order)
    return order


def set_in_progress(db: Session, order: SalesOrder, cause: str, source: str, actor: str | None) -> None:
    if order.status == "confirmed":
        order.status = "in_progress"
        flush(db, "invalid_sales_order")
        events.record(db, "sales_order", order.id, "status", {"old_status": "confirmed", "new_status": "in_progress",
                                                               "cause": cause}, source, actor=actor)


def cancel(db: Session, order_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> SalesOrder:
    order = get_sales_order(db, order_id)
    if order.status not in OPEN:
        raise Conflict("sales_order_locked", f"A {order.status} sales order cannot be cancelled", {"status": order.status})
    if db.scalar(select(func.count()).select_from(Delivery).where(Delivery.sales_order_id == order.id)):
        raise Conflict("has_deliveries", "Reverse the deliveries first")
    open_pos = db.scalar(select(func.count()).select_from(PurchaseOrder).where(
        PurchaseOrder.sales_order_id == order.id, PurchaseOrder.status.notin_(("cancelled", "superseded", "draft"))))
    if open_pos:
        raise Conflict("has_purchase_orders", "Cancel the purchase orders of this sales order first", {"purchase_orders": open_pos})
    reason = reason_required(reason)
    old = order.status
    order.status, order.cancel_reason = "cancelled", reason
    flush(db, "invalid_sales_order")
    from app.modules.execution import followups, milestones

    milestones.cancel_open_of_order(db, order.id, reason, source, actor)
    followups.cancel(db, f"sales order cancelled: {reason}"[:200], source, actor, ref_id=order.id)
    events.record(db, "sales_order", order.id, "cancel", {"old_status": old, "reason": reason}, source, actor=actor)
    return order


def delete_order(db: Session, order_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Drafts only; a confirmed order is cancelled instead."""
    order = get_sales_order(db, order_id)
    if order.status != "draft":
        raise Conflict("sales_order_not_draft", "Only a draft sales order is deleted; cancel it instead",
                       {"status": order.status})
    paid = db.scalar(select(func.count()).select_from(PaymentRecord).join(
        PaymentMilestone, PaymentMilestone.id == PaymentRecord.milestone_id).where(PaymentMilestone.sales_order_id == order.id))
    if paid:
        raise Conflict("has_payments", "Payments were recorded on this order", {"payments": paid})
    pos = db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.sales_order_id == order.id))
    if pos:
        raise Conflict("in_use", "Purchase orders refer to this order", {"purchase_orders": pos})
    snapshot = {"order": row_snapshot(order), "items": [row_snapshot(r) for r in items_of(db, order.id)]}
    for ms in db.scalars(select(PaymentMilestone).where(PaymentMilestone.sales_order_id == order.id)):
        db.delete(ms)
    for row in items_of(db, order.id):
        db.delete(row)
    db.flush()
    db.delete(order)
    flush(db, "in_use")
    events.record(db, "sales_order", order_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def delivery_progress(db: Session, order: SalesOrder) -> dict:
    """Per item «۳۰ از ۸۸ تحویل شد» and «۲ از ۳ قلم»."""
    delivered = delivered_quantities(db, order.id)
    rows = []
    for r in items_of(db, order.id):
        done = delivered.get(r.id, ZERO)
        rows.append({"sales_order_item_id": r.id, "ordered": r.quantity, "delivered": done,
                     "complete": done >= r.quantity})
    return jsonable({"items": rows, "items_total": len(rows), "items_delivered": sum(1 for x in rows if x["complete"])})


def order_out(db: Session, order: SalesOrder) -> dict:
    from app.modules.execution import milestones

    def party(pid):
        if pid is None:
            return None
        p = parties.get_party(db, pid)
        return {"id": p.id, "name_fa": p.name_fa, "name_en": p.name_en}

    progress = delivery_progress(db, order)
    by_item = {x["sales_order_item_id"]: x for x in progress["items"]}
    return jsonable({
        **row_snapshot(order), "customer": party(order.customer_party_id),
        "items": [{**row_snapshot(r), "delivered": by_item.get(str(r.id), {}).get("delivered", "0")}
                  for r in items_of(db, order.id)],
        "changes": [row_snapshot(c) for c in changes_of(db, order.id)], "progress": progress,
        "milestones": [milestones.milestone_out(db, x) for x in milestones.milestones_of(db, sales_order_id=order.id)],
        "outputs": parties.linked_documents(db, "sales_order", [str(order.id)]),
    })


__all__ = ["NO_DOCUMENT", "amend", "cancel", "candidates", "confirm", "create_from_proposal", "create_from_quote",
           "create_manual", "delete_order", "delivered_quantities", "delivery_progress", "items_of", "order_out",
           "orders_of", "register_order_confirmed", "remove_item", "set_in_progress", "update_item", "update_order"]
