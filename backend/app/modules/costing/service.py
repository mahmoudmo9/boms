"""Costing (Phase 6): tax parameters, cost templates, versioned cost sheets with FX entries and cost lines,
the computation (``compute.py``) and the quote gate.

This module writes only its own tables. Case, line items and offers are read through the sourcing services;
events through ``events.record``. A sheet is editable while ``draft``; ``final`` is read-only (a new version
copies it); finalizing marks the previous final sheet ``superseded``.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.costing import compute as calc
from app.modules.costing import usage
from app.modules.costing.models import (
    CostLine,
    CostSheet,
    CostTemplate,
    CostTemplateLine,
    FxRateEntry,
    TaxKind,
    TaxParameter,
)
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.sourcing import coverage as sourcing_coverage
from app.modules.sourcing import inquiries as sourcing_cases
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing import offers as sourcing_offers
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.system import settings
from app.modules.system.models import Currency

DEAL_TYPES = ("import", "export", "domestic")
# Rials have no fractional unit in practice, although ISO 4217 lists 2 minor units for IRR
DECIMALS_OVERRIDE = {"IRR": 0}
SHEET_FIELDS = ("pricing_currency", "sheet_date", "notes", "supplier_prepay_percent", "customer_prepay_percent",
                "days_from_payment_to_receipt", "annual_cost_of_money_percent", "guarantee_percent", "guarantee_days",
                "pricing_method", "target_percent", "min_acceptable_price", "item_min_prices", "price_overrides",
                "rounding", "rounding_step", "validity_days", "deal_type")
LINE_FIELDS = ("position", "kind", "label", "scope", "line_item_id", "amount", "currency", "basis", "percent",
               "allocation", "manual_shares", "paid_before_receipt", "tax_parameter_id", "notes")
FX_FIELDS = ("from_currency", "to_currency", "rate", "rate_kind", "source_note", "as_of")


def currency_decimals(db: Session, code: str) -> int:
    if code in DECIMALS_OVERRIDE:
        return DECIMALS_OVERRIDE[code]
    row = db.get(Currency, code)
    if row is None:
        raise AppError("unknown_currency", "Unknown currency", {"currency": code}, status=422)
    return 2 if row.minor_units is None else int(row.minor_units)


# ---- tax parameters ---------------------------------------------------------------------------------------

def tax_kinds(db: Session) -> list[TaxKind]:
    return list(db.scalars(select(TaxKind).order_by(TaxKind.sort_order)))


def get_parameter(db: Session, parameter_id: uuid.UUID) -> TaxParameter:
    row = db.get(TaxParameter, parameter_id)
    if row is None:
        raise NotFound("not_found", "Tax parameter not found")
    return row


def list_parameters(db: Session, kind: str | None = None) -> list[TaxParameter]:
    query = select(TaxParameter).order_by(TaxParameter.kind, TaxParameter.deal_type, TaxParameter.effective_from.desc())
    if kind:
        query = query.where(TaxParameter.kind == kind)
    return list(db.scalars(query))


def create_parameter(db: Session, data: dict, source: str, actor: str | None = None) -> TaxParameter:
    """A new rate is always a new row with its own ``effective_from``; rows are never overwritten."""
    if data.get("effective_to") and data["effective_to"] < data["effective_from"]:
        raise AppError("invalid_period", "effective_to is before effective_from", status=422)
    if (data.get("confirmed_by") is None) != (data.get("confirmed_on") is None):
        raise AppError("confirmation_incomplete", "Give both who confirmed and when", status=422)
    row = TaxParameter(**data)
    db.add(row)
    flush(db, "invalid_parameter")
    events.record(db, "tax_parameter", row.id, "create", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def update_parameter(db: Session, parameter_id: uuid.UUID, changes: dict, source: str,
                     actor: str | None = None) -> TaxParameter:
    """Only the note, the end date and the confirmation change; a new rate is a new row."""
    row = get_parameter(db, parameter_id)
    if "effective_to" in changes and changes["effective_to"] and changes["effective_to"] < row.effective_from:
        raise AppError("invalid_period", "effective_to is before effective_from", status=422)
    by = changes.get("confirmed_by", row.confirmed_by)
    on = changes.get("confirmed_on", row.confirmed_on)
    if (by is None) != (on is None):
        raise AppError("confirmation_incomplete", "Give both who confirmed and when", status=422)
    changed = diff(row, changes)
    if changed:
        flush(db, "invalid_parameter")
        events.record(db, "tax_parameter", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return row


def delete_parameter(db: Session, parameter_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_parameter(db, parameter_id)
    used = db.scalar(select(func.count()).select_from(CostLine).where(CostLine.tax_parameter_id == row.id)) or 0
    if used:
        raise Conflict("in_use", "The parameter is used by cost lines; set an end date instead", {"cost_lines": used})
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "tax_parameter", parameter_id, "delete", {"deleted": snapshot}, source, actor=actor)


def parameter_in_force(db: Session, kind: str, deal_type: str, on: date) -> TaxParameter | None:
    """The newest row of ``kind`` in force on ``on``; a row for the exact deal type wins over ``all``."""
    rows = db.scalars(select(TaxParameter).where(
        TaxParameter.kind == kind, TaxParameter.deal_type.in_((deal_type, "all")),
        TaxParameter.effective_from <= on,
        (TaxParameter.effective_to.is_(None)) | (TaxParameter.effective_to >= on),
    ).order_by((TaxParameter.deal_type == deal_type).desc(), TaxParameter.effective_from.desc())).all()
    return rows[0] if rows else None


# ---- templates ---------------------------------------------------------------------------------------------

def get_template(db: Session, template_id: uuid.UUID) -> CostTemplate:
    row = db.get(CostTemplate, template_id)
    if row is None:
        raise NotFound("not_found", "Cost template not found")
    return row


def template_lines(db: Session, template_id: uuid.UUID) -> list[CostTemplateLine]:
    return list(db.scalars(select(CostTemplateLine).where(CostTemplateLine.template_id == template_id)
                           .order_by(CostTemplateLine.position)))


def list_templates(db: Session, include_archived: bool = False) -> list[CostTemplate]:
    query = select(CostTemplate).order_by(CostTemplate.deal_type, CostTemplate.is_default.desc(), CostTemplate.name)
    if not include_archived:
        query = query.where(CostTemplate.status == "active")
    return list(db.scalars(query))


def default_template(db: Session, deal_type: str) -> CostTemplate | None:
    return db.scalar(select(CostTemplate).where(CostTemplate.deal_type == deal_type, CostTemplate.is_default,
                                                CostTemplate.status == "active"))


def _clear_default(db: Session, template: CostTemplate) -> None:
    if template.is_default and template.status == "active":
        for other in db.scalars(select(CostTemplate).where(CostTemplate.deal_type == template.deal_type,
                                                           CostTemplate.is_default, CostTemplate.id != template.id)):
            other.is_default = False
        db.flush()


def _write_template_lines(db: Session, template: CostTemplate, lines: list[dict]) -> list[dict]:
    for row in template_lines(db, template.id):
        db.delete(row)
    db.flush()
    for position, line in enumerate(lines, start=1):
        db.add(CostTemplateLine(template_id=template.id, position=position, **line))
    flush(db, "invalid_template")
    return [jsonable(row_snapshot(r)) for r in template_lines(db, template.id)]


def create_template(db: Session, data: dict, source: str, actor: str | None = None) -> CostTemplate:
    lines = data.pop("lines", [])
    template = CostTemplate(**data)
    db.add(template)
    flush(db, "invalid_template")
    _clear_default(db, template)
    written = _write_template_lines(db, template, lines)
    events.record(db, "cost_template", template.id, "create",
                  jsonable({**row_snapshot(template), "lines": written}), source, actor=actor)
    return template


def update_template(db: Session, template_id: uuid.UUID, changes: dict, source: str,
                    actor: str | None = None) -> CostTemplate:
    """Name, default flag, status; ``lines`` (when given) replaces the whole list: add, remove, reorder."""
    template = get_template(db, template_id)
    lines = changes.pop("lines", None)
    changed = diff(template, changes)
    if changed:
        flush(db, "invalid_template")
        _clear_default(db, template)
    if lines is not None:
        before = [jsonable(row_snapshot(r)) for r in template_lines(db, template.id)]
        changed["lines"] = {"old": before, "new": _write_template_lines(db, template, lines)}
    if changed:
        events.record(db, "cost_template", template.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return template


def delete_template(db: Session, template_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    template = get_template(db, template_id)
    used = db.scalar(select(func.count()).select_from(CostSheet).where(CostSheet.template_id == template.id)) or 0
    if used:
        raise Conflict("in_use", "Cost sheets were made from this template; archive it instead", {"cost_sheets": used})
    snapshot = {**row_snapshot(template), "lines": [row_snapshot(r) for r in template_lines(db, template.id)]}
    for row in template_lines(db, template.id):
        db.delete(row)
    db.flush()
    db.delete(template)
    flush(db, "in_use")
    events.record(db, "cost_template", template_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


# ---- sheets -------------------------------------------------------------------------------------------------

def get_sheet(db: Session, sheet_id: uuid.UUID) -> CostSheet:
    row = db.get(CostSheet, sheet_id)
    if row is None:
        raise NotFound("not_found", "Cost sheet not found")
    return row


def sheets_of(db: Session, case_id: uuid.UUID) -> list[CostSheet]:
    return list(db.scalars(select(CostSheet).where(CostSheet.case_id == case_id).order_by(CostSheet.version.desc())))


def current_sheet(db: Session, case_id: uuid.UUID) -> CostSheet | None:
    return db.scalar(select(CostSheet).where(CostSheet.case_id == case_id, CostSheet.status == "final"))


def lines_of(db: Session, sheet_id: uuid.UUID) -> list[CostLine]:
    return list(db.scalars(select(CostLine).where(CostLine.cost_sheet_id == sheet_id)
                           .order_by(CostLine.position, CostLine.created_at)))


def fx_of(db: Session, sheet_id: uuid.UUID) -> list[FxRateEntry]:
    return list(db.scalars(select(FxRateEntry).where(FxRateEntry.cost_sheet_id == sheet_id)
                           .order_by(FxRateEntry.from_currency, FxRateEntry.to_currency)))


def sheet_items(db: Session, sheet: CostSheet):
    return sourcing_items.items_of(db, case_id=sheet.case_id, include_cancelled=False)


def _draft(sheet: CostSheet) -> None:
    if sheet.status != "draft":
        raise Conflict("sheet_not_draft", f"The cost sheet is {sheet.status}; create a new version to change it",
                       {"status": sheet.status, "version": sheet.version})


def _purchase_prefill(db: Session, item, units) -> dict:
    """Unit price per item unit from the item's selected offer row (price basis and convertible units applied)."""
    line = {"kind": "purchase", "scope": "item", "line_item_id": item.id, "basis": "per_unit", "allocation": "by_value",
            "paid_before_receipt": True, "label": item.name}
    if not item.selected_offer_item_id:
        return line
    offer_item = sourcing_offers.get_offer_item(db, item.selected_offer_item_id)
    offer = sourcing_offers.get_offer(db, offer_item.offer_id)
    price = offer_item.unit_price / (offer_item.price_per_quantity or Decimal(1))
    if offer_item.unit_code and item.unit_code and offer_item.unit_code != item.unit_code:
        offer_group, offer_factor = sourcing_coverage.unit_group(offer_item.unit_code, None, units)
        item_group, item_factor = sourcing_coverage.unit_group(item.unit_code, None, units)
        if offer_group == item_group and offer_group.startswith("kind:"):
            price = price / offer_factor * item_factor
    line.update(amount=price.quantize(Decimal("0.0001")), currency=offer.currency,
                source_offer_item_id=offer_item.id)
    return line


def _template_line_to_sheet(db: Session, tline: CostTemplateLine, deal_type: str, on: date, lang_label: str) -> dict:
    line = {"kind": tline.kind, "label": lang_label, "scope": "case", "basis": tline.basis,
            "allocation": tline.allocation, "paid_before_receipt": tline.paid_before_receipt}
    if tline.tax_kind:
        param = parameter_in_force(db, tline.tax_kind, deal_type, on)
        if param is not None:
            line.update(tax_parameter_id=param.id, percent=param.rate_percent)
    return line


def _add_line(db: Session, sheet: CostSheet, data: dict, position: int) -> CostLine:
    row = CostLine(cost_sheet_id=sheet.id, position=position, **data)
    db.add(row)
    return row


def create_sheet(db: Session, data: dict, source: str, actor: str | None = None) -> CostSheet:
    """A new sheet version for the case from a template (default for the deal type unless ``blank``).
    Purchase lines are pre-filled from each item's selected offer row."""
    case = sourcing_cases.get_case(db, data["case_id"])
    deal_type = data["deal_type"]
    template = None
    if data.get("template_id"):
        template = get_template(db, data["template_id"])
        if template.deal_type != deal_type:
            raise AppError("template_deal_type", "The template is for another deal type", status=422)
    elif not data.get("blank"):
        template = default_template(db, deal_type)
    currency_decimals(db, data["pricing_currency"])
    version = (db.scalar(select(func.max(CostSheet.version)).where(CostSheet.case_id == case.id)) or 0) + 1
    sheet = CostSheet(case_id=case.id, version=version, status="draft", deal_type=deal_type,
                      pricing_currency=data["pricing_currency"], template_id=template.id if template else None,
                      sheet_date=data.get("sheet_date") or clock.today(), notes=data.get("notes"),
                      pricing_method=settings.get(db, "costing.default_pricing_method"),
                      validity_days=settings.get(db, "quotes.default_validity_days"),
                      item_min_prices={}, price_overrides={})
    db.add(sheet)
    flush(db, "invalid_sheet")
    units = sourcing_coverage.unit_index(db)
    position = 0
    tlines = template_lines(db, template.id) if template else []
    language = data.get("language") or "en"
    purchase_done = False
    for tline in tlines or [None]:
        if tline is None or tline.kind == "purchase":
            if purchase_done:
                continue
            for item in sheet_items(db, sheet):
                position += 1
                _add_line(db, sheet, _purchase_prefill(db, item, units), position)
            purchase_done = True
            if tline is None:
                break
            continue
        label = (tline.label_fa if language == "fa" else tline.label_en) or tline.label_en or tline.label_fa
        position += 1
        _add_line(db, sheet, _template_line_to_sheet(db, tline, deal_type, sheet.sheet_date, label), position)
    flush(db, "invalid_line")
    events.record(db, "cost_sheet", sheet.id, "create", jsonable({
        "case_id": case.id, "version": version, "deal_type": deal_type, "pricing_currency": sheet.pricing_currency,
        "template_id": sheet.template_id, "lines": len(lines_of(db, sheet.id))}), source, actor=actor)
    events.record(db, "case", case.id, "cost_sheet_add", jsonable({"cost_sheet_id": sheet.id, "version": version}),
                  source, actor=actor)
    return sheet


def new_version(db: Session, sheet_id: uuid.UUID, source: str, actor: str | None = None) -> CostSheet:
    """Copy a sheet (any status) with its lines and FX entries as the case's next draft version."""
    old = get_sheet(db, sheet_id)
    version = (db.scalar(select(func.max(CostSheet.version)).where(CostSheet.case_id == old.case_id)) or 0) + 1
    copy = CostSheet(case_id=old.case_id, version=version, status="draft", template_id=old.template_id,
                     **{k: getattr(old, k) for k in SHEET_FIELDS})
    db.add(copy)
    flush(db, "invalid_sheet")
    for line in lines_of(db, old.id):
        db.add(CostLine(cost_sheet_id=copy.id, source_offer_item_id=line.source_offer_item_id,
                        **{k: getattr(line, k) for k in LINE_FIELDS}))
    for fx in fx_of(db, old.id):
        db.add(FxRateEntry(cost_sheet_id=copy.id, **{k: getattr(fx, k) for k in FX_FIELDS}))
    flush(db, "invalid_line")
    events.record(db, "cost_sheet", copy.id, "create", jsonable({
        "case_id": copy.case_id, "version": version, "copied_from": old.id, "copied_version": old.version}),
        source, actor=actor)
    events.record(db, "case", copy.case_id, "cost_sheet_add", jsonable({"cost_sheet_id": copy.id, "version": version}),
                  source, actor=actor)
    return copy


def update_sheet(db: Session, sheet_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> CostSheet:
    sheet = get_sheet(db, sheet_id)
    _draft(sheet)
    if changes.get("pricing_currency"):
        currency_decimals(db, changes["pricing_currency"])
    if changes.get("pricing_method", sheet.pricing_method) == "margin":
        target = changes.get("target_percent", sheet.target_percent)
        if target is not None and target >= 100:
            raise AppError("invalid_margin", "A margin must be below 100 %", {"percent": str(target)}, status=422)
    for key in ("item_min_prices", "price_overrides"):
        if key in changes:
            changes[key] = {str(k): str(v) for k, v in (changes[key] or {}).items() if v is not None}
    if changes.get("rounding", sheet.rounding) != "none" and not changes.get("rounding_step", sheet.rounding_step):
        raise AppError("rounding_step_required", "Rounding needs a step (for example 1000)", status=422)
    changed = diff(sheet, {k: v for k, v in changes.items() if k in SHEET_FIELDS})
    if changed:
        flush(db, "invalid_sheet")
        events.record(db, "cost_sheet", sheet.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return sheet


def delete_sheet(db: Session, sheet_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """Drafts only; final and superseded sheets are the record of what was priced."""
    sheet = get_sheet(db, sheet_id)
    _draft(sheet)
    used = usage.quotes_using_sheet(db, sheet.id)
    if used:
        raise Conflict("in_use", "Quotes use this cost sheet", {"quotes": used})
    snapshot = {"sheet": row_snapshot(sheet), "lines": [row_snapshot(r) for r in lines_of(db, sheet.id)],
                "fx": [row_snapshot(r) for r in fx_of(db, sheet.id)]}
    for row in lines_of(db, sheet.id) + fx_of(db, sheet.id):
        db.delete(row)
    db.flush()
    db.delete(sheet)
    flush(db, "in_use")
    events.record(db, "cost_sheet", sheet_id, "delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def _check_line(db: Session, sheet: CostSheet, data: dict) -> None:
    scope = data.get("scope")
    if scope == "item":
        if not data.get("line_item_id"):
            raise AppError("item_required", "An item line needs the item", status=422)
        item = sourcing_items.get_item(db, data["line_item_id"])
        if item.case_id != sheet.case_id:
            raise AppError("item_not_of_case", "The item belongs to another case", status=422)
    elif scope == "case" and data.get("line_item_id"):
        raise AppError("item_not_allowed", "A case line has no item", status=422)
    basis = data.get("basis")
    if basis and basis.startswith("percent_") and data.get("amount") is not None:
        raise AppError("amount_not_allowed", "A percentage line has no amount", status=422)
    if basis and not basis.startswith("percent_") and data.get("percent") is not None:
        raise AppError("percent_not_allowed", "Only percentage lines have a percent", status=422)
    if data.get("amount") is not None and not data.get("currency"):
        raise AppError("currency_required", "An amount needs a currency", status=422)
    if data.get("tax_parameter_id"):
        get_parameter(db, data["tax_parameter_id"])


def add_line(db: Session, sheet_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> CostLine:
    sheet = get_sheet(db, sheet_id)
    _draft(sheet)
    if data.get("tax_parameter_id") and data.get("percent") is None:
        data["percent"] = get_parameter(db, data["tax_parameter_id"]).rate_percent
    _check_line(db, sheet, data)
    position = data.pop("position", None) or (db.scalar(select(func.max(CostLine.position))
                                                        .where(CostLine.cost_sheet_id == sheet.id)) or 0) + 1
    row = _add_line(db, sheet, {k: v for k, v in data.items() if k in LINE_FIELDS}, position)
    flush(db, "invalid_line")
    events.record(db, "cost_sheet", sheet.id, "line_add", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def get_line(db: Session, line_id: uuid.UUID) -> CostLine:
    row = db.get(CostLine, line_id)
    if row is None:
        raise NotFound("not_found", "Cost line not found")
    return row


def update_line(db: Session, line_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> CostLine:
    row = get_line(db, line_id)
    sheet = get_sheet(db, row.cost_sheet_id)
    _draft(sheet)
    merged = {k: changes.get(k, getattr(row, k)) for k in LINE_FIELDS}
    if "tax_parameter_id" in changes and changes["tax_parameter_id"] and "percent" not in changes:
        merged["percent"] = changes["percent"] = get_parameter(db, changes["tax_parameter_id"]).rate_percent
    _check_line(db, sheet, merged)
    changed = diff(row, {k: v for k, v in changes.items() if k in LINE_FIELDS})
    if changed:
        flush(db, "invalid_line")
        events.record(db, "cost_sheet", sheet.id, "line_update", jsonable({"line_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def delete_line(db: Session, line_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_line(db, line_id)
    sheet = get_sheet(db, row.cost_sheet_id)
    _draft(sheet)
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "cost_sheet", sheet.id, "line_delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def set_fx(db: Session, sheet_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> FxRateEntry:
    """Add or replace the rate for one currency pair on a draft sheet (entered by hand, no default rate)."""
    sheet = get_sheet(db, sheet_id)
    _draft(sheet)
    for key in ("from_currency", "to_currency"):
        currency_decimals(db, data[key])
    row = db.scalar(select(FxRateEntry).where(FxRateEntry.cost_sheet_id == sheet.id,
                                              FxRateEntry.from_currency == data["from_currency"],
                                              FxRateEntry.to_currency == data["to_currency"]))
    if row is None:
        row = FxRateEntry(cost_sheet_id=sheet.id, **{k: data.get(k) for k in FX_FIELDS})
        db.add(row)
        flush(db, "invalid_fx")
        events.record(db, "cost_sheet", sheet.id, "fx_add", jsonable(row_snapshot(row)), source, actor=actor)
        return row
    changed = diff(row, {k: data.get(k) for k in FX_FIELDS})
    if changed:
        flush(db, "invalid_fx")
        events.record(db, "cost_sheet", sheet.id, "fx_update", jsonable({"fx_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def delete_fx(db: Session, fx_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = db.get(FxRateEntry, fx_id)
    if row is None:
        raise NotFound("not_found", "Exchange rate not found")
    sheet = get_sheet(db, row.cost_sheet_id)
    _draft(sheet)
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "cost_sheet", sheet.id, "fx_delete", {"deleted": jsonable(snapshot)}, source, actor=actor)


def rate_kind_suggestions(db: Session) -> list[str]:
    rows = db.execute(select(FxRateEntry.rate_kind, func.count()).where(FxRateEntry.rate_kind.is_not(None))
                      .group_by(FxRateEntry.rate_kind).order_by(func.count().desc()).limit(20)).all()
    return [r[0] for r in rows]


# ---- computation, warnings, gate ------------------------------------------------------------------------

def _dec_map(values: dict | None) -> dict[str, Decimal]:
    return {str(k): Decimal(str(v)) for k, v in (values or {}).items() if v is not None}


def compute_sheet(db: Session, sheet: CostSheet) -> dict:
    """Raises 422 ``fx_missing`` (naming the pair), ``invalid_margin``, ... as AppError."""
    items = sheet_items(db, sheet)
    fx = {(r.from_currency, r.to_currency): calc.Fx(r.rate, r.as_of, str(r.id)) for r in fx_of(db, sheet.id)}
    params = calc.Sheet(
        currency=sheet.pricing_currency, decimals=currency_decimals(db, sheet.pricing_currency), fx=fx,
        supplier_prepay_percent=sheet.supplier_prepay_percent, customer_prepay_percent=sheet.customer_prepay_percent,
        days_from_payment_to_receipt=sheet.days_from_payment_to_receipt,
        annual_cost_of_money_percent=sheet.annual_cost_of_money_percent, guarantee_percent=sheet.guarantee_percent,
        guarantee_days=sheet.guarantee_days, pricing_method=sheet.pricing_method, target_percent=sheet.target_percent,
        rounding=sheet.rounding, rounding_step=sheet.rounding_step, min_acceptable_price=sheet.min_acceptable_price,
        item_min_prices=_dec_map(sheet.item_min_prices), price_overrides=_dec_map(sheet.price_overrides))
    calc_items = [calc.Item(str(i.id), i.name, i.quantity) for i in items]
    calc_lines = [calc.Line(str(ln.id), ln.kind, ln.label, ln.scope, str(ln.line_item_id) if ln.line_item_id else None,
                            ln.amount, ln.currency, ln.basis, ln.percent, ln.allocation,
                            _dec_map(ln.manual_shares) if ln.manual_shares else None, ln.paid_before_receipt)
                  for ln in lines_of(db, sheet.id)]
    try:
        result = calc.compute(params, calc_items, calc_lines)
    except calc.CostingError as exc:
        raise AppError(exc.code, exc.message, exc.details, status=422) from None
    units = {str(i.id): (i.unit_code, i.unit_text) for i in items}
    for row in result["items"]:
        row["unit_code"], row["unit_text"] = units[row["item_id"]]
    return result


def warnings(db: Session, sheet: CostSheet, computation: dict | None = None, today: date | None = None) -> list[dict]:
    """Selected offer no longer valid / changed, unconfirmed tax parameter, stale FX."""
    today = today or clock.today()
    out = []
    items = {i.id: i for i in sheet_items(db, sheet)}
    for line in lines_of(db, sheet.id):
        if line.kind == "purchase" and line.source_offer_item_id:
            offer_item = sourcing_offers.get_offer_item(db, line.source_offer_item_id)
            offer = sourcing_offers.get_offer(db, offer_item.offer_id) if offer_item else None
            if offer_item is None or not offer_item.available or not sourcing_offers.is_valid(offer, today):
                out.append({"code": "offer_invalid", "line_id": str(line.id), "offer_id": str(offer.id) if offer else None,
                            "status": offer.status if offer else None,
                            "valid_until": offer.valid_until if offer else None})
            item = items.get(line.line_item_id)
            if item is not None and item.selected_offer_item_id != line.source_offer_item_id:
                out.append({"code": "selection_changed", "line_id": str(line.id), "item_id": str(item.id)})
        if line.tax_parameter_id:
            param = db.get(TaxParameter, line.tax_parameter_id)
            if param is not None and param.confirmed_on is None:
                out.append({"code": "unconfirmed_parameter", "line_id": str(line.id), "parameter_id": str(param.id),
                            "name": param.name})
    newest = computation.get("newest_fx_as_of") if computation else None
    max_age = settings.get(db, "costing.fx_max_age_days")
    if newest is not None and (today - newest).days > max_age:
        out.append({"code": "fx_stale", "as_of": newest, "max_age_days": max_age, "age_days": (today - newest).days})
    return out


def max_valid_until(db: Session, sheet: CostSheet, computation: dict | None) -> date | None:
    """Earliest valid_until of the selected supplier offers used, and the FX age limit."""
    limits = []
    for line in lines_of(db, sheet.id):
        if line.kind == "purchase" and line.source_offer_item_id:
            offer_item = sourcing_offers.get_offer_item(db, line.source_offer_item_id)
            if offer_item is not None:
                offer = sourcing_offers.get_offer(db, offer_item.offer_id)
                if offer.valid_until:
                    limits.append(offer.valid_until)
    if computation and computation.get("newest_fx_as_of"):
        limits.append(computation["newest_fx_as_of"] + timedelta(days=settings.get(db, "costing.fx_max_age_days")))
    return min(limits) if limits else None


def gate(db: Session, sheet: CostSheet, valid_until: date | None = None, today: date | None = None) -> dict:
    """All conditions for creating/approving a quote from this sheet, reported together."""
    today = today or clock.today()
    failures: list[dict] = []
    if sheet.status != "final":
        failures.append({"code": "sheet_not_final", "status": sheet.status})
    computation = None
    try:
        computation = compute_sheet(db, sheet)
    except AppError as exc:
        failures.append({"code": exc.code, **jsonable(exc.details)})
    if computation is not None:
        unpriced = [r["item_id"] for r in computation["items"] if r["total_price"] is None]
        if unpriced:
            failures.append({"code": "item_not_priced", "item_ids": unpriced})
        incomplete = [p for p in computation["problems"] if p["code"] in ("amount_missing", "percent_missing",
                                                                           "manual_shares_missing")]
        if incomplete:
            failures.append({"code": "lines_incomplete", "lines": incomplete})
        if computation["below_minimum"]:
            failures.append({"code": "below_minimum", "price": computation["totals"]["price_before_vat"],
                             "minimum": sheet.min_acceptable_price})
        below = [r["item_id"] for r in computation["items"] if r["below_minimum"]]
        if below:
            failures.append({"code": "item_below_minimum", "item_ids": below})
    limit = max_valid_until(db, sheet, computation)
    capped = False
    if valid_until is None:  # default: the sheet's validity, never beyond what the offers and the FX allow
        valid_until = today + timedelta(days=sheet.validity_days or settings.get(db, "quotes.default_validity_days"))
        if limit is not None and valid_until > limit:
            valid_until, capped = limit, True
    if limit is not None and valid_until > limit:
        failures.append({"code": "validity_too_long", "valid_until": valid_until, "max_valid_until": limit})
    found = warnings(db, sheet, computation, today)
    if any(w["code"] == "unconfirmed_parameter" for w in found) and not sheet.parameter_override_reason:
        failures.append({"code": "unconfirmed_parameter",
                         "parameters": [w["name"] for w in found if w["code"] == "unconfirmed_parameter"]})
    if any(w["code"] == "fx_stale" for w in found) and not sheet.fx_override_reason:
        stale = next(w for w in found if w["code"] == "fx_stale")
        failures.append({"code": "fx_stale", "as_of": stale["as_of"], "max_age_days": stale["max_age_days"]})
    return jsonable({"ok": not failures, "failures": failures, "valid_until": valid_until, "max_valid_until": limit,
                     "valid_until_capped": capped,
                     "overrides": {"fx_stale": sheet.fx_override_reason,
                                   "unconfirmed_parameter": sheet.parameter_override_reason}})


def override(db: Session, sheet_id: uuid.UUID, kind: str, reason: str, source: str, actor: str | None = None) -> CostSheet:
    """Accept a stale FX rate or an unconfirmed tax parameter for the gate, with a reason (event)."""
    sheet = get_sheet(db, sheet_id)
    if sheet.status == "superseded":
        raise Conflict("sheet_not_draft", "The cost sheet is superseded", {"status": sheet.status})
    reason = (reason or "").strip()
    if not reason:
        raise AppError("reason_required", "An override needs a reason", status=422)
    field = {"fx_stale": "fx_override_reason", "unconfirmed_parameter": "parameter_override_reason"}[kind]
    setattr(sheet, field, reason)
    flush(db, "invalid_sheet")
    events.record(db, "cost_sheet", sheet.id, "gate_override", {"kind": kind, "reason": reason}, source, actor=actor)
    return sheet


def finalize(db: Session, sheet_id: uuid.UUID, source: str, actor: str | None = None) -> CostSheet:
    """draft -> final (read-only); the previous final sheet of the case becomes superseded."""
    sheet = get_sheet(db, sheet_id)
    _draft(sheet)
    computation = compute_sheet(db, sheet)  # 422 fx_missing etc. before anything changes
    previous = current_sheet(db, sheet.case_id)
    if previous is not None:
        previous.status = "superseded"
        flush(db, "invalid_sheet")
        events.record(db, "cost_sheet", previous.id, "superseded", jsonable({"by": sheet.id, "version": sheet.version}),
                      source, actor=actor)
    sheet.status, sheet.finalized_at = "final", clock.now()
    flush(db, "invalid_sheet")
    events.record(db, "cost_sheet", sheet.id, "finalize", jsonable({
        "version": sheet.version, "totals": computation["totals"], "exposure": computation["exposure"]}),
        source, actor=actor)
    return sheet


def case_summary(db: Session, case_id: uuid.UUID) -> dict:
    """For the case header: the current (final) sheet's computed exposure, cost, price, margin and markup."""
    sourcing_cases.get_case(db, case_id)
    sheet = current_sheet(db, case_id)
    out = {"sheets": [jsonable({k: getattr(s, k) for k in ("id", "version", "status", "deal_type", "pricing_currency",
                                                            "sheet_date", "created_at", "finalized_at")})
                      for s in sheets_of(db, case_id)], "current": None}
    if sheet is not None:
        try:
            c = compute_sheet(db, sheet)
            out["current"] = jsonable({"sheet_id": sheet.id, "version": sheet.version, "currency": c["currency"],
                                       "exposure": c["exposure"]["exposure"], "cost": c["totals"]["cost_before_vat"],
                                       "price": c["totals"]["price_before_vat"],
                                       "margin_percent": c["totals"]["margin_percent"],
                                       "markup_percent": c["totals"]["markup_percent"]})
        except AppError as exc:
            out["current"] = jsonable({"sheet_id": sheet.id, "version": sheet.version, "error": exc.code})
    return out


def cleanup_case(db: Session, case_id: uuid.UUID, note: str, source: str, actor: str | None) -> dict:
    """Cost sheets of a case being deleted (test-data cleanup): lines, FX entries and the sheets go."""
    sheets = sheets_of(db, case_id)
    snapshots = [{"sheet": row_snapshot(s), "lines": [row_snapshot(r) for r in lines_of(db, s.id)],
                  "fx": [row_snapshot(r) for r in fx_of(db, s.id)]} for s in sheets]
    for sheet in sheets:
        for row in lines_of(db, sheet.id) + fx_of(db, sheet.id):
            db.delete(row)
    db.flush()
    for sheet in sheets:
        db.delete(sheet)
    flush(db, "in_use")
    return jsonable({"cost_sheets": snapshots, "counts": {"cost_sheets": len(sheets)}})
