"""Tender workflow tables (schema ``ops``, migration 0012)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, Boolean, Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id

AMOUNT = Numeric(20, 4)


class TenderResultReason(Timestamps, Base):
    __tablename__ = "tender_result_reason"
    __table_args__ = {"schema": "ops"}

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Tender(Timestamps, Base):
    __tablename__ = "tender"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    tender_no: Mapped[str | None] = mapped_column(Text)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    organizer_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    tender_type: Mapped[str | None] = mapped_column(Text)
    stages: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text, default="screening")
    participation: Mapped[str] = mapped_column(Text, default="undecided")
    participation_reason: Mapped[str | None] = mapped_column(Text)
    document_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    document_price_currency: Mapped[str | None] = mapped_column(Text)
    documents_obtained_at: Mapped[datetime | None] = mapped_column(TZ)
    estimate: Mapped[Decimal | None] = mapped_column(AMOUNT)
    estimate_currency: Mapped[str | None] = mapped_column(Text)
    proposal_validity_days: Mapped[int | None] = mapped_column(Integer)
    proposal_valid_until: Mapped[date | None] = mapped_column(Date)
    financial_mode: Mapped[str] = mapped_column(Text, default="buyer_form")
    submitted_at: Mapped[datetime | None] = mapped_column(TZ)
    submit_channel: Mapped[str | None] = mapped_column(Text)
    submit_note: Mapped[str | None] = mapped_column(Text)
    submit_override_reason: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    result_reason: Mapped[str | None] = mapped_column(Text)
    result_note: Mapped[str | None] = mapped_column(Text)
    winner_name: Mapped[str | None] = mapped_column(Text)
    winner_price: Mapped[Decimal | None] = mapped_column(AMOUNT)
    winner_price_currency: Mapped[str | None] = mapped_column(Text)
    our_rank: Mapped[int | None] = mapped_column(Integer)
    result_on: Mapped[date | None] = mapped_column(Date)
    appendix_seen: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    setad_dates_seen: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class TenderDate(Timestamps, Base):
    __tablename__ = "tender_date"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.tender.id"))
    kind: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(TZ)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)
    remind_days_before: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)
    source: Mapped[str] = mapped_column(Text, default="manual")


class TenderDateChange(Timestamps, Base):
    __tablename__ = "tender_date_change"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    tender_date_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.tender_date.id"))
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID)
    old_at: Mapped[datetime | None] = mapped_column(TZ)
    new_at: Mapped[datetime] = mapped_column(TZ)
    reason: Mapped[str] = mapped_column(Text)
    addendum_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class TenderAddendum(Timestamps, Base):
    __tablename__ = "tender_addendum"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.tender.id"))
    number: Mapped[str | None] = mapped_column(Text)
    received_on: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    question: Mapped[str | None] = mapped_column(Text)
    asked_on: Mapped[date | None] = mapped_column(Date)
    answer: Mapped[str | None] = mapped_column(Text)
    answered_on: Mapped[date | None] = mapped_column(Date)


class TenderFollowup(Timestamps, Base):
    __tablename__ = "tender_followup"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    tender_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    followup_id: Mapped[uuid.UUID] = mapped_column(UUID)
    purpose: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    days_before: Mapped[int | None] = mapped_column(Integer)


class CompanyDocument(Timestamps, Base):
    __tablename__ = "company_document"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, default="other")
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    issued_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")


class EnvelopeTemplate(Timestamps, Base):
    __tablename__ = "envelope_template"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="active")


class EnvelopeTemplateLine(Timestamps, Base):
    __tablename__ = "envelope_template_line"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    template_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.envelope_template.id"))
    envelope: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="document")


class EnvelopeItem(Timestamps, Base):
    __tablename__ = "envelope_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.tender.id"))
    envelope: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="document")
    status: Mapped[str] = mapped_column(Text, default="not_ready")
    company_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    guarantee_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    note: Mapped[str | None] = mapped_column(Text)


class Guarantee(Timestamps, Base):
    __tablename__ = "guarantee"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    tender_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    purpose: Mapped[str] = mapped_column(Text)
    form: Mapped[str | None] = mapped_column(Text)
    beneficiary_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    reminder_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    amount_currency: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(Text)
    number: Mapped[str | None] = mapped_column(Text)
    issued_on: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    claim_period_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="to_request")
    fee: Mapped[Decimal | None] = mapped_column(AMOUNT)
    fee_currency: Mapped[str | None] = mapped_column(Text)
    blocked_deposit: Mapped[Decimal | None] = mapped_column(AMOUNT)
    blocked_deposit_currency: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    description: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class GuaranteeEvent(Timestamps, Base):
    __tablename__ = "guarantee_event"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    guarantee_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.guarantee.id"))
    kind: Mapped[str] = mapped_column(Text)
    on_date: Mapped[date] = mapped_column(Date)
    old_status: Mapped[str | None] = mapped_column(Text)
    new_status: Mapped[str | None] = mapped_column(Text)
    valid_until: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class TenderCost(Timestamps, Base):
    __tablename__ = "tender_cost"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.tender.id"))
    kind: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(AMOUNT)
    amount_currency: Mapped[str] = mapped_column(Text)
    paid_on: Mapped[date | None] = mapped_column(Date)
    refundable: Mapped[bool] = mapped_column(Boolean, default=False)
    refunded_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class TenderProposal(Timestamps, Base):
    __tablename__ = "tender_proposal"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    tender_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.tender.id"))
    cost_sheet_id: Mapped[uuid.UUID] = mapped_column(UUID)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="draft")
    price_basis: Mapped[str] = mapped_column(Text, default="before_vat")
    currency: Mapped[str] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    valid_until: Mapped[date | None] = mapped_column(Date)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    approved_by: Mapped[str | None] = mapped_column(Text)
    below_cost_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class TenderProposalLine(Timestamps, Base):
    __tablename__ = "tender_proposal_line"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    proposal_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.tender_proposal.id"))
    line_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_code: Mapped[str | None] = mapped_column(Text)
    unit_text: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    total: Mapped[Decimal] = mapped_column(AMOUNT)
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    unit_cost: Mapped[Decimal | None] = mapped_column(AMOUNT)
