"""Supplier invoices (v0.8.0), matched against the purchase order and its receipts.

Per line: ordered / received / invoiced (all supplier invoices of the PO that are not cancelled) and the price
difference against the PO. Approving with differences needs a reason (409 ``invoice_differences`` lists them). A
disputed invoice can link to a claim of the case. Service providers (forwarder, broker, insurer) invoice through
actual costs; a supplier invoice may also be recorded without a PO. Approved invoices are never deleted one by one.
"""
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.finance.common import ZERO, get, money, reason_required, round_to
from app.modules.finance.models import PaymentAllocation, PurchaseInvoice, PurchaseInvoiceLine
from app.modules.parties import clock
from app.modules.parties import service as parties
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings

EDITABLE = ("supplier_invoice_no", "invoice_date", "due_date", "vat_amount", "document_id", "notes")


def get_invoice(db: Session, invoice_id: uuid.UUID) -> PurchaseInvoice:
    return get(db, PurchaseInvoice, invoice_id, "Supplier invoice")


def lines_of(db: Session, invoice_id: uuid.UUID) -> list[PurchaseInvoiceLine]:
    return list(db.scalars(select(PurchaseInvoiceLine).where(PurchaseInvoiceLine.purchase_invoice_id == invoice_id)
                           .order_by(PurchaseInvoiceLine.position)))


def invoices_of(db: Session, *, case_id=None, purchase_order_id=None, supplier_id=None) -> list[PurchaseInvoice]:
    query = select(PurchaseInvoice)
    if case_id:
        query = query.where(PurchaseInvoice.case_id == case_id)
    if purchase_order_id:
        query = query.where(PurchaseInvoice.purchase_order_id == purchase_order_id)
    if supplier_id:
        query = query.where(PurchaseInvoice.supplier_party_id == supplier_id)
    return list(db.scalars(query.order_by(PurchaseInvoice.invoice_date, PurchaseInvoice.created_at)))


def invoiced_quantities(db: Session, purchase_order_id: uuid.UUID, exclude: uuid.UUID | None = None) -> dict:
    query = (select(PurchaseInvoiceLine.purchase_order_item_id, func.sum(PurchaseInvoiceLine.quantity))
             .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
             .where(PurchaseInvoice.purchase_order_id == purchase_order_id, PurchaseInvoice.status != "cancelled",
                    PurchaseInvoiceLine.purchase_order_item_id.is_not(None)))
    if exclude is not None:
        query = query.where(PurchaseInvoice.id != exclude)
    return dict(db.execute(query.group_by(PurchaseInvoiceLine.purchase_order_item_id)).all())


def received_not_invoiced(db: Session, purchase_order_id: uuid.UUID) -> list[dict]:
    """PO items with received goods not covered by a supplier invoice yet."""
    from app.modules.execution.purchase_orders import items_of

    invoiced = invoiced_quantities(db, purchase_order_id)
    return [{"item": r, "quantity": r.received_quantity - invoiced.get(r.id, ZERO)} for r in items_of(db, purchase_order_id)
            if r.received_quantity - invoiced.get(r.id, ZERO) > 0]


def _recompute(db: Session, inv: PurchaseInvoice) -> None:
    inv.subtotal = money(sum((r.total for r in lines_of(db, inv.id)), ZERO))
    inv.total = money(inv.subtotal + (inv.vat_amount or ZERO))
    flush(db, "invalid_purchase_invoice")


def _write_lines(db: Session, inv: PurchaseInvoice, lines: list[dict]) -> None:
    po_items = {}
    if inv.purchase_order_id:
        from app.modules.execution.purchase_orders import items_of

        po_items = {r.id: r for r in items_of(db, inv.purchase_order_id)}
    for row in lines_of(db, inv.id):
        db.delete(row)
    db.flush()
    for position, line in enumerate(lines, start=1):
        item_id = line.get("purchase_order_item_id")
        item = po_items.get(item_id) if item_id else None
        if item_id and item is None:
            raise AppError("item_not_of_order", "A line is not an item of this purchase order",
                           {"purchase_order_item_id": str(item_id)}, status=422)
        description = (line.get("description") or (item.description if item else "") or "").strip()
        if not description:
            raise AppError("description_required", "A line needs a description", status=422)
        unit_price = line.get("unit_price")
        if unit_price is None:
            if item is None:
                raise AppError("unit_price_required", "A line needs a unit price", status=422)
            unit_price = item.unit_price
        db.add(PurchaseInvoiceLine(purchase_invoice_id=inv.id, purchase_order_item_id=item.id if item else None,
                                   position=position, description=description[:500], quantity=line["quantity"],
                                   unit_price=unit_price, total=round_to(db, line["quantity"] * unit_price, inv.currency)))
    flush(db, "invalid_purchase_invoice_line")
    _recompute(db, inv)


def create(db: Session, data: dict, source: str, actor: str | None = None) -> PurchaseInvoice:
    """From a PO (supplier, currency and case from it; lines default to received but not yet invoiced) or without
    one (``case_id``, ``supplier_party_id``, ``currency`` and lines required)."""
    from app.modules.sourcing import inquiries as sourcing

    po = None
    if data.get("purchase_order_id"):
        from app.modules.execution.common import get_purchase_order

        po = get_purchase_order(db, data["purchase_order_id"])
        if po.status in ("draft", "cancelled", "superseded"):
            raise Conflict("purchase_order_not_open", f"The purchase order is {po.status}", {"status": po.status})
    case_id = po.case_id if po else data.get("case_id")
    if case_id is None:
        raise AppError("case_required", "A supplier invoice belongs to a case", status=422)
    if po and data.get("case_id") and data["case_id"] != po.case_id:
        raise AppError("link_not_of_case", "The purchase order belongs to another case", status=422)
    sourcing.get_case(db, case_id)
    supplier = data.get("supplier_party_id") or (po.supplier_party_id if po else None)
    if supplier is None:
        raise AppError("supplier_required", "Who sent the invoice?", status=422)
    parties.get_party(db, supplier)
    currency = data.get("currency") or (po.currency if po else None)
    if not currency:
        raise AppError("currency_required", "An invoice needs a currency", status=422)
    lines = data.get("lines")
    if lines is None and po is not None:
        lines = [{"purchase_order_item_id": r["item"].id, "quantity": r["quantity"]} for r in received_not_invoiced(db, po.id)]
    if not lines:
        raise AppError("no_lines", "A supplier invoice needs at least one line", status=422)
    no = reason_required(data.get("supplier_invoice_no"), "supplier_invoice_no_required", "The supplier's invoice number is required")
    days = int(settings.get(db, "finance.supplier_payment_days") or 0)
    inv = PurchaseInvoice(case_id=case_id, purchase_order_id=po.id if po else None, supplier_party_id=supplier,
                          supplier_invoice_no=no, invoice_date=data["invoice_date"],
                          due_date=data.get("due_date") or data["invoice_date"] + timedelta(days=days), currency=currency,
                          vat_amount=data.get("vat_amount") or ZERO, status="received", document_id=data.get("document_id"),
                          notes=data.get("notes"))
    if inv.due_date < inv.invoice_date:
        raise AppError("due_before_issue", "The due date is before the invoice date", status=422)
    db.add(inv)
    flush(db, "purchase_invoice_exists")
    _write_lines(db, inv, lines)
    events.record(db, "purchase_invoice", inv.id, "create", jsonable({
        "supplier_invoice_no": inv.supplier_invoice_no, "purchase_order_id": inv.purchase_order_id, "total": inv.total,
        "currency": inv.currency, "lines": len(lines)}), source, actor=actor)
    return inv


def _editable(inv: PurchaseInvoice) -> None:
    if inv.status not in ("received", "disputed"):
        raise Conflict("invoice_locked", f"The supplier invoice is {inv.status}", {"status": inv.status})


def update(db: Session, invoice_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> PurchaseInvoice:
    inv = get_invoice(db, invoice_id)
    _editable(inv)
    lines = changes.pop("lines", None)
    changed = diff(inv, {k: v for k, v in changes.items() if k in EDITABLE})
    if inv.due_date and inv.due_date < inv.invoice_date:
        raise AppError("due_before_issue", "The due date is before the invoice date", status=422)
    flush(db, "purchase_invoice_exists")
    if lines is not None:
        if not lines:
            raise AppError("no_lines", "A supplier invoice needs at least one line", status=422)
        _write_lines(db, inv, lines)
        changed["lines"] = len(lines)
    else:
        _recompute(db, inv)
    if changed:
        events.record(db, "purchase_invoice", inv.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return inv


def allocated(db: Session, invoice_id: uuid.UUID) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(PaymentAllocation.target_amount), 0))
                     .where(PaymentAllocation.purchase_invoice_id == invoice_id)) or ZERO


def balance_due(db: Session, inv: PurchaseInvoice) -> Decimal:
    return ZERO if inv.status == "cancelled" else money(inv.total - allocated(db, inv.id))


def payment_status(db: Session, inv: PurchaseInvoice) -> str:
    if inv.status == "cancelled":
        return "none"
    due, paid = balance_due(db, inv), allocated(db, inv.id)
    return "overpaid" if due < 0 else "paid" if due == 0 else "partly_paid" if paid > 0 else "unpaid"


# ---- matching -------------------------------------------------------------------------------------------------------------

def matching(db: Session, inv: PurchaseInvoice) -> dict:
    """Per PO item: ordered, received, invoiced (all invoices), on this invoice, PO price, invoice price and the
    differences; lines without a PO item are listed as ``unmatched``."""
    lines = lines_of(db, inv.id)
    if inv.purchase_order_id is None:
        return {"rows": [], "unmatched": [row_snapshot(r) for r in lines], "differences": []}
    from app.modules.execution.purchase_orders import items_of

    invoiced = invoiced_quantities(db, inv.purchase_order_id)
    mine: dict = {}
    for r in lines:
        if r.purchase_order_item_id:
            mine.setdefault(r.purchase_order_item_id, []).append(r)
    rows, differences = [], []
    for item in items_of(db, inv.purchase_order_id):
        own = mine.get(item.id, [])
        qty = sum((r.quantity for r in own), ZERO)
        price = own[0].unit_price if own else None
        row = {"purchase_order_item_id": item.id, "description": item.description, "ordered": item.quantity,
               "received": item.received_quantity, "invoiced": invoiced.get(item.id, ZERO), "this_invoice": qty,
               "po_price": item.unit_price, "invoice_price": price,
               "price_difference": (price - item.unit_price) if price is not None else None, "flags": []}
        if own:
            if row["invoiced"] > item.received_quantity:
                row["flags"].append("invoiced_above_received")
            if row["invoiced"] > item.quantity:
                row["flags"].append("invoiced_above_ordered")
            if price != item.unit_price:
                row["flags"].append("price_difference")
        if row["flags"]:
            differences.append({"purchase_order_item_id": str(item.id), "description": item.description, "flags": row["flags"]})
        rows.append(row)
    unmatched = [row_snapshot(r) for r in lines if r.purchase_order_item_id is None]
    if unmatched:
        differences.append({"flags": ["lines_without_po_item"], "count": len(unmatched)})
    return jsonable({"rows": rows, "unmatched": unmatched, "differences": differences})


# ---- status --------------------------------------------------------------------------------------------------------------

def approve(db: Session, invoice_id: uuid.UUID, reason: str | None, source: str, actor: str | None = None) -> PurchaseInvoice:
    inv = get_invoice(db, invoice_id)
    _editable(inv)
    found = matching(db, inv)["differences"]
    text = (reason or "").strip() or None
    if found and not text:
        raise Conflict("invoice_differences", "The invoice differs from the purchase order or the receipts; approving "
                       "needs a reason", {"differences": found})
    inv.status, inv.approved_at, inv.difference_reason = "approved", clock.now(), text if found else None
    flush(db, "invalid_purchase_invoice")
    events.record(db, "purchase_invoice", inv.id, "approve", jsonable({"differences": found, "reason": inv.difference_reason,
                                                                        "total": inv.total}), source, actor=actor)
    return inv


def dispute(db: Session, invoice_id: uuid.UUID, reason: str, claim_id: uuid.UUID | None, source: str,
            actor: str | None = None) -> PurchaseInvoice:
    inv = get_invoice(db, invoice_id)
    if inv.status not in ("received", "disputed"):
        raise Conflict("invoice_locked", f"The supplier invoice is {inv.status}", {"status": inv.status})
    reason = reason_required(reason)
    if claim_id:
        from app.modules.execution.claims import get_claim

        if get_claim(db, claim_id).case_id != inv.case_id:
            raise AppError("link_not_of_case", "The claim belongs to another case", status=422)
    inv.status, inv.dispute_reason, inv.claim_id = "disputed", reason, claim_id
    flush(db, "invalid_purchase_invoice")
    events.record(db, "purchase_invoice", inv.id, "dispute", jsonable({"reason": reason, "claim_id": claim_id}), source, actor=actor)
    return inv


def cancel(db: Session, invoice_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> PurchaseInvoice:
    inv = get_invoice(db, invoice_id)
    if inv.status == "cancelled":
        raise Conflict("invoice_cancelled", "The supplier invoice is already cancelled")
    reason = reason_required(reason)
    if allocated(db, inv.id) > 0:
        raise Conflict("invoice_has_payments", "Payments are allocated to this invoice; remove them first")
    inv.status, inv.cancel_reason = "cancelled", reason
    flush(db, "invalid_purchase_invoice")
    events.record(db, "purchase_invoice", inv.id, "cancel", {"reason": reason}, source, actor=actor)
    return inv


def delete(db: Session, invoice_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    inv = get_invoice(db, invoice_id)
    if inv.status == "approved":
        raise Conflict("invoice_locked", "An approved supplier invoice is never deleted; cancel it", {"status": inv.status})
    if allocated(db, inv.id) > 0:
        raise Conflict("invoice_has_payments", "Payments are allocated to this invoice; remove them first")
    snapshot = {**row_snapshot(inv), "lines": [row_snapshot(r) for r in lines_of(db, inv.id)]}
    for row in lines_of(db, inv.id):
        db.delete(row)
    db.flush()
    db.delete(inv)
    flush(db, "in_use")
    events.record(db, "purchase_invoice", invoice_id, "delete", jsonable(snapshot), source, actor=actor)


def invoice_out(db: Session, inv: PurchaseInvoice) -> dict:
    p = parties.get_party(db, inv.supplier_party_id)
    po_number = None
    if inv.purchase_order_id:
        from app.modules.execution.common import get_purchase_order

        po_number = get_purchase_order(db, inv.purchase_order_id).number
    return jsonable({**row_snapshot(inv), "lines": [row_snapshot(r) for r in lines_of(db, inv.id)],
                     "supplier": {"id": p.id, "name_fa": p.name_fa, "name_en": p.name_en}, "purchase_order_number": po_number,
                     "matching": matching(db, inv), "allocated": allocated(db, inv.id), "balance_due": balance_due(db, inv),
                     "payment_status": payment_status(db, inv)})
