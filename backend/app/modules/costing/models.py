import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id

AMOUNT = Numeric(18, 4)
PERCENT = Numeric(9, 4)


class TaxKind(Timestamps, Base):
    __tablename__ = "tax_kind"
    __table_args__ = {"schema": "ops"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class TaxParameter(Timestamps, Base):
    __tablename__ = "tax_parameter"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    kind: Mapped[str] = mapped_column(ForeignKey("ops.tax_kind.code"))
    name: Mapped[str] = mapped_column(Text)
    rate_percent: Mapped[Decimal] = mapped_column(PERCENT)
    deal_type: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[str | None] = mapped_column(Text)
    confirmed_on: Mapped[date | None] = mapped_column(Date)


class CostTemplate(Timestamps, Base):
    __tablename__ = "cost_template"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(Text)
    name_fa: Mapped[str | None] = mapped_column(Text)
    deal_type: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="active")


class CostTemplateLine(Timestamps, Base):
    __tablename__ = "cost_template_line"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.cost_template.id"))
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    label_fa: Mapped[str | None] = mapped_column(Text)
    label_en: Mapped[str | None] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text)
    allocation: Mapped[str] = mapped_column(Text, default="by_value")
    paid_before_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_kind: Mapped[str | None] = mapped_column(ForeignKey("ops.tax_kind.code"))


class CostSheet(Timestamps, Base):
    __tablename__ = "cost_sheet"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="draft")
    deal_type: Mapped[str] = mapped_column(Text)
    pricing_currency: Mapped[str] = mapped_column(Text)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    sheet_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    supplier_prepay_percent: Mapped[Decimal] = mapped_column(PERCENT, default=Decimal(0))
    customer_prepay_percent: Mapped[Decimal] = mapped_column(PERCENT, default=Decimal(0))
    days_from_payment_to_receipt: Mapped[int] = mapped_column(Integer, default=0)
    annual_cost_of_money_percent: Mapped[Decimal] = mapped_column(PERCENT, default=Decimal(0))
    guarantee_percent: Mapped[Decimal] = mapped_column(PERCENT, default=Decimal(0))
    guarantee_days: Mapped[int] = mapped_column(Integer, default=0)
    pricing_method: Mapped[str] = mapped_column(Text, default="margin")
    target_percent: Mapped[Decimal | None] = mapped_column(PERCENT)
    min_acceptable_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    item_min_prices: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    price_overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    rounding: Mapped[str] = mapped_column(Text, default="none")
    rounding_step: Mapped[Decimal | None] = mapped_column(AMOUNT)
    validity_days: Mapped[int | None] = mapped_column(Integer)
    fx_override_reason: Mapped[str | None] = mapped_column(Text)
    parameter_override_reason: Mapped[str | None] = mapped_column(Text)
    finalized_at: Mapped[datetime | None] = mapped_column(TZ)


class FxRateEntry(Timestamps, Base):
    __tablename__ = "fx_rate_entry"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    cost_sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.cost_sheet.id"))
    from_currency: Mapped[str] = mapped_column(Text)
    to_currency: Mapped[str] = mapped_column(Text)
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    rate_kind: Mapped[str | None] = mapped_column(Text)
    source_note: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[date] = mapped_column(Date)


class CostLine(Timestamps, Base):
    __tablename__ = "cost_line"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    cost_sheet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.cost_sheet.id"))
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    line_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    currency: Mapped[str | None] = mapped_column(Text)
    basis: Mapped[str] = mapped_column(Text)
    percent: Mapped[Decimal | None] = mapped_column(PERCENT)
    allocation: Mapped[str] = mapped_column(Text, default="by_value")
    manual_shares: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    paid_before_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    tax_parameter_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    source_offer_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    notes: Mapped[str | None] = mapped_column(Text)
