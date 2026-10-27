"""Request models of the quotes module. Every request body forbids unknown fields."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from app.core.schemas import InputModel
from app.modules.sourcing.schemas import Amount, Currency, Incoterm, LongText, Text300, Text500

Days = Annotated[int, Field(ge=0, le=3650)]


class FollowupSpec(InputModel):
    action: Annotated[str, Field(min_length=1, max_length=500)]
    due_on: date


class QuoteCreate(InputModel):
    case_id: uuid.UUID
    cost_sheet_id: uuid.UUID | None = None
    language: Literal["fa", "en"] | None = None
    price_basis: Literal["before_vat", "with_vat"] | None = None
    valid_until: date | None = None
    incoterm: Incoterm | None = None
    incoterm_place: Text300 | None = None
    payment_terms: Text500 | None = None
    delivery_terms: Text500 | None = None
    lead_time_days: Days | None = None
    terms_text: LongText | None = None
    notes: LongText | None = None
    buyer_party_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None


class QuotePatch(InputModel):
    language: Literal["fa", "en"] | None = None
    price_basis: Literal["before_vat", "with_vat"] | None = None
    valid_until: date | None = None
    incoterm: Incoterm | None = None
    incoterm_place: Text300 | None = None
    payment_terms: Text500 | None = None
    delivery_terms: Text500 | None = None
    lead_time_days: Days | None = None
    terms_text: LongText | None = None
    notes: LongText | None = None
    buyer_party_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None


class QuoteItemPatch(InputModel):
    description_override: Annotated[str, Field(max_length=2000)] | None = None
    unit_price: Amount | None = None
    lead_time_days: Days | None = None
    note: Text500 | None = None


class MarkSentIn(InputModel):
    channel: Literal["email", "whatsapp", "phone", "in_person", "letter", "other"] = "email"
    sent_at: datetime | None = None
    followup: FollowupSpec | None = None
    no_followup_reason: Text500 | None = None
    move_to_quoted: bool = True


class ReasonIn(InputModel):
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ReviseIn(InputModel):
    cost_sheet_id: uuid.UUID | None = None
    valid_until: date | None = None


class OutcomeIn(InputModel):
    quote_item_id: uuid.UUID
    outcome: Literal["accepted", "rejected", "no_reply", "negotiating"] | None = None
    outcome_reason: Annotated[str, Field(max_length=40)] | None = None
    outcome_note: Text500 | None = None
    competitor_price: Amount | None = None
    competitor_currency: Currency | None = None
    decided_on: date | None = None


class OutcomesIn(InputModel):
    items: list[OutcomeIn] = Field(min_length=1, max_length=500)


class OutputIn(InputModel):
    format: Literal["pdf", "docx"]


class CaseResultIn(InputModel):
    result: Literal["won", "lost"]
