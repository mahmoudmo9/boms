"""Request models of the tenders module (every body forbids unknown fields)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.core.schemas import InputModel

Text300 = Annotated[str, Field(max_length=300)]
Text2000 = Annotated[str, Field(max_length=2000)]
LongText = Annotated[str, Field(max_length=20000)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Amount = Annotated[Decimal, Field(ge=0, max_digits=20, decimal_places=4)]
Days = Annotated[int, Field(ge=0, le=365)]
Stage = Literal["screening", "documents", "pricing", "guarantee", "envelopes", "submitted", "opening", "result", "closed"]
DateKind = Literal["documents_deadline", "briefing", "site_visit", "questions_deadline", "proposal_deadline", "opening",
                   "quality_docs_deadline", "offer_valid_until", "other"]
Envelope = Literal["A", "B", "C"]
ItemStatus = Literal["not_ready", "in_progress", "needs_signature", "ready", "submitted"]
GuaranteeStatus = Literal["to_request", "requested", "issued", "ready_to_upload", "submitted", "extended", "released",
                          "claimed", "cancelled"]
Purpose = Literal["bid", "performance", "advance_payment", "retention", "other"]
Form = Literal["bank", "electronic_bank", "cheque", "cash_deposit", "insurance", "promissory_note", "other"]
DocCategory = Literal["registration", "tax", "insurance", "certificates", "track_record", "qualification", "identity",
                      "other"]


class TenderPatch(InputModel):
    tender_no: Text300 | None = None
    tender_type: Text300 | None = None
    stages: Literal["one_stage", "two_stage", "quality_evaluation"] | None = None
    stage: Stage | None = None
    participation: Literal["undecided", "yes", "no"] | None = None
    participation_reason: Text2000 | None = None
    document_price: Amount | None = None
    document_price_currency: Currency | None = None
    documents_obtained_at: datetime | None = None
    estimate: Amount | None = None
    estimate_currency: Currency | None = None
    proposal_validity_days: Annotated[int, Field(ge=1, le=3650)] | None = None
    proposal_valid_until: date | None = None
    financial_mode: Literal["buyer_form", "letterhead"] | None = None
    organizer_party_id: uuid.UUID | None = None


class DateIn(InputModel):
    kind: DateKind
    label: Text300 | None = None
    at: datetime
    all_day: bool = False
    note: Text2000 | None = None
    remind_days_before: list[Days] | None = Field(default=None, max_length=10)


class DatePatch(InputModel):
    label: Text300 | None = None
    at: datetime | None = None
    reason: Text2000 | None = None
    all_day: bool | None = None
    note: Text2000 | None = None
    remind_days_before: list[Days] | None = Field(default=None, max_length=10)


class DateChangeIn(InputModel):
    date_id: uuid.UUID | None = None
    kind: DateKind | None = None
    at: datetime


class AddendumIn(InputModel):
    number: Text300 | None = None
    received_on: date
    kind: Literal["clarification", "question_answer", "extension", "change", "cancellation", "other"]
    summary: LongText
    document_id: uuid.UUID | None = None
    question: LongText | None = None
    asked_on: date | None = None
    answer: LongText | None = None
    answered_on: date | None = None
    date_changes: list[DateChangeIn] = Field(default_factory=list, max_length=20)
    confirm_cancellation: bool = False


class AddendumPatch(InputModel):
    number: Text300 | None = None
    received_on: date | None = None
    summary: LongText | None = None
    document_id: uuid.UUID | None = None
    question: LongText | None = None
    asked_on: date | None = None
    answer: LongText | None = None
    answered_on: date | None = None
    date_changes: list[DateChangeIn] = Field(default_factory=list, max_length=20)


class RefreshApplyIn(InputModel):
    fields: list[Text300] = Field(min_length=1, max_length=30)


class SetadDateApplyIn(InputModel):
    kind: DateKind | None = None   # none = apply all


class ItemIn(InputModel):
    envelope: Envelope
    title: Text300
    kind: Literal["document", "bid_bond", "price_form"] = "document"
    status: ItemStatus | None = None
    company_document_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    note: Text2000 | None = None


class ItemPatch(InputModel):
    title: Text300 | None = None
    status: ItemStatus | None = None
    company_document_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    note: Text2000 | None = None


class ReorderIn(InputModel):
    envelope: Envelope
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class FromTemplateIn(InputModel):
    template_id: uuid.UUID | None = None


class CompanyDocIn(InputModel):
    title: Text300
    category: DocCategory = "other"
    document_id: uuid.UUID | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    note: Text2000 | None = None


class CompanyDocPatch(InputModel):
    title: Text300 | None = None
    category: DocCategory | None = None
    document_id: uuid.UUID | None = None
    issued_on: date | None = None
    expires_on: date | None = None
    note: Text2000 | None = None
    status: Literal["active", "archived"] | None = None


class TemplateLineIn(InputModel):
    envelope: Envelope
    title: Text300
    kind: Literal["document", "bid_bond", "price_form"] = "document"


class TemplateIn(InputModel):
    name: Text300
    is_default: bool = False
    lines: list[TemplateLineIn] = Field(default_factory=list, max_length=200)


class GuaranteeIn(InputModel):
    case_id: uuid.UUID
    tender_id: uuid.UUID | None = None
    purpose: Purpose
    form: Form | None = None
    beneficiary_party_id: uuid.UUID | None = None
    reminder_party_id: uuid.UUID | None = None
    amount: Amount | None = None
    amount_currency: Currency | None = None
    bank_name: Text300 | None = None
    branch: Text300 | None = None
    number: Text300 | None = None
    issued_on: date | None = None
    valid_until: date | None = None
    claim_period_until: date | None = None
    fee: Amount | None = None
    fee_currency: Currency | None = None
    blocked_deposit: Amount | None = None
    blocked_deposit_currency: Currency | None = None
    document_id: uuid.UUID | None = None
    description: Text2000 | None = None
    note: Text2000 | None = None


class GuaranteePatch(InputModel):
    purpose: Purpose | None = None
    form: Form | None = None
    beneficiary_party_id: uuid.UUID | None = None
    reminder_party_id: uuid.UUID | None = None
    amount: Amount | None = None
    amount_currency: Currency | None = None
    bank_name: Text300 | None = None
    branch: Text300 | None = None
    number: Text300 | None = None
    issued_on: date | None = None
    valid_until: date | None = None
    claim_period_until: date | None = None
    fee: Amount | None = None
    fee_currency: Currency | None = None
    blocked_deposit: Amount | None = None
    blocked_deposit_currency: Currency | None = None
    document_id: uuid.UUID | None = None
    description: Text2000 | None = None
    note: Text2000 | None = None


class GuaranteeStatusIn(InputModel):
    status: GuaranteeStatus
    on_date: date | None = None
    valid_until: date | None = None
    reason: Text2000 | None = None
    document_id: uuid.UUID | None = None


class CostIn(InputModel):
    kind: Literal["documents_purchase", "guarantee_fee", "deposit", "travel", "other"]
    amount: Amount
    amount_currency: Currency = "IRR"
    paid_on: date | None = None
    refundable: bool | None = None
    refunded_on: date | None = None
    note: Text2000 | None = None
    document_id: uuid.UUID | None = None


class CostPatch(InputModel):
    kind: Literal["documents_purchase", "guarantee_fee", "deposit", "travel", "other"] | None = None
    amount: Amount | None = None
    amount_currency: Currency | None = None
    paid_on: date | None = None
    refundable: bool | None = None
    refunded_on: date | None = None
    note: Text2000 | None = None
    document_id: uuid.UUID | None = None


class SubmitIn(InputModel):
    submitted_at: datetime | None = None
    channel: Literal["setad", "in_person", "post", "other"] = "setad"
    note: Text2000 | None = None
    override_reason: Text2000 | None = None


class ResultIn(InputModel):
    result: Literal["won", "lost", "cancelled", "no_result"]
    result_reason: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")] | None = None
    result_note: Text2000 | None = None
    winner_name: Text300 | None = None
    winner_price: Amount | None = None
    winner_price_currency: Currency | None = None
    our_rank: Annotated[int, Field(ge=1, le=1000)] | None = None
    result_on: date | None = None
    case_status: Literal["won", "lost", "cancelled", "open"] | None = None


class ReasonIn(InputModel):
    code: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")]
    label_fa: Text300
    label_en: Text300
    active: bool = True


class ReasonsIn(InputModel):
    reasons: list[ReasonIn] = Field(min_length=1, max_length=50)


class ProposalCreate(InputModel):
    cost_sheet_id: uuid.UUID | None = None
    price_basis: Literal["before_vat", "with_vat"] = "before_vat"
    valid_until: date | None = None
    note: Text2000 | None = None


class ProposalPatch(InputModel):
    price_basis: Literal["before_vat", "with_vat"] | None = None
    valid_until: date | None = None
    note: Text2000 | None = None


class ProposalLinePatch(InputModel):
    unit_price: Amount


class ProposalApproveIn(InputModel):
    confirm_below_cost: bool = False
    reason: Text2000 | None = None


class OutputIn(InputModel):
    format: Literal["pdf", "docx"]
