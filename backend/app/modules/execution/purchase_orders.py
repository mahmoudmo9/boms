"""Purchase orders to suppliers (v0.7.0).

"Create POs" on a sales order groups its items by the supplier of each item's selected offer and creates one draft
PO per supplier (and currency), prefilled from the offer (price per item unit, currency, Incoterm, payment terms,
lead time) with the ``po_terms`` template of the PO's language; items without a selected offer are listed to resolve.
Flow: draft -> approved (numbers locked; a price above the cost sheet's purchase price by more than
``execution.po_price_tolerance_percent`` needs a reason, 409 ``po_above_cost_sheet``) -> sent (an outgoing interaction
with the follow-up «پیگیری تأیید سفارش»; the customer-prepayment ordering gate) -> confirmed (supplier ref, confirmed
ready date, document; «پیگیری آماده شدن» before the ready date) -> in_production / ready / shipped (manual, with a
note) -> received (all items received, M3) -> closed. A moved ready date keeps its history
(``ops.purchase_order_change``). Revise creates ``-v2`` and supersedes this one.
"""
import uuid
from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.core.time import ensure_aware
from app.modules.costing import service as costing
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.execution import followups, milestones
from app.modules.execution.common import ZERO, get, get_purchase_order, get_sales_order, money, reason_required, today
from app.modules.execution.models import PurchaseOrder, PurchaseOrderChange, PurchaseOrderItem
from app.modules.execution.numbering import next_number, numbering_year
from app.modules.parties import clock
from app.modules.parties import interactions as party_interactions
from app.modules.parties import service as parties
from app.modules.sourcing import coverage as sourcing_coverage
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing import offers as sourcing_offers
from app.modules.sourcing import templates as sourcing_templates
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings

LOCKED = ("cancelled", "superseded", "closed")
SENT_OR_LATER = ("sent", "confirmed", "in_production", "ready", "shipped", "received", "closed")
MANUAL_STATUSES = {"in_production": ("confirmed",), "ready": ("confirmed", "in_production"),
                   "shipped": ("confirmed", "in_production", "ready"), "closed": ("received", "shipped", "ready")}
HEAD_FIELDS = ("contact_id", "language", "incoterm", "incoterm_place", "incoterm_place_location_id", "payment_terms", "delivery_terms", "ready_due_on",
               "delivery_place", "direct_to_customer", "terms_text", "notes")
FREE_AFTER_APPROVAL = ("contact_id", "delivery_place", "direct_to_customer", "notes")
CHANNELS = {"email": "email", "whatsapp": "whatsapp", "phone": "call", "in_person": "in_person", "letter": "other",
            "other": "other"}


def items_of(db: Session, po_id: uuid.UUID) -> list[PurchaseOrderItem]:
    return list(db.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == po_id)
                           .order_by(PurchaseOrderItem.position)))


def orders_of(db: Session, case_id: uuid.UUID) -> list[PurchaseOrder]:
    return list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.case_id == case_id).order_by(PurchaseOrder.created_at)))


def changes_of(db: Session, po_id: uuid.UUID) -> list[PurchaseOrderChange]:
    return list(db.scalars(select(PurchaseOrderChange).where(PurchaseOrderChange.purchase_order_id == po_id)
                           .order_by(PurchaseOrderChange.created_at)))


def _language_for(db: Session, party_id) -> str:
    return "fa" if (parties.get_party(db, party_id).country_iso2 or "IR") == "IR" else "en"


def _primary_contact(db: Session, party_id) -> uuid.UUID | None:
    active = [c for c in parties.contacts_of(db, party_id) if c.status == "active"]
    return next((c.id for c in active if c.is_primary), active[0].id if active else None)


def render_terms(db: Session, po: PurchaseOrder) -> str:
    template = sourcing_templates.default_of_kind(db, "po_terms", po.language)
    if template is None:
        return ""
    lang = po.language
    supplier = parties.get_party(db, po.supplier_party_id)
    contact = parties.get_contact(db, po.contact_id) if po.contact_id else None
    pick = (lambda fa, en: (fa or en or "") if lang == "fa" else (en or fa or ""))
    from app.modules.sourcing import rfq

    values = {"supplier_name": pick(supplier.name_fa, supplier.name_en),
              "contact_name": pick(contact.name_fa, contact.name_en) if contact else "",
              "payment_terms": po.payment_terms or "",
              "incoterm": " ".join(x for x in (po.incoterm, po.incoterm_place) if x),
              "ready_due_on": sourcing_templates.format_date(po.ready_due_on, lang, "fa" if lang == "fa" else "latin"),
              "delivery_place": po.delivery_place or "", "delivery_terms": po.delivery_terms or "",
              "case_title": sourcing.get_case(db, po.case_id).title or "", "signature": rfq.signature(db, lang)}
    return sourcing_templates.render(template.body_template, values, drop_empty_lines=True)


def _totals(db: Session, po: PurchaseOrder) -> None:
    po.subtotal = money(sum((r.total for r in items_of(db, po.id)), ZERO))
    po.total = po.subtotal


def _offer_line(db: Session, item, units) -> dict:
    """Unit price per item unit from the item's selected offer row (the cost sheet's own prefill rule)."""
    return costing._purchase_prefill(db, item, units)


def create_from_sales_order(db: Session, sales_order_id: uuid.UUID, calendar: str, source: str,
                            actor: str | None = None) -> dict:
    from app.modules.execution.sales_orders import items_of as so_items

    so = get_sales_order(db, sales_order_id)
    if so.status not in ("confirmed", "in_progress"):
        raise Conflict("sales_order_not_confirmed", "Confirm the sales order before ordering from suppliers",
                       {"status": so.status})
    ordered = set(db.scalars(select(PurchaseOrderItem.sales_order_item_id).join(
        PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id).where(
        PurchaseOrder.sales_order_id == so.id, PurchaseOrder.status.notin_(("cancelled", "superseded")))))
    units = sourcing_coverage.unit_index(db)
    groups: "OrderedDict[tuple, list]" = OrderedDict()
    unresolved = []
    for row in so_items(db, so.id):
        if row.id in ordered:
            continue
        item = sourcing_items.get_item(db, row.line_item_id)
        if not item.selected_offer_item_id:
            unresolved.append({"sales_order_item_id": row.id, "line_item_id": item.id, "description": row.description})
            continue
        offer_item = sourcing_offers.get_offer_item(db, item.selected_offer_item_id)
        offer = sourcing_offers.get_offer(db, offer_item.offer_id)
        line = _offer_line(db, item, units)
        groups.setdefault((offer.party_id, offer.currency), []).append((row, item, offer_item, offer, line))
    created = []
    for (supplier_id, currency), rows in groups.items():
        offers = {o.id: o for _, _, _, o, _ in rows}
        first = rows[0][3]
        lead = max((oi.lead_time_days or o.lead_time_days or 0) for _, _, oi, o, _ in rows)
        po = PurchaseOrder(case_id=so.case_id, sales_order_id=so.id, version=1, status="draft",
                           number=next_number(db, "purchase_order", numbering_year(clock.today(), calendar)),
                           supplier_party_id=supplier_id, contact_id=_primary_contact(db, supplier_id),
                           offer_id=first.id if len(offers) == 1 else None, language=_language_for(db, supplier_id),
                           currency=currency, incoterm=first.incoterm, incoterm_place=first.incoterm_place,
                           payment_terms=first.payment_terms, ready_due_on=today() + timedelta(days=lead) if lead else None,
                           delivery_place=so.delivery_place)
        db.add(po)
        flush(db, "invalid_purchase_order")
        for position, (row, item, offer_item, _o, line) in enumerate(rows, start=1):
            price = line.get("amount") or ZERO
            db.add(PurchaseOrderItem(purchase_order_id=po.id, line_item_id=item.id, sales_order_item_id=row.id,
                                     offer_item_id=offer_item.id, position=position, description=row.description,
                                     quantity=row.quantity, unit=row.unit, unit_price=price,
                                     total=money(row.quantity * price)))
        flush(db, "invalid_purchase_order_item")
        _totals(db, po)
        po.terms_text = render_terms(db, po)
        flush(db, "invalid_purchase_order")
        events.record(db, "purchase_order", po.id, "create", jsonable({
            "number": po.number, "sales_order_id": so.id, "supplier_party_id": supplier_id, "currency": currency,
            "total": po.total, "items": len(rows), "offer_ids": list(offers)}), source, actor=actor)
        events.record(db, "case", so.case_id, "purchase_order_add", jsonable({"purchase_order_id": po.id,
                                                                               "number": po.number}), source, actor=actor)
        created.append(po)
    return {"created": created, "unresolved": jsonable(unresolved)}


def _draft(po: PurchaseOrder) -> None:
    if po.status != "draft":
        raise Conflict("purchase_order_not_draft", f"The purchase order is {po.status}; revise it to change it",
                       {"status": po.status})


def update_order(db: Session, po_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> PurchaseOrder:
    po = get_purchase_order(db, po_id)
    if po.status in LOCKED:
        raise Conflict("purchase_order_locked", f"The purchase order is {po.status}", {"status": po.status})
    if po.status != "draft":
        locked = [k for k in changes if k not in FREE_AFTER_APPROVAL]
        if locked:
            raise Conflict("purchase_order_not_draft", "After approval change the ready date with a reason, or revise",
                           {"fields": locked})
    if changes.get("contact_id") and parties.get_contact(db, changes["contact_id"]).party_id != po.supplier_party_id:
        raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)
    manual_terms = "terms_text" in changes
    changed = diff(po, {k: v for k, v in changes.items() if k in HEAD_FIELDS})
    if manual_terms:
        po.terms_manual = True
    elif po.status == "draft" and not po.terms_manual and set(changed) & {"language", "incoterm", "incoterm_place",
                                                                           "payment_terms", "ready_due_on",
                                                                           "delivery_place", "delivery_terms",
                                                                           "contact_id"}:
        po.terms_text = render_terms(db, po)
    flush(db, "invalid_purchase_order")
    if changed:
        events.record(db, "purchase_order", po.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return po


def update_item(db: Session, item_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> PurchaseOrderItem:
    row = get(db, PurchaseOrderItem, item_id, "Purchase order item")
    po = get_purchase_order(db, row.purchase_order_id)
    _draft(po)
    changed = diff(row, {k: v for k, v in changes.items() if k in ("description", "quantity", "unit", "unit_price")})
    row.total = money(row.quantity * row.unit_price)
    flush(db, "invalid_purchase_order_item")
    _totals(db, po)
    flush(db, "invalid_purchase_order")
    if changed:
        events.record(db, "purchase_order", po.id, "item_update", jsonable({"item_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def remove_item(db: Session, item_id: uuid.UUID, source: str, actor: str | None = None) -> PurchaseOrder:
    row = get(db, PurchaseOrderItem, item_id, "Purchase order item")
    po = get_purchase_order(db, row.purchase_order_id)
    _draft(po)
    if len(items_of(db, po.id)) == 1:
        raise AppError("no_items", "A purchase order keeps at least one item", status=422)
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    _totals(db, po)
    flush(db, "invalid_purchase_order")
    events.record(db, "purchase_order", po.id, "item_remove", jsonable({"item": snapshot}), source, actor=actor)
    return po


FX_MISSING_FA = "نرخ ارز در برگهٔ هزینه نیست"


def _sheet_rate(fx: dict, src: str, dst: str, pricing: str) -> Decimal | None:
    """1 ``src`` in ``dst`` from the sheet's FX entries: direct, reverse, or through the pricing currency."""
    if src == dst:
        return Decimal(1)
    if (src, dst) in fx:
        return fx[(src, dst)]
    if (dst, src) in fx and fx[(dst, src)]:
        return Decimal(1) / fx[(dst, src)]
    if pricing not in (src, dst):
        a, b = _sheet_rate(fx, src, pricing, pricing), _sheet_rate(fx, dst, pricing, pricing)
        if a is not None and b:
            return a / b
    return None


def above_cost_sheet(db: Session, po: PurchaseOrder) -> list[dict]:
    """PO prices above the current cost sheet's purchase price by more than the tolerance. A PO in another currency
    than the purchase line is converted with the sheet's FX entries (v0.8.0); without a rate the item is flagged
    «نرخ ارز در برگهٔ هزینه نیست» (``check: fx_missing``) instead of being skipped."""
    sheet = costing.current_sheet(db, po.case_id)
    if sheet is None:
        return []
    tolerance = Decimal(str(settings.get(db, "execution.po_price_tolerance_percent") or 0))
    purchase = {line.line_item_id: line for line in costing.lines_of(db, sheet.id)
                if line.kind == "purchase" and line.scope == "item" and line.line_item_id and line.amount is not None}
    fx = {(e.from_currency, e.to_currency): e.rate for e in costing.fx_of(db, sheet.id)}
    out = []
    for row in items_of(db, po.id):
        line = purchase.get(row.line_item_id)
        if line is None:
            continue
        line_currency = line.currency or sheet.pricing_currency
        base = {"purchase_order_item_id": str(row.id), "description": row.description, "unit_price": str(row.unit_price),
                "cost_sheet_price": str(line.amount), "cost_sheet_currency": line_currency,
                "tolerance_percent": str(tolerance), "currency": po.currency}
        rate = _sheet_rate(fx, po.currency, line_currency, sheet.pricing_currency)
        if rate is None:
            out.append({**base, "check": "fx_missing", "message_fa": FX_MISSING_FA,
                        "message_en": f"No {po.currency} -> {line_currency} rate on the cost sheet"})
            continue
        limit = money(line.amount * (Decimal(100) + tolerance) / Decimal(100))
        price = money(row.unit_price * rate)
        if price > limit:
            extra = {} if line_currency == po.currency else {"unit_price_converted": str(price), "rate": str(rate)}
            out.append({**base, "check": "above", **extra})
    return out


def approve(db: Session, po_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PurchaseOrder:
    po = get_purchase_order(db, po_id)
    _draft(po)
    if not items_of(db, po.id):
        raise AppError("no_items", "The purchase order has no items", status=422)
    above = above_cost_sheet(db, po)
    reason = (data.get("reason") or "").strip() or None
    if above and not (data.get("confirm_above_cost") and reason):
        raise Conflict("po_above_cost_sheet", "Prices above the cost sheet's purchase price need a reason",
                       {"items": above})
    po.price_override_reason = reason if above else None
    po.status, po.approved_at = "approved", clock.now()
    flush(db, "invalid_purchase_order")
    events.record(db, "purchase_order", po.id, "approve", jsonable({
        "number": po.number, "total": po.total, "above_cost_sheet": above, "override_reason": po.price_override_reason}),
        source, actor=actor)
    return po


def mark_sent(db: Session, po_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PurchaseOrder:
    """Records the sending (BOMS sends nothing): an outgoing interaction with the supplier and the follow-up
    «پیگیری تأیید سفارش» after ``execution.po_confirm_days``; the customer-prepayment ordering gate applies."""
    po = get_purchase_order(db, po_id)
    if po.status in ("sent", "confirmed"):
        raise Conflict("purchase_order_already_sent", f"The purchase order is already {po.status}",
                       {"status": po.status})
    if po.status != "approved":
        raise Conflict("purchase_order_not_approved", f"The purchase order is {po.status}; approve it first",
                       {"status": po.status})
    override = milestones.check_ordering_gate(db, po.sales_order_id, bool(data.get("confirm_without_prepayment")),
                                              data.get("reason"))
    try:
        sent_at = ensure_aware(data.get("sent_at") or clock.now())
    except ValueError:
        raise AppError("naive_datetime", "sent_at needs a timezone", status=422) from None
    due = today() + timedelta(days=settings.get(db, "execution.po_confirm_days"))
    interaction, followup = party_interactions.create_interaction(db, {
        "party_id": po.supplier_party_id, "contact_id": po.contact_id, "channel": CHANNELS[data.get("channel") or "email"],
        "direction": "out", "occurred_at": sent_at, "subject": f"Purchase order {po.number}",
        "body": f"{po.number}: {po.total} {po.currency}",
        "followup": {"action": f"پیگیری تأیید سفارش {po.number}", "due_on": due}}, source, actor)
    followups.adopt(db, case_id=po.case_id, purpose="po_confirm", ref_id=po.id, followup_id=followup.id)
    po.status, po.sent_at, po.interaction_id = "sent", sent_at, interaction.id
    po.prepayment_override_reason = override
    flush(db, "invalid_purchase_order")
    events.record(db, "purchase_order", po.id, "sent", jsonable({
        "number": po.number, "interaction_id": interaction.id, "followup_id": followup.id, "sent_at": sent_at,
        "without_prepayment": override is not None, "prepayment_override_reason": override}), source, actor=actor)
    if po.sales_order_id:
        from app.modules.execution.sales_orders import set_in_progress

        set_in_progress(db, get_sales_order(db, po.sales_order_id), "purchase_order_sent", source, actor)
    _process_hint(db, po, "po_sent", source, actor)
    return po


def _ready_followup(db: Session, po: PurchaseOrder, note: str, source: str, actor: str | None) -> None:
    """«پیگیری آماده شدن» N days before the ready date (today when that is past), while not ready."""
    target = po.ready_due_on if po.status in ("confirmed", "in_production") else None
    offset = settings.get(db, "execution.ready_followup_days_before")
    links = followups.links(db, purpose="po_ready", ref_id=po.id)
    if target is None:
        for _, f in links:
            party_interactions.cancel_followup(db, f.id, note, source, actor)
        return
    due = max(target - timedelta(days=offset), today())
    action = f"پیگیری آماده شدن سفارش {po.number}"
    if links:
        for _, f in links:
            if f.due_on != due:
                party_interactions.reschedule_followup(db, f.id, due, note, source, actor)
    else:
        followups.create(db, case_id=po.case_id, purpose="po_ready", ref_id=po.id, party_id=po.supplier_party_id,
                         action=action, due_on=due, source=source, actor=actor)


def _record_change(db: Session, po: PurchaseOrder, field: str, old, new, reason: str, document_id=None) -> None:
    db.add(PurchaseOrderChange(purchase_order_id=po.id, field=field, old_value=None if old is None else str(old),
                               new_value=None if new is None else str(new), reason=reason, document_id=document_id))


def confirm(db: Session, po_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PurchaseOrder:
    """The supplier's confirmation: closes «پیگیری تأیید سفارش», sets the confirmed ready date (a changed date is
    kept in the history) and creates «پیگیری آماده شدن»."""
    po = get_purchase_order(db, po_id)
    if po.status != "sent":
        raise Conflict("purchase_order_not_sent", f"The purchase order is {po.status}", {"status": po.status})
    if data.get("confirmation_document_id"):
        documents.get(db, data["confirmation_document_id"])
    ready = data.get("confirmed_ready_on")
    po.supplier_ref = data.get("supplier_ref") or po.supplier_ref
    po.confirmation_document_id = data.get("confirmation_document_id") or po.confirmation_document_id
    po.confirmed_at = ensure_aware(data.get("confirmed_at") or clock.now())
    if ready:
        po.confirmed_ready_on = ready
        if ready != po.ready_due_on:
            _record_change(db, po, "ready_due_on", po.ready_due_on, ready, "تأیید تأمین‌کننده / supplier confirmation",
                           po.confirmation_document_id)
            po.ready_due_on = ready
    po.status = "confirmed"
    flush(db, "invalid_purchase_order")
    closed = followups.complete(db, f"confirmed by the supplier ({po.supplier_ref or '-'})", source, actor,
                                purpose="po_confirm", ref_id=po.id)
    _ready_followup(db, po, "supplier confirmation", source, actor)
    events.record(db, "purchase_order", po.id, "confirm", jsonable({
        "supplier_ref": po.supplier_ref, "confirmed_ready_on": po.confirmed_ready_on,
        "document_id": po.confirmation_document_id, "closed_followups": closed}), source, actor=actor)
    return po


def change_ready_date(db: Session, po_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PurchaseOrder:
    po = get_purchase_order(db, po_id)
    if po.status in LOCKED + ("received",):
        raise Conflict("purchase_order_locked", f"The purchase order is {po.status}", {"status": po.status})
    new = data["ready_due_on"]
    if new == po.ready_due_on:
        raise AppError("nothing_to_change", "The ready date is unchanged", status=422)
    reason = reason_required(data.get("reason"), "reason_required", "A moved ready date needs a reason")
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    _record_change(db, po, "ready_due_on", po.ready_due_on, new, reason, data.get("document_id"))
    old, po.ready_due_on = po.ready_due_on, new
    flush(db, "invalid_purchase_order")
    _ready_followup(db, po, f"ready date moved: {reason}"[:200], source, actor)
    events.record(db, "purchase_order", po.id, "ready_date", jsonable({"old": old, "new": new, "reason": reason}),
                  source, actor=actor)
    return po


def set_status(db: Session, po_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PurchaseOrder:
    """Manual production status: in_production / ready / shipped / closed, with a note and a date."""
    po = get_purchase_order(db, po_id)
    status = data["status"]
    allowed = MANUAL_STATUSES.get(status)
    if allowed is None:
        raise AppError("invalid_status", "This status is set by BOMS", {"status": status}, status=422)
    if po.status not in allowed:
        raise Conflict("invalid_transition", f"A {po.status} purchase order cannot become {status}",
                       {"status": po.status, "allowed_from": list(allowed)})
    old = po.status
    po.status, po.status_note = status, (data.get("note") or "").strip() or None
    if status == "ready":
        po.ready_on = data.get("on_date") or today()
    flush(db, "invalid_purchase_order")
    if status in ("ready", "shipped", "closed"):
        followups.complete(db, f"purchase order {status}", source, actor, purpose="po_ready", ref_id=po.id)
    events.record(db, "purchase_order", po.id, "status", jsonable({"old_status": old, "new_status": status,
                                                                  "note": po.status_note, "on": data.get("on_date")}),
                  source, actor=actor)
    if status == "ready":
        _process_hint(db, po, "goods_ready", source, actor)
    return po


def _revision_number(db: Session, po: PurchaseOrder) -> str:
    base = po.number.split("-v")[0]
    used = db.scalars(select(PurchaseOrder.number).where((PurchaseOrder.number == base)
                                                         | PurchaseOrder.number.like(f"{base}-v%"))).all()
    versions = [int(n.rsplit("-v", 1)[1]) if "-v" in n else 1 for n in used]
    return f"{base}-v{max(versions, default=1) + 1}"


def revise(db: Session, po_id: uuid.UUID, source: str, actor: str | None = None) -> PurchaseOrder:
    """The next version (``-v2``) as a draft with the same items and terms; this one becomes ``superseded`` and its
    open follow-ups are cancelled. Receipts stay on the old version (revise before receiving)."""
    old = get_purchase_order(db, po_id)
    if old.status in ("draft",) + LOCKED + ("received",):
        raise Conflict("purchase_order_locked", f"A {old.status} purchase order cannot be revised", {"status": old.status})
    if any(r.received_quantity > 0 for r in items_of(db, old.id)):
        raise Conflict("has_receipts", "Goods were received on this order")
    new = PurchaseOrder(**{k: getattr(old, k) for k in ("case_id", "sales_order_id", "supplier_party_id", "contact_id",
                                                        "offer_id", "language", "currency", "incoterm", "incoterm_place",
                                                        "payment_terms", "delivery_terms", "ready_due_on", "delivery_place",
                                                        "direct_to_customer", "terms_text", "terms_manual", "notes")},
                        number=_revision_number(db, old), version=old.version + 1, supersedes_id=old.id, status="draft")
    previous = old.status
    old.status = "superseded"
    flush(db, "invalid_purchase_order")
    db.add(new)
    flush(db, "invalid_purchase_order")
    for r in items_of(db, old.id):
        db.add(PurchaseOrderItem(purchase_order_id=new.id, **{k: getattr(r, k) for k in (
            "line_item_id", "sales_order_item_id", "offer_item_id", "position", "description", "quantity", "unit",
            "unit_price", "total")}))
    flush(db, "invalid_purchase_order_item")
    _totals(db, new)
    for ms in milestones.milestones_of(db, purchase_order_id=old.id):
        ms.purchase_order_id = new.id
    flush(db, "invalid_purchase_order")
    cancelled = followups.cancel(db, f"purchase order revised as {new.number}", source, actor, ref_id=old.id)
    events.record(db, "purchase_order", old.id, "superseded", jsonable({"by": new.id, "number": new.number,
                                                                       "old_status": previous,
                                                                       "cancelled_followups": cancelled}), source, actor=actor)
    events.record(db, "purchase_order", new.id, "create", jsonable({"number": new.number, "supersedes_id": old.id,
                                                                   "total": new.total}), source, actor=actor)
    return new


def cancel(db: Session, po_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> PurchaseOrder:
    po = get_purchase_order(db, po_id)
    if po.status in LOCKED + ("received",):
        raise Conflict("purchase_order_locked", f"A {po.status} purchase order cannot be cancelled", {"status": po.status})
    reason = reason_required(reason)
    old = po.status
    po.status, po.cancel_reason = "cancelled", reason
    flush(db, "invalid_purchase_order")
    milestones.cancel_open_of_order(db, po.id, reason, source, actor)
    cancelled = followups.cancel(db, f"purchase order cancelled: {reason}"[:200], source, actor, ref_id=po.id)
    events.record(db, "purchase_order", po.id, "cancel", jsonable({"old_status": old, "reason": reason,
                                                                  "cancelled_followups": cancelled}), source, actor=actor)
    return po


def delete_order(db: Session, po_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Drafts only; an approved or sent purchase order is cancelled instead."""
    po = get_purchase_order(db, po_id)
    _draft(po)
    if db.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.supersedes_id == po.id)):
        raise Conflict("in_use", "A newer version refers to this purchase order")
    if milestones.milestones_of(db, purchase_order_id=po.id):
        raise Conflict("in_use", "Payment milestones refer to this purchase order; delete or move them first")
    snapshot = {"order": row_snapshot(po), "items": [row_snapshot(r) for r in items_of(db, po.id)]}
    for row in items_of(db, po.id):
        db.delete(row)
    db.flush()
    db.delete(po)
    flush(db, "in_use")
    events.record(db, "purchase_order", po_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


_process_hooks: list = []


def register_process_hook(fn) -> None:
    """``fn(db, po, code, source, actor)`` on PO events that match checklist steps (po_sent, goods_ready)."""
    if fn not in _process_hooks:
        _process_hooks.append(fn)


def _process_hint(db: Session, po: PurchaseOrder, code: str, source: str, actor: str | None) -> None:
    """Tell the process checklist that a step-like event happened (domestic: PO sent, goods ready)."""
    from app.core.modules import load_hooks

    load_hooks()
    for fn in _process_hooks:
        fn(db, po, code, source, actor)


def po_out(db: Session, po: PurchaseOrder) -> dict:
    supplier = parties.get_party(db, po.supplier_party_id)
    offer = sourcing_offers.get_offer(db, po.offer_id) if po.offer_id else None
    return jsonable({
        **row_snapshot(po), "supplier": {"id": supplier.id, "name_fa": supplier.name_fa, "name_en": supplier.name_en},
        "items": [row_snapshot(r) for r in items_of(db, po.id)],
        "changes": [row_snapshot(c) for c in changes_of(db, po.id)],
        "offer_payment_terms": offer.payment_terms if offer else None,
        "above_cost_sheet": above_cost_sheet(db, po) if po.status == "draft" else [],
        "milestones": [milestones.milestone_out(db, x) for x in milestones.milestones_of(db, purchase_order_id=po.id)],
        "followups": [{"id": f.id, "purpose": link.purpose, "due_on": f.due_on, "action": f.action}
                      for link, f in followups.links(db, ref_id=po.id)],
        "outputs": parties.linked_documents(db, "purchase_order", [str(po.id)]),
    })


__all__ = ["approve", "cancel", "change_ready_date", "confirm", "create_from_sales_order", "date", "datetime",
           "delete_order", "items_of", "mark_sent", "orders_of", "po_out", "remove_item", "revise", "set_status",
           "update_item", "update_order"]
