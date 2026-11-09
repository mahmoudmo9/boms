"""Sales invoices (v0.8.0): issued by BOMS from a sales order's deliveries.

- ``language`` fa is the domestic invoice («صورتحساب فروش کالا و خدمات»), en the export commercial invoice.
- Lines default to the delivered but not yet invoiced quantities; more than delivered needs a reason (event), more
  than ordered is refused (422 ``over_ordered``). Several invoices per order; «invoice the rest» is one call.
- A draft has no number. Issuing assigns ``INV-<year>-<seq>`` (credit notes ``CN-``, debit notes ``DN-``; the user's
  calendar year, gap-free), locks the invoice and sets the Moadian status: a fa invoice to an Iranian customer is
  ``not_sent``, the others ``not_required``. Issuing needs the seller's IDs and, on a domestic invoice, the buyer's
  (422 ``issue_requirements_missing`` lists them).
- Issued invoices are never edited or deleted: corrections are credit / debit notes; cancelling (a reason, only while
  no payment is allocated) keeps the number used.
- VAT: the percent of the tax parameter ``vat`` in force on the issue date (deal type of the case's sheet) on a
  domestic invoice, 0 on an export one; editable on the draft with a note.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.finance.common import ZERO, get, money, reason_required, round_to, today
from app.modules.finance.models import PaymentAllocation, SalesInvoice, SalesInvoiceLine
from app.modules.parties import clock
from app.modules.parties import service as parties
from app.modules.quotes.numbering import numbering_year
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings

PREFIX = {"invoice": "INV", "credit_note": "CN", "debit_note": "DN"}
OPEN_ORDER = ("confirmed", "in_progress", "delivered", "closed")
EDITABLE = ("issue_date", "due_date", "language", "discount", "vat_rate", "vat_note", "incoterm", "incoterm_place", "incoterm_place_location_id",
            "country_of_origin", "shipping_marks", "gross_weight", "net_weight", "packages", "transport_doc_no",
            "shipment_id", "notes")


def get_invoice(db: Session, invoice_id: uuid.UUID) -> SalesInvoice:
    return get(db, SalesInvoice, invoice_id, "Sales invoice")


def lines_of(db: Session, invoice_id: uuid.UUID) -> list[SalesInvoiceLine]:
    return list(db.scalars(select(SalesInvoiceLine).where(SalesInvoiceLine.sales_invoice_id == invoice_id)
                           .order_by(SalesInvoiceLine.position)))


def invoices_of(db: Session, *, case_id=None, sales_order_id=None, customer_id=None) -> list[SalesInvoice]:
    query = select(SalesInvoice)
    if case_id:
        query = query.where(SalesInvoice.case_id == case_id)
    if sales_order_id:
        query = query.where(SalesInvoice.sales_order_id == sales_order_id)
    if customer_id:
        query = query.where(SalesInvoice.customer_party_id == customer_id)
    return list(db.scalars(query.order_by(SalesInvoice.created_at)))


def next_number(db: Session, kind: str, year: int) -> str:
    """v0.9.0: through the codes service (``codes.pattern.sales_invoice`` / ``credit_note`` / ``debit_note``); the
    old ``ops.invoice_sequence`` was carried over into ``core.code_sequence`` by migration 0018."""
    from app.modules.codes import service as codes

    return codes.next(db, "sales_invoice" if kind == "invoice" else kind, {"yyyy": year}, table="ops.sales_invoice",
                      column="number")


# ---- quantities --------------------------------------------------------------------------------------------------------

def invoiced_quantities(db: Session, sales_order_id: uuid.UUID, exclude: uuid.UUID | None = None) -> dict:
    """Per sales order item: the quantity on invoices (draft or issued, not notes, not cancelled)."""
    query = (select(SalesInvoiceLine.sales_order_item_id, func.sum(SalesInvoiceLine.quantity))
             .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.sales_invoice_id)
             .where(SalesInvoice.sales_order_id == sales_order_id, SalesInvoice.kind == "invoice",
                    SalesInvoice.status != "cancelled", SalesInvoiceLine.sales_order_item_id.is_not(None)))
    if exclude is not None:
        query = query.where(SalesInvoice.id != exclude)
    return dict(db.execute(query.group_by(SalesInvoiceLine.sales_order_item_id)).all())


def order_invoicing(db: Session, sales_order_id: uuid.UUID, exclude: uuid.UUID | None = None) -> list[dict]:
    """Ordered, delivered, invoiced and still to invoice (delivered minus invoiced) per sales order item."""
    from app.modules.execution import sales_orders

    delivered = sales_orders.delivered_quantities(db, sales_order_id)
    invoiced = invoiced_quantities(db, sales_order_id, exclude)
    out = []
    for item in sales_orders.items_of(db, sales_order_id):
        d, i = delivered.get(item.id, ZERO), invoiced.get(item.id, ZERO)
        out.append({"item": item, "ordered": item.quantity, "delivered": d, "invoiced": i,
                    "to_invoice": max(ZERO, d - i), "not_invoiced_ordered": max(ZERO, item.quantity - i)})
    return out


def delivered_not_invoiced(db: Session, sales_order_id: uuid.UUID) -> Decimal:
    return sum((r["to_invoice"] for r in order_invoicing(db, sales_order_id)), ZERO)


# ---- defaults ------------------------------------------------------------------------------------------------------------

def _hs_code(db: Session, line_item_id) -> str | None:
    from app.modules.catalog.models import Product
    from app.modules.sourcing.models import LineItem

    item = db.get(LineItem, line_item_id) if line_item_id else None
    if item is None or item.product_id is None:
        return None
    product = db.get(Product, item.product_id)
    return product.hs_code if product else None


def _domestic(db: Session, customer_id, language: str) -> bool:
    p = parties.get_party(db, customer_id)
    return language == "fa" and (p.country_iso2 or "IR") == "IR"


def parameter_vat_rate(db: Session, case_id, on: date) -> Decimal | None:
    """The ``vat`` tax parameter in force on ``on`` for the deal type of the case's sheet (None when there is none)."""
    from app.modules.costing import service as costing

    sheet = costing.current_sheet(db, case_id)
    param = costing.parameter_in_force(db, "vat", sheet.deal_type if sheet is not None else "domestic", on)
    return param.rate_percent if param is not None else None


def default_vat_rate(db: Session, case_id, customer_id, language: str, on: date) -> Decimal:
    if not _domestic(db, customer_id, language):
        return ZERO
    decision = settings.get(db, "finance.vat_default_domestic")
    if decision and decision.get("mode") == "zero":     # v0.9.0: the owner's decision is the default
        return ZERO
    from app.modules.costing import service as costing

    sheet = costing.current_sheet(db, case_id)
    deal_type = sheet.deal_type if sheet is not None else "domestic"
    param = costing.parameter_in_force(db, "vat", deal_type, on)
    return param.rate_percent if param is not None else ZERO


def _language_for(db: Session, customer_id) -> str:
    p = parties.get_party(db, customer_id)
    return "fa" if (p.country_iso2 or "IR") == "IR" else "en"


def _shipment_of(db: Session, order) -> object | None:
    from app.modules.execution.models import Shipment

    return db.scalar(select(Shipment).where(Shipment.sales_order_id == order.id, Shipment.status != "cancelled")
                     .order_by(Shipment.created_at.desc()).limit(1))


# ---- lines and totals -------------------------------------------------------------------------------------------------------

def _line_total(db: Session, inv: SalesInvoice, quantity: Decimal, unit_price: Decimal, discount: Decimal) -> Decimal:
    total = round_to(db, quantity * unit_price - discount, inv.currency)
    if total < 0:
        raise AppError("discount_too_large", "A line discount is larger than the line amount", status=422)
    return total


def recompute(db: Session, inv: SalesInvoice) -> None:
    rows = lines_of(db, inv.id)
    inv.subtotal = money(sum((r.total for r in rows), ZERO))
    base = inv.subtotal - (inv.discount or ZERO)
    if base < 0:
        raise AppError("discount_too_large", "The discount is larger than the subtotal", status=422)
    inv.vat_amount = round_to(db, base * (inv.vat_rate or ZERO) / Decimal(100), inv.currency)
    inv.total = money(base + inv.vat_amount)
    flush(db, "invalid_sales_invoice")


def _check_quantities(db: Session, inv: SalesInvoice, lines: list[dict], reason: str | None) -> str | None:
    """More than ordered: 422; more than delivered: needs a reason (returned to store)."""
    if inv.kind != "invoice":
        return None
    state = {r["item"].id: r for r in order_invoicing(db, inv.sales_order_id, exclude=inv.id)}
    over_delivered = []
    wanted: dict = {}
    for line in lines:
        if line.get("sales_order_item_id"):
            wanted[line["sales_order_item_id"]] = wanted.get(line["sales_order_item_id"], ZERO) + line["quantity"]
    for item_id, qty in wanted.items():
        row = state.get(item_id)
        if row is None:
            raise AppError("item_not_of_order", "A line is not an item of this sales order", {"sales_order_item_id": str(item_id)},
                           status=422)
        if row["invoiced"] + qty > row["ordered"]:
            raise AppError("over_ordered", "More than ordered cannot be invoiced",
                           {"sales_order_item_id": str(item_id), "ordered": str(row["ordered"]),
                            "invoiced": str(row["invoiced"]), "quantity": str(qty)}, status=422)
        if row["invoiced"] + qty > row["delivered"]:
            over_delivered.append({"sales_order_item_id": str(item_id), "delivered": str(row["delivered"]),
                                   "invoiced": str(row["invoiced"]), "quantity": str(qty)})
    if over_delivered:
        text_reason = (reason or "").strip()
        if not text_reason:
            raise AppError("over_delivered_reason_required", "Invoicing more than delivered needs a reason",
                           {"items": over_delivered}, status=422)
        return text_reason
    return None


def _write_lines(db: Session, inv: SalesInvoice, lines: list[dict]) -> None:
    from app.modules.execution.sales_orders import items_of

    items = {r.id: r for r in items_of(db, inv.sales_order_id)}
    for row in lines_of(db, inv.id):
        db.delete(row)
    db.flush()
    for position, line in enumerate(lines, start=1):
        item = items.get(line.get("sales_order_item_id")) if line.get("sales_order_item_id") else None
        description = (line.get("description") or (item.description if item else "") or "").strip()
        if not description:
            raise AppError("description_required", "A line needs a description", status=422)
        unit_price = line.get("unit_price")
        if unit_price is None:
            if item is None:
                raise AppError("unit_price_required", "A line needs a unit price", status=422)
            unit_price = item.unit_price
        discount = line.get("discount") or ZERO
        db.add(SalesInvoiceLine(
            sales_invoice_id=inv.id, sales_order_item_id=item.id if item else None, position=position,
            description=description[:500], quantity=line["quantity"], unit=line.get("unit") or (item.unit if item else None),
            unit_price=unit_price, discount=discount, total=_line_total(db, inv, line["quantity"], unit_price, discount),
            hs_code=line.get("hs_code") or (_hs_code(db, item.line_item_id) if item else None)))
    flush(db, "invalid_sales_invoice_line")
    recompute(db, inv)


# ---- create / edit ------------------------------------------------------------------------------------------------------------

def create_from_order(db: Session, sales_order_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> SalesInvoice:
    """A draft invoice; ``lines`` omitted = every delivered but not yet invoiced quantity («invoice the rest»)."""
    from app.modules.execution.common import get_sales_order

    order = get_sales_order(db, sales_order_id)
    if order.status not in OPEN_ORDER:
        raise Conflict("sales_order_not_open", f"The sales order is {order.status}", {"status": order.status})
    lines = data.get("lines")
    if lines is None:
        lines = [{"sales_order_item_id": r["item"].id, "quantity": r["to_invoice"]}
                 for r in order_invoicing(db, order.id) if r["to_invoice"] > 0]
    if not lines:
        raise AppError("nothing_to_invoice", "Nothing delivered is left to invoice", status=422)
    language = data.get("language") or _language_for(db, order.customer_party_id)
    shipment = _shipment_of(db, order)
    inv = SalesInvoice(
        case_id=order.case_id, sales_order_id=order.id, kind="invoice", language=language,
        customer_party_id=order.customer_party_id, currency=order.currency, price_basis=order.price_basis,
        status="draft", moadian_status="not_required", discount=data.get("discount") or ZERO,
        vat_rate=default_vat_rate(db, order.case_id, order.customer_party_id, language, data.get("issue_date") or today()),
        issue_date=data.get("issue_date"), due_date=data.get("due_date"),
        incoterm=data.get("incoterm") or order.incoterm, incoterm_place=data.get("incoterm_place") or order.incoterm_place,
        country_of_origin=data.get("country_of_origin"), shipping_marks=data.get("shipping_marks"),
        gross_weight=data.get("gross_weight"), net_weight=data.get("net_weight"), packages=data.get("packages"),
        transport_doc_no=data.get("transport_doc_no") or (shipment.transport_doc_no if shipment else None),
        shipment_id=data.get("shipment_id") or (shipment.id if shipment else None), notes=data.get("notes"))
    db.add(inv)
    flush(db, "invalid_sales_invoice")
    inv.over_delivered_reason = _check_quantities(db, inv, lines, data.get("over_delivered_reason"))
    _write_lines(db, inv, lines)
    events.record(db, "sales_invoice", inv.id, "create", jsonable({
        "sales_order_id": order.id, "kind": inv.kind, "language": inv.language, "total": inv.total,
        "currency": inv.currency, "lines": len(lines), "over_delivered_reason": inv.over_delivered_reason}),
        source, actor=actor)
    return inv


def _draft(inv: SalesInvoice) -> None:
    if inv.status != "draft":
        raise Conflict("invoice_locked", f"The invoice is {inv.status}; correct it with a credit or debit note",
                       {"status": inv.status})


def update_draft(db: Session, invoice_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> SalesInvoice:
    inv = get_invoice(db, invoice_id)
    _draft(inv)
    lines = changes.pop("lines", None)
    reason = changes.pop("over_delivered_reason", None)
    if "vat_rate" in changes and changes["vat_rate"] is not None:
        default = default_vat_rate(db, inv.case_id, inv.customer_party_id, changes.get("language", inv.language),
                                   changes.get("issue_date") or inv.issue_date or today())
        if Decimal(changes["vat_rate"]) != default and not (changes.get("vat_note") or inv.vat_note or "").strip():
            raise AppError("vat_note_required", "A VAT percent other than the tax parameter needs a note",
                           {"default_vat_rate": str(default)}, status=422)
    if "language" in changes and changes["language"] and changes["language"] != inv.language and "vat_rate" not in changes:
        changes["vat_rate"] = default_vat_rate(db, inv.case_id, inv.customer_party_id, changes["language"],
                                               changes.get("issue_date") or inv.issue_date or today())
    changed = diff(inv, {k: v for k, v in changes.items() if k in EDITABLE})
    flush(db, "invalid_sales_invoice")
    if lines is not None:
        if not lines:
            raise AppError("no_lines", "An invoice needs at least one line", status=422)
        inv.over_delivered_reason = _check_quantities(db, inv, lines, reason or inv.over_delivered_reason)
        _write_lines(db, inv, lines)
        changed["lines"] = len(lines)
    else:
        recompute(db, inv)
    if changed:
        events.record(db, "sales_invoice", inv.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return inv


def delete_draft(db: Session, invoice_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    inv = get_invoice(db, invoice_id)
    if inv.status != "draft":
        raise Conflict("invoice_locked", "An issued invoice is never deleted; cancel it or correct it with a note",
                       {"status": inv.status})
    snapshot = {**row_snapshot(inv), "lines": [row_snapshot(r) for r in lines_of(db, inv.id)]}
    for row in lines_of(db, inv.id):
        db.delete(row)
    db.flush()
    db.delete(inv)
    flush(db, "in_use")
    events.record(db, "sales_invoice", invoice_id, "delete", jsonable(snapshot), source, actor=actor)


# ---- issue / cancel -------------------------------------------------------------------------------------------------------------

def issue_requirements(db: Session, inv: SalesInvoice) -> list[str]:
    missing = [key for key in ("company.national_id", "company.economic_code") if not (settings.get(db, key) or "").strip()]
    if not ((settings.get(db, "company.name_fa") or settings.get(db, "company.name_en") or settings.get(db, "company.name") or "").strip()):
        missing.insert(0, "company.name")
    if _domestic(db, inv.customer_party_id, inv.language):
        p = parties.get_party(db, inv.customer_party_id)
        if not (p.national_id or "").strip():
            missing.append("customer.national_id")
        if p.kind != "person" and not (p.economic_code or "").strip():
            missing.append("customer.economic_code")
    return missing


def issue(db: Session, invoice_id: uuid.UUID, data: dict, calendar: str, source: str, actor: str | None = None) -> SalesInvoice:
    inv = get_invoice(db, invoice_id)
    _draft(inv)
    rows = lines_of(db, inv.id)
    if not rows:
        raise AppError("no_lines", "An invoice needs at least one line", status=422)
    missing = issue_requirements(db, inv)
    if missing:
        raise AppError("issue_requirements_missing", "Fill in the seller's and buyer's IDs before issuing",
                       {"missing": missing}, status=422)
    _check_quantities(db, inv, [{"sales_order_item_id": r.sales_order_item_id, "quantity": r.quantity} for r in rows],
                      inv.over_delivered_reason)
    inv.issue_date = data.get("issue_date") or inv.issue_date or today()
    _vat_decision(db, inv, data, source, actor)
    if inv.due_date is None:
        inv.due_date = inv.issue_date + timedelta(days=int(settings.get(db, "finance.payment_days") or 0))
    if inv.due_date < inv.issue_date:
        raise AppError("due_before_issue", "The due date is before the issue date", status=422)
    inv.number = next_number(db, inv.kind, numbering_year(inv.issue_date, calendar))
    inv.status, inv.issued_at = "issued", clock.now()
    inv.moadian_status = "not_sent" if _domestic(db, inv.customer_party_id, inv.language) else "not_required"
    flush(db, "invalid_sales_invoice")
    events.record(db, "sales_invoice", inv.id, "issue", jsonable({
        "number": inv.number, "kind": inv.kind, "issue_date": inv.issue_date, "due_date": inv.due_date, "total": inv.total,
        "currency": inv.currency, "vat_rate": inv.vat_rate, "moadian_status": inv.moadian_status}), source, actor=actor)
    return inv


def _vat_decision(db: Session, inv: SalesInvoice, data: dict, source: str, actor: str | None) -> None:
    """v0.9.0: the first domestic invoice asks the owner how VAT is applied (409 ``vat_decision_required`` with the
    rate of the tax parameters in force on the issue date). "apply" uses that rate, "zero" needs a reason; the choice
    becomes the default (``finance.vat_default_domestic``) and each invoice stays editable with a note."""
    if inv.kind != "invoice" or not _domestic(db, inv.customer_party_id, inv.language):
        return
    if settings.get(db, "finance.vat_default_domestic"):
        return
    rate = parameter_vat_rate(db, inv.case_id, inv.issue_date)
    choice = data.get("vat_decision")
    if choice not in ("apply", "zero"):
        raise Conflict("vat_decision_required", "Decide how VAT applies to domestic invoices before the first one is issued",
                       {"rate": str(rate) if rate is not None else None, "issue_date": inv.issue_date.isoformat()})
    if choice == "zero":
        reason = reason_required(data.get("vat_reason"), "vat_reason_required", "A zero VAT rate needs a reason")
        decision = {"mode": "zero", "reason": reason}
        inv.vat_rate, inv.vat_note = ZERO, reason
    else:
        if rate is None:
            raise AppError("vat_parameter_missing", "No VAT tax parameter is in force on the issue date; add it under "
                           "Settings → Costing & tax, or choose a zero rate with a reason", status=422)
        decision = {"mode": "apply"}
        inv.vat_rate = rate
    settings.update(db, {"finance.vat_default_domestic": decision}, source, actor)
    recompute(db, inv)


def allocated(db: Session, invoice_id: uuid.UUID) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(PaymentAllocation.target_amount), 0))
                     .where(PaymentAllocation.sales_invoice_id == invoice_id)) or ZERO


def cancel(db: Session, invoice_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> SalesInvoice:
    inv = get_invoice(db, invoice_id)
    if inv.status != "issued":
        raise Conflict("invoice_not_issued", f"The invoice is {inv.status}", {"status": inv.status})
    reason = reason_required(reason)
    if allocated(db, inv.id) > 0:
        raise Conflict("invoice_has_payments", "Payments are allocated to this invoice; remove them first")
    live_notes = [n.number for n in notes_of(db, inv.id) if n.status == "issued"]
    if live_notes:
        raise Conflict("invoice_has_notes", "Issued credit or debit notes correct this invoice", {"notes": live_notes})
    inv.status, inv.cancel_reason = "cancelled", reason
    flush(db, "invalid_sales_invoice")
    events.record(db, "sales_invoice", inv.id, "cancel", {"number": inv.number, "reason": reason}, source, actor=actor)
    return inv


# ---- credit / debit notes -------------------------------------------------------------------------------------------------------

def notes_of(db: Session, invoice_id: uuid.UUID) -> list[SalesInvoice]:
    return list(db.scalars(select(SalesInvoice).where(SalesInvoice.corrects_invoice_id == invoice_id)
                           .order_by(SalesInvoice.created_at)))


def create_note(db: Session, invoice_id: uuid.UUID, kind: str, data: dict, source: str, actor: str | None = None) -> SalesInvoice:
    """A draft credit or debit note on an issued invoice (same customer, currency, language and VAT percent)."""
    if kind not in ("credit_note", "debit_note"):
        raise AppError("invalid_kind", "A note is a credit_note or a debit_note", status=422)
    base = get_invoice(db, invoice_id)
    if base.kind != "invoice" or base.status != "issued":
        raise Conflict("invoice_not_issued", "Only an issued invoice is corrected by a note", {"status": base.status})
    reason = reason_required(data.get("reason"))
    lines = data.get("lines") or []
    if not lines:
        raise AppError("no_lines", "A note needs at least one line", status=422)
    note = SalesInvoice(case_id=base.case_id, sales_order_id=base.sales_order_id, kind=kind, corrects_invoice_id=base.id,
                        language=base.language, customer_party_id=base.customer_party_id, currency=base.currency,
                        price_basis=base.price_basis, vat_rate=base.vat_rate, status="draft", moadian_status="not_required",
                        notes=reason, issue_date=data.get("issue_date"), due_date=data.get("due_date"))
    db.add(note)
    flush(db, "invalid_sales_invoice")
    _write_lines(db, note, lines)
    if kind == "credit_note":
        creditable = base.total + sum((signed_total(n) for n in notes_of(db, base.id) if n.status == "issued"), ZERO)
        if note.total > creditable:
            raise AppError("credit_above_invoice", "A credit note cannot exceed the invoice (with its notes)",
                           {"creditable": str(creditable)}, status=422)
    events.record(db, "sales_invoice", note.id, "create", jsonable({
        "kind": kind, "corrects": base.number, "total": note.total, "reason": reason}), source, actor=actor)
    events.record(db, "sales_invoice", base.id, "note_created", jsonable({"note_id": note.id, "kind": kind}), source, actor=actor)
    return note


def signed_total(inv: SalesInvoice) -> Decimal:
    """What the invoice adds to the customer's balance: an invoice or debit note +, a credit note −."""
    return -inv.total if inv.kind == "credit_note" else inv.total


def balance_due(db: Session, inv: SalesInvoice) -> Decimal:
    """Invoice total + issued debit notes − issued credit notes − allocations (to the invoice and its notes)."""
    if inv.status != "issued":
        return ZERO
    total = inv.total - allocated(db, inv.id)
    for note in notes_of(db, inv.id):
        if note.status == "issued":
            total += signed_total(note) - (allocated(db, note.id) if note.kind == "debit_note" else ZERO)
    return money(total)


def payment_status(db: Session, inv: SalesInvoice) -> str:
    """unpaid / partly_paid / paid / overpaid (warning), derived; notes and drafts: none."""
    if inv.kind != "invoice" or inv.status != "issued":
        return "none"
    due = balance_due(db, inv)
    paid = allocated(db, inv.id)
    if due < 0:
        return "overpaid"
    if due == 0:
        return "paid"
    return "partly_paid" if paid > 0 else "unpaid"


# ---- Moadian ----------------------------------------------------------------------------------------------------------------------

MOADIAN = ("not_required", "not_sent", "sent", "accepted", "rejected")


def set_moadian(db: Session, invoice_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> SalesInvoice:
    """The owner registers the invoice in سامانه مودیان himself and types the tax ID and status here."""
    inv = get_invoice(db, invoice_id)
    if inv.status != "issued":
        raise Conflict("invoice_not_issued", "Only an issued invoice has a Moadian status", {"status": inv.status})
    status = data.get("moadian_status") or inv.moadian_status
    if status not in MOADIAN:
        raise AppError("invalid_moadian_status", "Unknown Moadian status", status=422)
    tax_id = (data.get("moadian_tax_id") if "moadian_tax_id" in data else inv.moadian_tax_id) or None
    if tax_id:
        tax_id = tax_id.strip()
    if status in ("sent", "accepted") and not tax_id:
        raise AppError("moadian_tax_id_required", "Enter the tax ID («شماره منحصربه‌فرد مالیاتی»)", status=422)
    if status == "rejected" and not (data.get("moadian_note") or inv.moadian_note or "").strip():
        raise AppError("moadian_note_required", "A rejected invoice needs a note", status=422)
    changed = diff(inv, {"moadian_status": status, "moadian_tax_id": tax_id,
                         "moadian_on": data.get("moadian_on") or (today() if status != inv.moadian_status else inv.moadian_on),
                         "moadian_note": data.get("moadian_note", inv.moadian_note)})
    flush(db, "invalid_sales_invoice")
    if changed:
        events.record(db, "sales_invoice", inv.id, "moadian", jsonable({"changes": changed}), source, actor=actor)
    return inv


# ---- output dicts -------------------------------------------------------------------------------------------------------------------

def invoice_out(db: Session, inv: SalesInvoice) -> dict:
    p = parties.get_party(db, inv.customer_party_id)
    base = get_invoice(db, inv.corrects_invoice_id) if inv.corrects_invoice_id else None
    out = {**row_snapshot(inv), "lines": [row_snapshot(r) for r in lines_of(db, inv.id)],
           "customer": {"id": p.id, "name_fa": p.name_fa, "name_en": p.name_en, "country_iso2": p.country_iso2,
                        "national_id": p.national_id, "economic_code": p.economic_code},
           "corrects_number": base.number if base else None,
           "notes_list": [{"id": n.id, "kind": n.kind, "number": n.number, "status": n.status, "total": n.total}
                          for n in notes_of(db, inv.id)],
           "allocated": allocated(db, inv.id), "balance_due": balance_due(db, inv), "payment_status": payment_status(db, inv),
           "missing_for_issue": issue_requirements(db, inv) if inv.status == "draft" else []}
    if inv.status == "draft" and inv.kind == "invoice":
        out["default_vat_rate"] = default_vat_rate(db, inv.case_id, inv.customer_party_id, inv.language,
                                                   inv.issue_date or today())
    return jsonable(out)


def invoicing_out(db: Session, sales_order_id: uuid.UUID) -> list[dict]:
    return jsonable([{"sales_order_item_id": r["item"].id, "description": r["item"].description, "unit": r["item"].unit,
                      "unit_price": r["item"].unit_price, "ordered": r["ordered"], "delivered": r["delivered"],
                      "invoiced": r["invoiced"], "to_invoice": r["to_invoice"]} for r in order_invoicing(db, sales_order_id)])


def on_claim_resolved(db: Session, claim, source: str, actor: str | None) -> None:
    """v0.9.0: a claim from the customer resolved with a discount or a credit note creates a DRAFT credit note on the
    order's latest issued invoice in the claim's currency, linked to the claim, for the owner to review and issue.
    Nothing is created (an event says why) when there is no such invoice or the amount is more than it can credit."""
    if claim.direction != "from_customer" or claim.resolution not in ("discount", "credit_note") or not claim.resolution_amount:
        return
    from app.modules.execution.models import Delivery, SalesOrder

    order_id = None
    if claim.delivery_id:
        delivery = db.get(Delivery, claim.delivery_id)
        order_id = delivery.sales_order_id if delivery else None
    if order_id is None:
        order_id = db.scalar(select(SalesOrder.id).where(SalesOrder.case_id == claim.case_id, SalesOrder.status != "cancelled")
                             .order_by(SalesOrder.created_at).limit(1))
    currency = claim.resolution_amount_currency
    base = None
    if order_id is not None:
        candidates = [i for i in invoices_of(db, sales_order_id=order_id)
                      if i.kind == "invoice" and i.status == "issued" and (currency is None or i.currency == currency)]
        base = candidates[-1] if candidates else None
    if base is None:
        events.record(db, "claim", claim.id, "credit_note_not_created",
                      {"reason": "no issued invoice in the claim's currency"}, source, actor=actor)
        return
    creditable = base.total + sum((signed_total(n) for n in notes_of(db, base.id) if n.status == "issued"), ZERO)
    if claim.resolution_amount > creditable:
        events.record(db, "claim", claim.id, "credit_note_not_created",
                      {"reason": "more than the invoice can credit", "creditable": str(creditable)}, source, actor=actor)
        return
    note = create_note(db, base.id, "credit_note", {
        "reason": f"claim {claim.kind}: {claim.resolution}",
        "lines": [{"description": f"Claim {claim.kind} ({claim.resolution})", "quantity": Decimal(1),
                   "unit_price": claim.resolution_amount}]}, source, actor)
    note.claim_id = claim.id
    flush(db, "invalid_sales_invoice")
    events.record(db, "claim", claim.id, "credit_note_drafted", jsonable({"sales_invoice_id": note.id,
                                                                          "corrects": base.number}), source, actor=actor)
