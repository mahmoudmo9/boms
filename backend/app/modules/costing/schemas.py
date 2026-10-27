"""Request models of the costing module. Every request body forbids unknown fields."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.core.schemas import InputModel
from app.modules.sourcing.schemas import Amount, Currency, LongText, Text300, Text500

DealType = Literal["import", "export", "domestic"]
LineKind = Literal["purchase", "freight_international", "insurance", "bank_fees", "customs_duty", "levy",
                   "customs_clearance", "storage", "inspection", "freight_domestic", "export_clearance", "vat", "other"]
Basis = Literal["total", "per_unit", "percent_of_cif", "percent_of_purchase"]
Allocation = Literal["by_value", "by_quantity", "equal", "manual"]
TaxKindCode = Literal["vat", "income_tax", "duty_default", "levy", "other"]
Percent = Annotated[Decimal, Field(ge=0, le=1000, max_digits=9, decimal_places=4)]
Share = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]
Rate = Annotated[Decimal, Field(gt=0, max_digits=24, decimal_places=10)]
Days = Annotated[int, Field(ge=0, le=3650)]


class TaxParameterIn(InputModel):
    kind: TaxKindCode
    name: Annotated[str, Field(min_length=1, max_length=300)]
    rate_percent: Percent
    deal_type: Literal["import", "export", "domestic", "all"] = "all"
    effective_from: date
    effective_to: date | None = None
    note: Text500 | None = None
    confirmed_by: Text300 | None = None
    confirmed_on: date | None = None


class TaxParameterPatch(InputModel):
    """Rate, kind and start date never change: a new rate is a new row."""
    effective_to: date | None = None
    note: Text500 | None = None
    confirmed_by: Text300 | None = None
    confirmed_on: date | None = None


class TemplateLineIn(InputModel):
    kind: LineKind
    label_fa: Text300 | None = None
    label_en: Text300 | None = None
    basis: Basis
    allocation: Allocation = "by_value"
    paid_before_receipt: bool = False
    tax_kind: TaxKindCode | None = None


class TemplateIn(InputModel):
    name: Annotated[str, Field(min_length=1, max_length=300)]
    name_fa: Text300 | None = None
    deal_type: DealType
    is_default: bool = False
    lines: list[TemplateLineIn] = Field(default_factory=list, max_length=100)


class TemplatePatch(InputModel):
    name: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    name_fa: Text300 | None = None
    is_default: bool | None = None
    status: Literal["active", "archived"] | None = None
    lines: list[TemplateLineIn] | None = Field(default=None, max_length=100)


class SheetCreate(InputModel):
    case_id: uuid.UUID
    deal_type: DealType
    pricing_currency: Currency
    template_id: uuid.UUID | None = None
    blank: bool = False
    sheet_date: date | None = None
    notes: LongText | None = None
    language: Literal["fa", "en"] | None = None


class SheetPatch(InputModel):
    deal_type: DealType | None = None
    pricing_currency: Currency | None = None
    sheet_date: date | None = None
    notes: LongText | None = None
    supplier_prepay_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)] | None = None
    customer_prepay_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)] | None = None
    days_from_payment_to_receipt: Days | None = None
    annual_cost_of_money_percent: Percent | None = None
    guarantee_percent: Annotated[Decimal, Field(ge=0, le=100, decimal_places=4)] | None = None
    guarantee_days: Days | None = None
    pricing_method: Literal["margin", "markup"] | None = None
    target_percent: Percent | None = None
    min_acceptable_price: Amount | None = None
    item_min_prices: dict[uuid.UUID, Amount | None] | None = None
    price_overrides: dict[uuid.UUID, Amount | None] | None = None
    rounding: Literal["none", "nearest", "up"] | None = None
    rounding_step: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)] | None = None
    validity_days: Days | None = None


class LineIn(InputModel):
    position: Annotated[int, Field(ge=1, le=100000)] | None = None
    kind: LineKind
    label: Annotated[str, Field(min_length=1, max_length=300)]
    scope: Literal["case", "item"] = "case"
    line_item_id: uuid.UUID | None = None
    amount: Amount | None = None
    currency: Currency | None = None
    basis: Basis = "total"
    percent: Percent | None = None
    allocation: Allocation = "by_value"
    manual_shares: dict[uuid.UUID, Share] | None = None
    paid_before_receipt: bool = False
    tax_parameter_id: uuid.UUID | None = None
    notes: Text500 | None = None


class LinePatch(InputModel):
    position: Annotated[int, Field(ge=1, le=100000)] | None = None
    kind: LineKind | None = None
    label: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    scope: Literal["case", "item"] | None = None
    line_item_id: uuid.UUID | None = None
    amount: Amount | None = None
    currency: Currency | None = None
    basis: Basis | None = None
    percent: Percent | None = None
    allocation: Allocation | None = None
    manual_shares: dict[uuid.UUID, Share] | None = None
    paid_before_receipt: bool | None = None
    tax_parameter_id: uuid.UUID | None = None
    notes: Text500 | None = None


class FxIn(InputModel):
    from_currency: Currency
    to_currency: Currency
    rate: Rate
    rate_kind: Text300 | None = None
    source_note: Text500 | None = None
    as_of: date


class OverrideIn(InputModel):
    kind: Literal["fx_stale", "unconfirmed_parameter"]
    reason: Annotated[str, Field(min_length=1, max_length=500)]
