import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Computed, Date, ForeignKey, Integer, Numeric, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id

AMOUNT = Numeric(18, 4)


class PaymentTerm(Timestamps, Base):
    __tablename__ = "payment_term"
    __table_args__ = {"schema": "ops"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)
    requires_reason: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemStatus(Timestamps, Base):
    __tablename__ = "item_status"
    __table_args__ = {"schema": "ops"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)


class Inquiry(Timestamps, Base):
    __tablename__ = "inquiry"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    source_channel: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="rfq")
    received_at: Mapped[datetime] = mapped_column(TZ)
    response_due_on: Mapped[date | None] = mapped_column(Date)
    subject: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    search_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True), deferred=True)
    status: Mapped[str] = mapped_column(Text, default="new")
    source_interaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    reject_reason: Mapped[str | None] = mapped_column(Text)


class Decision(Timestamps, Base):
    __tablename__ = "decision"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    inquiry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.inquiry.id"))
    light: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    feasible_sourcing: Mapped[str] = mapped_column(Text, default="unknown")
    feasible_sourcing_note: Mapped[str | None] = mapped_column(Text)
    exposure_acceptable: Mapped[str] = mapped_column(Text, default="unknown")
    exposure_acceptable_note: Mapped[str | None] = mapped_column(Text)
    requirements_ok: Mapped[str] = mapped_column(Text, default="unknown")
    requirements_ok_note: Mapped[str | None] = mapped_column(Text)
    exposure_estimate: Mapped[Decimal | None] = mapped_column(AMOUNT)
    exposure_currency: Mapped[str | None] = mapped_column(Text)
    payment_term: Mapped[str | None] = mapped_column(Text)
    ordering_before_payment_reason: Mapped[str | None] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class Case(Timestamps, Base):
    __tablename__ = "case"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
    status: Mapped[str] = mapped_column(Text, default="open")
    payment_term: Mapped[str | None] = mapped_column(Text)
    ordering_before_payment_reason: Mapped[str | None] = mapped_column(Text)
    exposure_estimate: Mapped[Decimal | None] = mapped_column(AMOUNT)
    exposure_currency: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class LineItem(Timestamps, Base):
    __tablename__ = "line_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
    description: Mapped[str | None] = mapped_column(Text)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    quantity: Mapped[Decimal | None] = mapped_column(AMOUNT)
    unit_code: Mapped[str | None] = mapped_column(Text)
    unit_text: Mapped[str | None] = mapped_column(Text)
    target_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    target_currency: Mapped[str | None] = mapped_column(Text)
    destination_country_iso2: Mapped[str | None] = mapped_column(Text)
    incoterm: Mapped[str | None] = mapped_column(Text)
    incoterm_place: Mapped[str | None] = mapped_column(Text)
    required_by: Mapped[date | None] = mapped_column(Date)
    packaging: Mapped[str | None] = mapped_column(Text)
    hs_code: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str] = mapped_column(Text, default="unknown")
    notes: Mapped[str | None] = mapped_column(Text)
    specs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(Text, default="uncovered")
    no_coverage_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    no_coverage_reason: Mapped[str | None] = mapped_column(Text)
    selected_offer_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class MessageTemplate(Timestamps, Base):
    __tablename__ = "message_template"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    kind: Mapped[str] = mapped_column(Text, default="rfq")
    language: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    subject_template: Mapped[str] = mapped_column(Text, default="")
    body_template: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="active")


class Rfq(Timestamps, Base):
    __tablename__ = "rfq"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
    status: Mapped[str] = mapped_column(Text, default="draft")
    language: Mapped[str] = mapped_column(Text, default="en")
    respond_by: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class RfqItem(Timestamps, Base):
    __tablename__ = "rfq_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    rfq_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.rfq.id"))
    line_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    quantity: Mapped[Decimal | None] = mapped_column(AMOUNT)
    unit_code: Mapped[str | None] = mapped_column(Text)
    unit_text: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class RfqRecipient(Timestamps, Base):
    __tablename__ = "rfq_recipient"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    rfq_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.rfq.id"))
    party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    channel: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, default="en")
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    status: Mapped[str] = mapped_column(Text, default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    subject: Mapped[str | None] = mapped_column(Text)
    message_text: Mapped[str | None] = mapped_column(Text)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class SupplierOffer(Timestamps, Base):
    __tablename__ = "supplier_offer"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    rfq_recipient_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    received_at: Mapped[datetime] = mapped_column(TZ)
    channel: Mapped[str] = mapped_column(Text)
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(Text)
    incoterm: Mapped[str | None] = mapped_column(Text)
    incoterm_place: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(Text)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    compliance_notes: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    raw_norm: Mapped[str | None] = mapped_column(Text, Computed("x", persisted=True), deferred=True)
    status: Mapped[str] = mapped_column(Text, default="active")
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class OfferItem(Timestamps, Base):
    __tablename__ = "offer_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ops.supplier_offer.id"))
    line_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    unit_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    price_per_quantity: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(1))
    unit_code: Mapped[str | None] = mapped_column(Text)
    unit_text: Mapped[str | None] = mapped_column(Text)
    moq: Mapped[Decimal | None] = mapped_column(AMOUNT)
    moq_unit: Mapped[str | None] = mapped_column(Text)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    spec_deviation: Mapped[str | None] = mapped_column(Text)
    packaging: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class HsCode(Timestamps, Base):
    __tablename__ = "hs_code"
    __table_args__ = {"schema": "ref"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger)
    parent_code: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    title_fa: Mapped[str | None] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
    edition: Mapped[str] = mapped_column(Text)


class IsicCode(Timestamps, Base):
    __tablename__ = "isic_code"
    __table_args__ = {"schema": "ref"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    level: Mapped[str] = mapped_column(Text)
    parent_code: Mapped[str | None] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    title_fa: Mapped[str | None] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text, Computed("x", persisted=True))
    edition: Mapped[str] = mapped_column(Text)


class PartyCapability(Timestamps, Base):
    __tablename__ = "party_capability"
    __table_args__ = {"schema": "core"}

    id: Mapped[uuid.UUID] = _id()
    party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    kind: Mapped[str] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(Text)
    tag_text: Mapped[str | None] = mapped_column(Text)
    tag_norm: Mapped[str | None] = mapped_column(Text, Computed("x", persisted=True))
    notes: Mapped[str | None] = mapped_column(Text)
