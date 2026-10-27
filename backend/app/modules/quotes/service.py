"""Quotes / proforma invoices (Phase 6).

Flow: draft (texts, terms and items; prices from the final cost sheet unless set by hand) -> approve (the owner's
final review: gate checked again, numbers locked) -> outputs (PDF / Word from the quote's own rows) -> mark as sent
(outgoing interaction + "Chase quote response" follow-up, optional funnel move to ``quoted``) -> outcome per item
(accepted / rejected / no_reply / negotiating; quote status derived). A sent quote never changes; "revise" makes the
next version and marks this one ``superseded``. Accepted items become ``sold`` through the sourcing status function.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.time import ensure_aware
from app.modules.costing import service as costing
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.parties import interactions as party_interactions
from app.modules.parties import service as parties
from app.modules.quotes.models import OutcomeReason, Quote, QuoteItem
from app.modules.quotes.numbering import next_number, numbering_year
from app.modules.sourcing import coverage as sourcing_coverage
from app.modules.sourcing import inquiries as sourcing_cases
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing import templates as sourcing_templates
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings

EDITABLE = ("language", "price_basis", "valid_until", "incoterm", "incoterm_place", "payment_terms", "delivery_terms",
            "lead_time_days", "terms_text", "notes", "buyer_party_id", "contact_id")
OPEN_STATUSES = ("draft", "approved", "sent")
DECIDED = ("accepted", "partially_accepted", "rejected")
CHASE_ACTION = {"en": "Chase quote response", "fa": "پیگیری پاسخ پیش‌فاکتور"}
INTERACTION_CHANNELS = {"email": "email", "whatsapp": "whatsapp", "phone": "call", "in_person": "in_person",
                        "letter": "other", "other": "other"}


def get_quote(db: Session, quote_id: uuid.UUID) -> Quote:
    row = db.get(Quote, quote_id)
    if row is None:
        raise NotFound("not_found", "Quote not found")
    return row


def items_of(db: Session, quote_id: uuid.UUID) -> list[QuoteItem]:
    return list(db.scalars(select(QuoteItem).where(QuoteItem.quote_id == quote_id).order_by(QuoteItem.position)))


def list_quotes(db: Session, *, case_id: uuid.UUID | None = None, party_id: uuid.UUID | None = None,
                status: str | None = None) -> list[Quote]:
    query = select(Quote).order_by(Quote.created_at.desc())
    if case_id:
        query = query.where(Quote.case_id == case_id)
    if party_id:
        query = query.where(Quote.buyer_party_id == party_id)
    if status:
        query = query.where(Quote.status == status)
    return list(db.scalars(query))


def outcome_reasons(db: Session) -> list[OutcomeReason]:
    return list(db.scalars(select(OutcomeReason).order_by(OutcomeReason.sort_order)))


def _draft(quote: Quote) -> None:
    if quote.status != "draft":
        raise Conflict("quote_locked", f"The quote is {quote.status}; revise it to make changes",
                       {"status": quote.status, "number": quote.number})


def _gate_or_fail(db: Session, sheet, valid_until: date | None) -> dict:
    gate = costing.gate(db, sheet, valid_until)
    if not gate["ok"]:
        raise Conflict("gate_failed", "The cost sheet does not pass the quote gate", {"failures": gate["failures"],
                                                                                     "max_valid_until": gate["max_valid_until"]})
    return gate


def _sheet_for(db: Session, case_id: uuid.UUID, sheet_id: uuid.UUID | None):
    if sheet_id:
        sheet = costing.get_sheet(db, sheet_id)
        if sheet.case_id != case_id:
            raise AppError("sheet_not_of_case", "The cost sheet belongs to another case", status=422)
        return sheet
    sheet = costing.current_sheet(db, case_id)
    if sheet is None:
        raise Conflict("gate_failed", "The case has no final cost sheet", {"failures": [{"code": "sheet_not_final"}]})
    return sheet


def _language_for(db: Session, party_id: uuid.UUID | None) -> str:
    if party_id is None:
        return "en"
    return "fa" if (parties.get_party(db, party_id).country_iso2 or "IR") == "IR" else "en"


def _primary_contact(db: Session, party_id: uuid.UUID | None) -> uuid.UUID | None:
    if party_id is None:
        return None
    active = [c for c in parties.contacts_of(db, party_id) if c.status == "active"]
    return next((c.id for c in active if c.is_primary), active[0].id if active else None)


def _party_name(db: Session, party_id: uuid.UUID | None, language: str) -> str:
    if party_id is None:
        return ""
    party = parties.get_party(db, party_id)
    return ((party.name_fa or party.name_en) if language == "fa" else (party.name_en or party.name_fa)) or ""


def render_terms(db: Session, quote: Quote) -> str:
    """The default ``quote_terms`` template of the quote's language with this quote's values."""
    template = sourcing_templates.default_of_kind(db, "quote_terms", quote.language)
    if template is None:
        return ""
    lang = quote.language
    lead = ""
    if quote.lead_time_days is not None:
        lead = f"{quote.lead_time_days} " + ("روز" if lang == "fa" else "days")
    bank = (settings.get(db, "company.bank_details") or {}).get(lang) or ""
    values = {"buyer_name": _party_name(db, quote.buyer_party_id, lang),
              "valid_until": sourcing_templates.format_date(quote.valid_until, lang),
              "payment_terms": quote.payment_terms or "", "lead_time": lead, "bank_details": bank,
              "incoterm": " ".join(x for x in (quote.incoterm, quote.incoterm_place) if x)}
    return sourcing_templates.render(template.body_template, values)


def _fill_items(db: Session, quote: Quote, sheet, keep: dict[uuid.UUID, QuoteItem] | None = None) -> None:
    """Quote rows from the sheet computation (priced items); ``keep`` carries texts and manual prices over."""
    computation = costing.compute_sheet(db, sheet)
    keep = keep or {}
    position = 0
    for row in computation["items"]:
        if row["total_price"] is None:
            continue
        item_id = uuid.UUID(row["item_id"])
        old = keep.get(item_id)
        position += 1
        unit_price, total, manual = row["unit_price"], row["total_price"], bool(row["manual"])
        if old is not None and old.price_manual:
            unit_price, manual = old.unit_price, True
            total = (unit_price * row["quantity"]).quantize(Decimal(1).scaleb(-computation["decimals"]))
        db.add(QuoteItem(quote_id=quote.id, line_item_id=item_id, position=position, quantity=row["quantity"],
                         unit_code=row.get("unit_code"), unit_text=row.get("unit_text"), unit_price=unit_price,
                         total=total, vat_amount=row["vat"], unit_cost=row["unit_cost"], price_manual=manual,
                         description_override=old.description_override if old else None,
                         lead_time_days=old.lead_time_days if old else None, note=old.note if old else None))
    if position == 0:
        raise Conflict("gate_failed", "No item of the sheet is priced", {"failures": [{"code": "item_not_priced"}]})
    flush(db, "invalid_quote")


def _totals(db: Session, quote: Quote) -> None:
    rows = items_of(db, quote.id)
    quote.subtotal = sum((r.total for r in rows), Decimal(0))
    quote.vat_amount = sum((r.vat_amount for r in rows), Decimal(0))
    quote.total = quote.subtotal + (quote.vat_amount if quote.price_basis == "with_vat" else Decimal(0))


def create_quote(db: Session, data: dict, calendar: str, source: str, actor: str | None = None) -> Quote:
    """A draft quote from the case's final cost sheet (or the given one), only when the sheet passes the gate."""
    case = sourcing_cases.get_case(db, data["case_id"])
    sheet = _sheet_for(db, case.id, data.get("cost_sheet_id"))
    gate = _gate_or_fail(db, sheet, data.get("valid_until"))
    buyer = data.get("buyer_party_id") or case.party_id
    if buyer:
        parties.get_party(db, buyer)
    contact = data.get("contact_id") or _primary_contact(db, buyer)
    if data.get("contact_id") and (buyer is None or parties.get_contact(db, data["contact_id"]).party_id != buyer):
        raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)
    language = data.get("language") or _language_for(db, buyer)
    version = (db.scalar(select(func.max(Quote.version)).where(Quote.case_id == case.id)) or 0) + 1
    payment_terms = data.get("payment_terms")
    if payment_terms is None and case.payment_term:
        payment_terms = next((t.label_fa if language == "fa" else t.label_en
                              for t in sourcing_cases.payment_terms(db) if t.code == case.payment_term), None)
    quote = Quote(case_id=case.id, cost_sheet_id=sheet.id, version=version, status="draft", language=language,
                  number=next_number(db, numbering_year(clock.today(), calendar)),
                  price_basis=data.get("price_basis") or "before_vat", currency=sheet.pricing_currency,
                  valid_until=date.fromisoformat(gate["valid_until"]), buyer_party_id=buyer, contact_id=contact,
                  supersedes_id=data.get("supersedes_id"),
                  **{k: data.get(k) for k in ("incoterm", "incoterm_place", "delivery_terms", "lead_time_days",
                                               "notes")}, payment_terms=payment_terms)
    db.add(quote)
    flush(db, "invalid_quote")
    quote.terms_text = data.get("terms_text") if data.get("terms_text") is not None else render_terms(db, quote)
    _fill_items(db, quote, sheet, data.get("_keep"))
    _totals(db, quote)
    flush(db, "invalid_quote")
    events.record(db, "quote", quote.id, "create", jsonable({
        "number": quote.number, "case_id": case.id, "version": version, "cost_sheet_id": sheet.id,
        "currency": quote.currency, "subtotal": quote.subtotal, "valid_until": quote.valid_until,
        "supersedes_id": quote.supersedes_id}), source, actor=actor)
    events.record(db, "case", case.id, "quote_add", jsonable({"quote_id": quote.id, "number": quote.number}),
                  source, actor=actor)
    return quote


def update_quote(db: Session, quote_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Quote:
    quote = get_quote(db, quote_id)
    _draft(quote)
    buyer = changes.get("buyer_party_id", quote.buyer_party_id)
    if "buyer_party_id" in changes and changes["buyer_party_id"]:
        parties.get_party(db, changes["buyer_party_id"])
        if "contact_id" not in changes:
            changes["contact_id"] = _primary_contact(db, changes["buyer_party_id"])
    if changes.get("contact_id") and (buyer is None or parties.get_contact(db, changes["contact_id"]).party_id != buyer):
        raise AppError("contact_not_of_party", "The contact belongs to another party", status=422)
    if changes.get("valid_until"):
        gate = costing.gate(db, costing.get_sheet(db, quote.cost_sheet_id), changes["valid_until"])
        if any(f["code"] == "validity_too_long" for f in gate["failures"]):
            raise AppError("validity_too_long", "The quote cannot be valid longer than the offers and FX allow",
                           {"max_valid_until": gate["max_valid_until"]}, status=422)
    changed = diff(quote, {k: v for k, v in changes.items() if k in EDITABLE})
    if changed:
        if "price_basis" in changed:
            _totals(db, quote)
        flush(db, "invalid_quote")
        events.record(db, "quote", quote.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return quote


def regenerate_terms(db: Session, quote_id: uuid.UUID, source: str, actor: str | None = None) -> Quote:
    quote = get_quote(db, quote_id)
    _draft(quote)
    return update_quote(db, quote_id, {"terms_text": render_terms(db, quote)}, source, actor)


def update_item(db: Session, quote_item_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> QuoteItem:
    row = db.get(QuoteItem, quote_item_id)
    if row is None:
        raise NotFound("not_found", "Quote item not found")
    quote = get_quote(db, row.quote_id)
    _draft(quote)
    if "unit_price" in changes:
        if changes["unit_price"] is None:  # back to the sheet's price
            sheet = costing.get_sheet(db, quote.cost_sheet_id)
            computed = {r["item_id"]: r for r in costing.compute_sheet(db, sheet)["items"]}[str(row.line_item_id)]
            changes.update(unit_price=computed["unit_price"], price_manual=False)
        else:
            changes["price_manual"] = True
        decimals = costing.currency_decimals(db, quote.currency)
        changes["total"] = (changes["unit_price"] * row.quantity).quantize(Decimal(1).scaleb(-decimals))
    changed = diff(row, {k: v for k, v in changes.items()
                         if k in ("description_override", "unit_price", "price_manual", "total", "lead_time_days", "note")})
    if changed:
        _totals(db, quote)
        flush(db, "invalid_quote")
        events.record(db, "quote", quote.id, "item_update", jsonable({"quote_item_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def remove_item(db: Session, quote_item_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = db.get(QuoteItem, quote_item_id)
    if row is None:
        raise NotFound("not_found", "Quote item not found")
    quote = get_quote(db, row.quote_id)
    _draft(quote)
    if len(items_of(db, quote.id)) <= 1:
        raise AppError("items_required", "A quote needs at least one item", status=422)
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    _totals(db, quote)
    flush(db, "invalid_quote")
    events.record(db, "quote", quote.id, "item_remove", {"deleted": jsonable(snapshot)}, source, actor=actor)


def recalculate(db: Session, quote_id: uuid.UUID, source: str, actor: str | None = None) -> Quote:
    """Refresh the rows from the cost sheet; texts and hand-set prices stay."""
    quote = get_quote(db, quote_id)
    _draft(quote)
    old = {r.line_item_id: r for r in items_of(db, quote.id)}
    for row in old.values():
        db.delete(row)
    db.flush()
    _fill_items(db, quote, costing.get_sheet(db, quote.cost_sheet_id), old)
    _totals(db, quote)
    flush(db, "invalid_quote")
    events.record(db, "quote", quote.id, "recalculate", jsonable({"subtotal": quote.subtotal}), source, actor=actor)
    return quote


def _minimums(db: Session, quote: Quote) -> list[dict]:
    sheet = costing.get_sheet(db, quote.cost_sheet_id)
    failures = []
    if sheet.min_acceptable_price is not None and quote.subtotal < sheet.min_acceptable_price:
        failures.append({"code": "below_minimum", "price": quote.subtotal, "minimum": sheet.min_acceptable_price})
    mins = sheet.item_min_prices or {}
    below = [str(r.line_item_id) for r in items_of(db, quote.id)
             if str(r.line_item_id) in mins and r.unit_price < Decimal(str(mins[str(r.line_item_id)]))]
    if below:
        failures.append({"code": "item_below_minimum", "item_ids": below})
    return failures


def approval_check(db: Session, quote: Quote) -> dict:
    sheet = costing.get_sheet(db, quote.cost_sheet_id)
    gate = costing.gate(db, sheet, quote.valid_until)
    failures = [f for f in gate["failures"] if f["code"] not in ("below_minimum", "item_below_minimum")]
    failures += jsonable(_minimums(db, quote))
    if quote.buyer_party_id is None:
        failures.append({"code": "buyer_required"})
    return {"ok": not failures, "failures": failures, "max_valid_until": gate["max_valid_until"]}


def approve(db: Session, quote_id: uuid.UUID, source: str, actor: str | None = None) -> Quote:
    """The owner's final review before sending: gate again, then the numbers are locked."""
    quote = get_quote(db, quote_id)
    _draft(quote)
    check = approval_check(db, quote)
    if not check["ok"]:
        raise Conflict("gate_failed", "The quote cannot be approved yet", {"failures": check["failures"]})
    quote.status, quote.approved_at, quote.approved_by = "approved", clock.now(), actor or "unknown"
    flush(db, "invalid_quote")
    events.record(db, "quote", quote.id, "approve", jsonable({"number": quote.number, "subtotal": quote.subtotal,
                                                             "total": quote.total, "valid_until": quote.valid_until}),
                  source, actor=actor)
    return quote


def default_followup(quote: Quote, today: date | None = None) -> dict:
    """"Chase quote response" due the day before the quote expires (never before today)."""
    today = today or clock.today()
    return {"action": CHASE_ACTION.get(quote.language, CHASE_ACTION["en"]),
            "due_on": max(today, quote.valid_until - timedelta(days=1))}


def _summary_text(db: Session, quote: Quote) -> str:
    names = {i.id: i.name for i in sourcing_items.items_of(db, case_id=quote.case_id)}
    lines = [f"{quote.number} (v{quote.version})"]
    for row in items_of(db, quote.id):
        lines.append(f"- {row.description_override or names.get(row.line_item_id, '')}: {row.quantity} x "
                     f"{row.unit_price} {quote.currency} = {row.total} {quote.currency}")
    basis = "with VAT" if quote.price_basis == "with_vat" else "before VAT"
    lines.append(f"Total {quote.total} {quote.currency} ({basis}); valid until {quote.valid_until.isoformat()}")
    return "\n".join(lines)


def _cancel_chases(db: Session, quote: Quote, note: str, source: str, actor: str | None) -> list[uuid.UUID]:
    if not quote.interaction_id:
        return []
    return [party_interactions.cancel_followup(db, f.id, note, source, actor).id
            for f in party_interactions.open_followups_of_interactions(db, [quote.interaction_id])]


def mark_sent(db: Session, quote_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> Quote:
    """Records the sending (BOMS sends nothing): one OUTGOING interaction for the buyer with a follow-up."""
    quote = get_quote(db, quote_id)
    if quote.status != "approved":
        raise Conflict("quote_not_approved", f"The quote is {quote.status}; approve it first", {"status": quote.status})
    if quote.buyer_party_id is None:
        raise AppError("buyer_required", "The quote has no buyer", status=422)
    try:
        sent_at = ensure_aware(data.get("sent_at") or clock.now())
    except ValueError:
        raise AppError("naive_datetime", "sent_at needs a timezone", status=422) from None
    followup, reason = data.get("followup"), (data.get("no_followup_reason") or "").strip() or None
    if not followup and not reason:
        followup = default_followup(quote)
    interaction, created = party_interactions.create_interaction(db, {
        "party_id": quote.buyer_party_id, "contact_id": quote.contact_id,
        "channel": INTERACTION_CHANNELS[data.get("channel") or "email"], "direction": "out", "occurred_at": sent_at,
        "subject": f"Proforma {quote.number}", "body": _summary_text(db, quote), "followup": followup,
        "no_followup_reason": reason}, source, actor)
    moved = None
    if data.get("move_to_quoted", True):
        roles = {r.role: r for r in parties.roles_of(db, quote.buyer_party_id)}
        if "buyer" in roles and roles["buyer"].stage not in ("quoted", "won", "lost"):
            parties.change_stage(db, quote.buyer_party_id, "buyer", "quoted", f"quote {quote.number} sent", source,
                                 actor)
            moved = "quoted"
    quote.status, quote.sent_at, quote.interaction_id = "sent", sent_at, interaction.id
    flush(db, "invalid_quote")
    events.record(db, "quote", quote.id, "sent", jsonable({
        "number": quote.number, "interaction_id": interaction.id, "followup_id": created.id if created else None,
        "no_followup_reason": reason, "funnel_stage": moved, "sent_at": sent_at}), source, actor=actor)
    return quote


def withdraw(db: Session, quote_id: uuid.UUID, reason: str, source: str, actor: str | None = None) -> Quote:
    quote = get_quote(db, quote_id)
    if quote.status not in ("approved", "sent", "expired"):
        raise Conflict("quote_locked", f"A {quote.status} quote cannot be withdrawn", {"status": quote.status})
    old = quote.status
    quote.status = "withdrawn"
    flush(db, "invalid_quote")
    cancelled = _cancel_chases(db, quote, "quote withdrawn", source, actor)
    events.record(db, "quote", quote.id, "withdraw", jsonable({"old_status": old, "reason": reason,
                                                              "cancelled_followups": cancelled}), source, actor=actor)
    return quote


def revise(db: Session, quote_id: uuid.UUID, data: dict, calendar: str, source: str, actor: str | None = None) -> Quote:
    """Next version prefilled from this one (texts, terms, hand-set prices) on the given / current final sheet;
    this one becomes ``superseded`` and its open chase follow-ups are cancelled."""
    old = get_quote(db, quote_id)
    if old.status in ("draft", "withdrawn", "superseded", "accepted"):
        raise Conflict("quote_locked", f"A {old.status} quote cannot be revised", {"status": old.status})
    sheet_id = data.get("cost_sheet_id") or (getattr(costing.current_sheet(db, old.case_id), "id", None)
                                             or old.cost_sheet_id)
    previous_status = old.status
    old.status = "superseded"
    flush(db, "invalid_quote")
    new = create_quote(db, {"case_id": old.case_id, "cost_sheet_id": sheet_id, "supersedes_id": old.id,
                            "valid_until": data.get("valid_until"),
                            "_keep": {r.line_item_id: r for r in items_of(db, old.id)},
                            **{k: getattr(old, k) for k in EDITABLE if k != "valid_until"}}, calendar, source, actor)
    cancelled = _cancel_chases(db, old, "quote revised", source, actor)
    events.record(db, "quote", old.id, "superseded", jsonable({"by": new.id, "number": new.number,
                                                              "old_status": previous_status,
                                                              "cancelled_followups": cancelled}), source, actor=actor)
    sourcing_items.recompute_items(db, [r.line_item_id for r in items_of(db, old.id)], source, actor)
    return new


def set_outcomes(db: Session, quote_id: uuid.UUID, rows: list[dict], source: str, actor: str | None = None) -> Quote:
    """Per-item outcome with reason (required for rejected); the quote status follows; sold items follow."""
    quote = get_quote(db, quote_id)
    if quote.status not in ("sent", "expired") + DECIDED:
        raise Conflict("quote_not_sent", f"The quote is {quote.status}; outcomes are recorded after sending",
                       {"status": quote.status})
    by_id = {r.id: r for r in items_of(db, quote.id)}
    reasons = {r.code for r in outcome_reasons(db)}
    today = clock.today()
    changes = []
    for data in rows:
        row = by_id.get(data["quote_item_id"])
        if row is None:
            raise AppError("item_not_of_quote", "The item belongs to another quote",
                           {"quote_item_id": str(data["quote_item_id"])}, status=422)
        if data.get("outcome") == "rejected" and not data.get("outcome_reason"):
            raise AppError("reason_required", "A rejected item needs a reason", {"quote_item_id": str(row.id)},
                           status=422)
        if data.get("outcome_reason") and data["outcome_reason"] not in reasons:
            raise AppError("unknown_reason", "Unknown reason", {"reason": data["outcome_reason"]}, status=422)
        if data.get("competitor_price") is not None and not data.get("competitor_currency"):
            raise AppError("currency_required", "A competitor price needs a currency", status=422)
        values = {k: data.get(k) for k in ("outcome", "outcome_reason", "outcome_note", "competitor_price",
                                            "competitor_currency")}
        values["decided_on"] = data.get("decided_on") or (today if data.get("outcome") else None)
        changed = diff(row, values)
        if changed:
            changes.append({"quote_item_id": row.id, "changes": changed})
    flush(db, "invalid_outcome")
    outcomes = [r.outcome for r in by_id.values()]
    old_status = quote.status
    if outcomes and all(o == "accepted" for o in outcomes):
        quote.status = "accepted"
    elif any(o == "accepted" for o in outcomes):
        quote.status = "partially_accepted"
    elif outcomes and all(o == "rejected" for o in outcomes):
        quote.status = "rejected"
    else:
        quote.status = "sent" if quote.valid_until >= today else "expired"
    quote.decided_at = clock.now() if quote.status in DECIDED else None
    flush(db, "invalid_quote")
    cancelled = _cancel_chases(db, quote, "quote decided", source, actor) if quote.status in DECIDED else []
    events.record(db, "quote", quote.id, "outcome", jsonable({"items": changes, "old_status": old_status,
                                                             "new_status": quote.status,
                                                             "cancelled_followups": cancelled}), source, actor=actor)
    sourcing_items.recompute_items(db, [r.line_item_id for r in by_id.values()], source, actor)
    return quote


def is_sold(db: Session, line_item_id: uuid.UUID) -> bool:
    """Accepted in a quote that is accepted or partially accepted (registered with the sourcing status function)."""
    return db.scalar(select(QuoteItem.id).join(Quote, Quote.id == QuoteItem.quote_id).where(
        QuoteItem.line_item_id == line_item_id, QuoteItem.outcome == "accepted",
        Quote.status.in_(("accepted", "partially_accepted"))).limit(1)) is not None


def expire_quotes(db: Session, today: date | None = None, source: str = "worker") -> list[uuid.UUID]:
    """Sent quotes past valid_until -> expired (status + event only; nobody is contacted)."""
    today = today or clock.today()
    rows = db.scalars(select(Quote).where(Quote.status == "sent", Quote.valid_until < today)).all()
    for quote in rows:
        quote.status = "expired"
        db.flush()
        events.record(db, "quote", quote.id, "status", {"old_status": "sent", "new_status": "expired",
                                                        "note": "valid_until passed"}, source)
    return [q.id for q in rows]


def delete_quote(db: Session, quote_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Drafts only; approved and later quotes are withdrawn instead."""
    quote = get_quote(db, quote_id)
    _draft(quote)
    successors = db.scalar(select(func.count()).select_from(Quote).where(Quote.supersedes_id == quote.id)) or 0
    if successors:
        raise Conflict("in_use", "A newer version refers to this quote", {"quotes": successors})
    snapshot = {"quote": row_snapshot(quote), "items": [row_snapshot(r) for r in items_of(db, quote.id)]}
    for link in parties.linked_documents(db, "quote", [str(quote.id)]):
        parties.unlink_document(db, "quote", quote.id, link["link_id"], source, actor)
    for row in items_of(db, quote.id):
        db.delete(row)
    db.flush()
    db.delete(quote)
    flush(db, "in_use")
    events.record(db, "quote", quote_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def set_case_result(db: Session, case_id: uuid.UUID, result: str, source: str, actor: str | None = None):
    """One click "won" / "lost" once no quote of the case is still open (draft, approved or sent)."""
    sourcing_cases.get_case(db, case_id)
    open_count = db.scalar(select(func.count()).select_from(Quote).where(
        Quote.case_id == case_id, Quote.status.in_(OPEN_STATUSES))) or 0
    if open_count:
        raise Conflict("quotes_undecided", "Some quotes are still open", {"quotes": open_count})
    return sourcing_cases.update_case(db, case_id, {"status": result}, source, actor)


def case_summary(db: Session, case_id: uuid.UUID) -> dict:
    quotes = list_quotes(db, case_id=case_id)
    won = sum(1 for q in quotes if q.status in ("accepted", "partially_accepted"))
    lost = sum(1 for q in quotes if q.status == "rejected")
    latest = next((q for q in quotes if q.status != "superseded"), None)
    return jsonable({"count": len(quotes), "won": won, "lost": lost,
                     "open": sum(1 for q in quotes if q.status in OPEN_STATUSES),
                     "latest": {"id": latest.id, "number": latest.number, "status": latest.status,
                                "valid_until": latest.valid_until} if latest else None,
                     "all_decided": bool(quotes) and not any(q.status in OPEN_STATUSES for q in quotes)})


# ---- product page: "Quotes we sent" -----------------------------------------------------------------------

def quotes_for_product(db: Session, product_id: uuid.UUID, today: date | None = None) -> dict:
    """Every sent quote row for items linked to the product, plus min/median/max per (currency, unit group)."""
    today = today or clock.today()
    units = sourcing_coverage.unit_index(db)
    rows = db.execute(text(
        """
        SELECT qi.id, q.id AS quote_id, q.number, q.case_id, q.sent_at, q.currency, q.incoterm, q.incoterm_place,
               q.status, qi.quantity, qi.unit_code, qi.unit_text, qi.unit_price, qi.outcome, qi.outcome_reason,
               q.buyer_party_id AS party_id, p.name_fa AS party_fa, p.name_en AS party_en
        FROM ops.quote_item qi
        JOIN ops.quote q ON q.id = qi.quote_id
        JOIN ops.line_item li ON li.id = qi.line_item_id
        LEFT JOIN core.party p ON p.id = q.buyer_party_id
        WHERE li.product_id = :p AND q.sent_at IS NOT NULL
        ORDER BY q.sent_at DESC
        """
    ), {"p": product_id}).mappings().all()
    groups: dict[tuple[str, str], list[Decimal]] = {}
    entries = []
    for r in rows:
        key, factor = sourcing_coverage.unit_group(r["unit_code"], r["unit_text"], units)
        price = sourcing_coverage.normalized_price(r["unit_price"], Decimal(1), factor)
        entries.append({**dict(r), "unit_group": key, "normalized_price": price})
        if price is not None:
            groups.setdefault((r["currency"], key), []).append(price)
    summary = [{"currency": cur, "unit_group": key, "count": len(values), "min": min(values),
                "median": median(values), "max": max(values)} for (cur, key), values in sorted(groups.items())]
    return jsonable({"quotes": entries, "summary": summary})


# ---- command center ------------------------------------------------------------------------------------------

def dashboard(db: Session, today: date) -> dict:
    awaiting = db.execute(text(
        """
        SELECT q.id AS quote_id, q.number, q.case_id, c.title AS case_title, q.total, q.currency, q.created_at
        FROM ops.quote q JOIN ops."case" c ON c.id = q.case_id
        WHERE q.status = 'draft' ORDER BY q.created_at
        """
    )).mappings().all()
    expiring = db.execute(text(
        """
        SELECT q.id AS quote_id, q.number, q.case_id, c.title AS case_title, q.valid_until, q.currency, q.total,
               p.name_fa AS party_name_fa, p.name_en AS party_name_en
        FROM ops.quote q JOIN ops."case" c ON c.id = q.case_id LEFT JOIN core.party p ON p.id = q.buyer_party_id
        WHERE q.status IN ('sent', 'expired') AND q.valid_until <= :until
          AND NOT EXISTS (SELECT 1 FROM ops.quote_item qi WHERE qi.quote_id = q.id AND qi.outcome IS NOT NULL)
        ORDER BY q.valid_until
        """
    ), {"until": today + timedelta(days=3)}).mappings().all()
    max_age = settings.get(db, "costing.fx_max_age_days")
    stale = db.execute(text(
        """
        SELECT s.id AS cost_sheet_id, s.case_id, c.title AS case_title, s.version, s.status, max(f.as_of) AS as_of
        FROM ops.cost_sheet s JOIN ops."case" c ON c.id = s.case_id JOIN ops.fx_rate_entry f ON f.cost_sheet_id = s.id
        WHERE s.status IN ('draft', 'final') AND c.status = 'open' AND s.fx_override_reason IS NULL
        GROUP BY s.id, s.case_id, c.title, s.version, s.status
        HAVING max(f.as_of) < :limit
        ORDER BY max(f.as_of)
        """
    ), {"limit": today - timedelta(days=max_age)}).mappings().all()
    since = clock.now() - timedelta(days=30)
    won = db.scalar(select(func.count()).select_from(Quote).where(
        Quote.status.in_(("accepted", "partially_accepted")), Quote.decided_at >= since)) or 0
    lost = db.scalar(select(func.count()).select_from(Quote).where(Quote.status == "rejected",
                                                                   Quote.decided_at >= since)) or 0
    return jsonable({
        "quotes_awaiting_approval": [dict(r) for r in awaiting],
        "quotes_expiring": [{**dict(r), "days_left": (r["valid_until"] - today).days} for r in expiring],
        "sheets_stale_fx": [{**dict(r), "age_days": (today - r["as_of"]).days} for r in stale],
        "quotes_won_30_days": won,
        "quotes_lost_30_days": lost,
    })


# ---- case cascade delete (test-data cleanup) ----------------------------------------------------------------

def cleanup_case(db: Session, case_id: uuid.UUID, note: str, source: str, actor: str | None) -> dict:
    """Quotes of a case being deleted: rows and output links go (files stay), chase follow-ups are cancelled."""
    quotes = list_quotes(db, case_id=case_id)
    snapshots, cancelled, links = [], [], 0
    for quote in quotes:
        cancelled += _cancel_chases(db, quote, note, source, actor)
        for link in parties.linked_documents(db, "quote", [str(quote.id)]):
            parties.unlink_document(db, "quote", quote.id, link["link_id"], source, actor)
            links += 1
        snapshots.append({"quote": row_snapshot(quote), "items": [row_snapshot(r) for r in items_of(db, quote.id)]})
    for quote in quotes:
        quote.supersedes_id = None
    db.flush()
    for quote in quotes:
        for row in items_of(db, quote.id):
            db.delete(row)
    db.flush()
    for quote in quotes:
        db.delete(quote)
    flush(db, "in_use")
    return jsonable({"quotes": snapshots, "cancelled_followups": cancelled,
                     "counts": {"quotes": len(quotes), "quote_outputs": links}})
