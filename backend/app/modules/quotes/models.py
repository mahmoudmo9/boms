import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id

AMOUNT = Numeric(18, 4)


class OutcomeReason(Timestamps, Base):
    __tablename__ = "outcome_reason"
    __table_args__ = {"schema": "ops"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Quote(Timestamps, Base):
    __tablename__ = "quote"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    cost_sheet_id: Mapped[uuid.UUID] = mapped_column(UUID)
    number: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="draft")
    language: Mapped[str] = mapped_column(Text)
    price_basis: Mapped[str] = mapped_column(Text, default="before_vat")
    currency: Mapped[str] = mapped_column(Text)
    valid_until: Mapped[date] = mapped_column(Date)
    incoterm: Mapped[str | None] = mapped_column(Text)
    incoterm_place: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    terms_text: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    buyer_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    approved_by: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    decided_at: Mapped[datetime | None] = mapped_column(TZ)


class QuoteItem(Timestamps, Base):
    __tablename__ = "quote_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    quote_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.quote.id"))
    line_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer)
    description_override: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    unit_code: Mapped[str | None] = mapped_column(Text)
    unit_text: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    total: Mapped[Decimal] = mapped_column(AMOUNT)
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    unit_cost: Mapped[Decimal | None] = mapped_column(AMOUNT)
    price_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    outcome_reason: Mapped[str | None] = mapped_column(Text)
    outcome_note: Mapped[str | None] = mapped_column(Text)
    competitor_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    competitor_currency: Mapped[str | None] = mapped_column(Text)
    decided_on: Mapped[date | None] = mapped_column(Date)
