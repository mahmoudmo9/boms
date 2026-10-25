"""Request and response models of the sourcing module. Every request body forbids unknown fields."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.core.schemas import ApiModel, InputModel

SourceChannel = Literal["whatsapp", "email", "phone", "tender_portal", "in_person", "letter", "other"]
InquiryKind = Literal["rfq", "tender", "direct_order", "other"]
InquiryStatus = Literal["new", "needs_info", "ready_for_screening", "rejected", "no_reply", "converted"]
Light = Literal["green", "yellow", "red"]
Check = Literal["yes", "no", "unknown"]
CaseStatus = Literal["open", "won", "lost", "closed", "cancelled"]
Route = Literal["domestic", "foreign", "both", "unknown"]
Incoterm = Literal["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
RfqChannel = Literal["email", "whatsapp", "letter", "phone", "other"]
TemplateChannel = Literal["email", "whatsapp", "letter"]
OfferChannel = Literal["email", "whatsapp", "wechat", "phone", "letter", "other"]

Text300 = Annotated[str, Field(max_length=300)]
Text500 = Annotated[str, Field(max_length=500)]
LongText = Annotated[str, Field(max_length=20000)]
RawText = Annotated[str, Field(max_length=200000)]
Code = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.\-]{1,40}$")]
Iso2 = Annotated[str, Field(pattern=r"^[A-Za-z]{2}$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Lang = Annotated[str, Field(pattern=r"^[a-z]{2,3}$")]
HsCode = Annotated[str, Field(pattern=r"^[0-9]{2,10}$")]
Amount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]


def _strip(value):
    return value.strip() or None if isinstance(value, str) else value


# ---- line items -------------------------------------------------------------------------------

class SpecIn(InputModel):
    key: Annotated[str, Field(min_length=1, max_length=200)]
    value: Annotated[str, Field(max_length=2000)] = ""
    unit: Annotated[str, Field(max_length=50)] | None = None


class LineItemFields(InputModel):
    position: Annotated[int, Field(ge=1, le=100000)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    description: LongText | None = None
    product_id: uuid.UUID | None = None
    quantity: Quantity | None = None
    unit_code: Code | None = None
    unit_text: Text300 | None = None
    target_price: Amount | None = None
    target_currency: Currency | None = None
    destination_country_iso2: Iso2 | None = None
    incoterm: Incoterm | None = None
    incoterm_place: Text300 | None = None
    required_by: date | None = None
    packaging: Text500 | None = None
    hs_code: HsCode | None = None
    route: Route | None = None
    notes: LongText | None = None
    specs: list[SpecIn] | None = Field(default=None, max_length=200)


class LineItemCreate(LineItemFields):
    name: Annotated[str, Field(min_length=1, max_length=1000)]


class LineItemAdd(LineItemCreate):
    inquiry_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None


class LineItemBulk(InputModel):
    inquiry_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    items: list[LineItemCreate] = Field(min_length=1, max_length=500)


class NoCoverageIn(InputModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class CancelIn(InputModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class LineItemOut(ApiModel):
    id: uuid.UUID
    inquiry_id: uuid.UUID | None
    case_id: uuid.UUID | None
    position: int
    name: str
    description: str | None
    product_id: uuid.UUID | None
    quantity: Decimal | None
    unit_code: str | None
    unit_text: str | None
    target_price: Decimal | None
    target_currency: str | None
    destination_country_iso2: str | None
    incoterm: str | None
    incoterm_place: str | None
    required_by: date | None
    packaging: str | None
    hs_code: str | None
    route: str
    notes: str | None
    specs: list[dict]
    status: str
    no_coverage_confirmed: bool
    no_coverage_reason: str | None
    selected_offer_item_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ImportParseIn(InputModel):
    text: Annotated[str, Field(min_length=1, max_length=500000)]


ImportField = Literal["name", "description", "quantity", "unit", "target_price", "target_currency", "packaging",
                      "hs_code", "required_by", "incoterm", "incoterm_place", "notes", "spec"]


class ImportMapping(InputModel):
    column: Annotated[int, Field(ge=0, le=200)]
    field: ImportField
    spec_key: Annotated[str, Field(max_length=200)] | None = None


class ImportPreviewIn(InputModel):
    rows: list[list[Annotated[str, Field(max_length=5000)]]] = Field(max_length=2000)
    mapping: list[ImportMapping] = Field(min_length=1, max_length=200)
    skip_header: bool = False
    inquiry_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None


# ---- inquiries, decisions, cases --------------------------------------------------------------

class InquiryCreate(InputModel):
    party_id: uuid.UUID | None = None
    source_channel: SourceChannel
    kind: InquiryKind = "rfq"
    received_at: datetime | None = None
    response_due_on: date | None = None
    subject: Text500 | None = None
    raw_text: RawText | None = None
    source_interaction_id: uuid.UUID | None = None
    items: list[LineItemCreate] = Field(default_factory=list, max_length=500)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class InquiryPatch(InputModel):
    party_id: uuid.UUID | None = None
    source_channel: SourceChannel | None = None
    kind: InquiryKind | None = None
    received_at: datetime | None = None
    response_due_on: date | None = None
    subject: Text500 | None = None
    status: Literal["new", "needs_info", "ready_for_screening", "no_reply"] | None = None


class RejectIn(InputModel):
    reason: Annotated[str, Field(min_length=1, max_length=2000)]


class InquiryOut(ApiModel):
    id: uuid.UUID
    party_id: uuid.UUID | None
    source_channel: str
    kind: str
    received_at: datetime
    response_due_on: date | None
    subject: str | None
    raw_text: str | None
    status: str
    source_interaction_id: uuid.UUID | None
    reject_reason: str | None
    created_at: datetime
    updated_at: datetime


class DecisionIn(InputModel):
    light: Light
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    feasible_sourcing: Check = "unknown"
    feasible_sourcing_note: Text500 | None = None
    exposure_acceptable: Check = "unknown"
    exposure_acceptable_note: Text500 | None = None
    requirements_ok: Check = "unknown"
    requirements_ok_note: Text500 | None = None
    exposure_estimate: Amount | None = None
    exposure_currency: Currency | None = None
    payment_term: Code | None = None
    ordering_before_payment_reason: Text500 | None = None
    confirmed: bool = False

    _strip_reason = field_validator("reason", "ordering_before_payment_reason", mode="before")(_strip)


class DecisionOut(ApiModel):
    id: uuid.UUID
    inquiry_id: uuid.UUID
    light: str
    reason: str
    feasible_sourcing: str
    feasible_sourcing_note: str | None
    exposure_acceptable: str
    exposure_acceptable_note: str | None
    requirements_ok: str
    requirements_ok_note: str | None
    exposure_estimate: Decimal | None
    exposure_currency: str | None
    payment_term: str | None
    ordering_before_payment_reason: str | None
    confirmed: bool
    updated_at: datetime


class ConvertIn(InputModel):
    title: Text500 | None = None


class CaseCreate(InputModel):
    party_id: uuid.UUID | None = None
    title: Annotated[str, Field(min_length=1, max_length=500)]
    payment_term: Code | None = None
    ordering_before_payment_reason: Text500 | None = None
    exposure_estimate: Amount | None = None
    exposure_currency: Currency | None = None
    notes: LongText | None = None


class CasePatch(InputModel):
    party_id: uuid.UUID | None = None
    title: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    status: CaseStatus | None = None
    payment_term: Code | None = None
    ordering_before_payment_reason: Text500 | None = None
    exposure_estimate: Amount | None = None
    exposure_currency: Currency | None = None
    notes: LongText | None = None


class CaseOut(ApiModel):
    id: uuid.UUID
    inquiry_id: uuid.UUID | None
    party_id: uuid.UUID | None
    title: str
    status: str
    payment_term: str | None
    ordering_before_payment_reason: str | None
    exposure_estimate: Decimal | None
    exposure_currency: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DocumentLinkIn(InputModel):
    document_id: uuid.UUID


# ---- RFQ ----------------------------------------------------------------------------------------

class FollowupSpec(InputModel):
    action: Annotated[str, Field(min_length=1, max_length=1000)]
    due_on: date


class RfqItemIn(InputModel):
    line_item_id: uuid.UUID
    quantity: Quantity | None = None
    unit_code: Code | None = None
    unit_text: Text300 | None = None
    note: Text500 | None = None


class RecipientIn(InputModel):
    party_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    channel: RfqChannel | None = None
    language: Lang | None = None
    template_id: uuid.UUID | None = None


class RfqCreate(InputModel):
    case_id: uuid.UUID
    title: Text500 | None = None
    language: Lang = "en"
    respond_by: date | None = None
    notes: LongText | None = None
    items: list[RfqItemIn] = Field(min_length=1, max_length=500)
    recipients: list[RecipientIn] = Field(default_factory=list, max_length=200)


class RfqPatch(InputModel):
    title: Text500 | None = None
    language: Lang | None = None
    respond_by: date | None = None
    notes: LongText | None = None
    items: list[RfqItemIn] | None = Field(default=None, min_length=1, max_length=500)


class RecipientPatch(InputModel):
    channel: RfqChannel | None = None
    language: Lang | None = None
    contact_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    subject: Text500 | None = None
    message_text: RawText | None = None
    rerender: bool = False


class MarkSentIn(InputModel):
    sent_at: datetime | None = None
    subject: Text500 | None = None
    message_text: RawText | None = None
    followup: FollowupSpec | None = None
    no_followup_reason: Text500 | None = None


class NoteIn(InputModel):
    note: Text500 | None = None


class TemplateIn(InputModel):
    language: Lang
    channel: TemplateChannel
    name: Annotated[str, Field(min_length=1, max_length=200)]
    subject_template: Text500 = ""
    body_template: Annotated[str, Field(min_length=1, max_length=20000)]
    is_default: bool = False


class TemplatePatch(InputModel):
    language: Lang | None = None
    channel: TemplateChannel | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    subject_template: Text500 | None = None
    body_template: Annotated[str, Field(min_length=1, max_length=20000)] | None = None
    is_default: bool | None = None
    status: Literal["active", "archived"] | None = None


class TemplatePreviewIn(InputModel):
    subject_template: Text500 = ""
    body_template: Annotated[str, Field(min_length=1, max_length=20000)]
    language: Lang = "en"


# ---- offers -------------------------------------------------------------------------------------

class OfferItemIn(InputModel):
    line_item_id: uuid.UUID
    available: bool = True
    unit_price: Amount | None = None
    price_per_quantity: Quantity = Decimal(1)
    unit_code: Code | None = None
    unit_text: Text300 | None = None
    moq: Quantity | None = None
    moq_unit: Text300 | None = None
    lead_time_days: Annotated[int, Field(ge=0, le=3650)] | None = None
    spec_deviation: LongText | None = None
    packaging: Text500 | None = None
    notes: LongText | None = None


class OfferHeader(InputModel):
    contact_id: uuid.UUID | None = None
    received_at: datetime | None = None
    channel: OfferChannel | None = None
    valid_until: date | None = None
    currency: Currency | None = None
    incoterm: Incoterm | None = None
    incoterm_place: Text300 | None = None
    payment_terms: Text500 | None = None
    lead_time_days: Annotated[int, Field(ge=0, le=3650)] | None = None
    compliance_notes: LongText | None = None
    notes: LongText | None = None


class OfferCreate(OfferHeader):
    case_id: uuid.UUID
    party_id: uuid.UUID
    rfq_recipient_id: uuid.UUID | None = None
    channel: OfferChannel
    currency: Currency
    raw_text: RawText | None = None
    items: list[OfferItemIn] = Field(min_length=1, max_length=500)
    followup: FollowupSpec | None = None
    no_followup_reason: Text500 | None = None
    supersedes_offer_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class OfferItemPatch(InputModel):
    available: bool | None = None
    unit_price: Amount | None = None
    price_per_quantity: Quantity | None = None
    unit_code: Code | None = None
    unit_text: Text300 | None = None
    moq: Quantity | None = None
    moq_unit: Text300 | None = None
    lead_time_days: Annotated[int, Field(ge=0, le=3650)] | None = None
    spec_deviation: LongText | None = None
    packaging: Text500 | None = None
    notes: LongText | None = None


class OfferStatusIn(InputModel):
    status: Literal["active", "withdrawn"]
    note: Text500 | None = None


class SelectOfferIn(InputModel):
    offer_item_id: uuid.UUID | None
    reason: Text500 | None = None


# ---- capabilities -------------------------------------------------------------------------------

class CapabilityIn(InputModel):
    kind: Literal["hs", "isic", "tag"]
    code: Annotated[str, Field(max_length=20)] | None = None
    tag_text: Annotated[str, Field(max_length=200)] | None = None
    notes: Text500 | None = None


class CapabilitySet(InputModel):
    items: list[CapabilityIn] = Field(max_length=500)


class ProductFromItemIn(InputModel):
    confirm_duplicate: bool = False
    name_fa: Text500 | None = None
    name_en: Text500 | None = None
