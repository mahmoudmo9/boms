"""Request models of the execution module (every body forbids unknown fields)."""
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
Positive = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=4)]
Percent = Annotated[Decimal, Field(gt=0, le=100, max_digits=9, decimal_places=4)]
Language = Literal["fa", "en"]
PriceBasis = Literal["before_vat", "with_vat"]
MilestoneKind = Literal["prepayment", "on_order_confirmation", "on_shipment", "on_delivery", "balance", "retention", "other"]
OutputFormat = Literal["pdf", "docx"]


# ---- sales orders --------------------------------------------------------------------------------------------------

class SalesOrderHead(InputModel):
    customer_party_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    customer_ref: Text300 | None = None
    contract_date: date | None = None
    delivery_due_on: date | None = None
    delivery_place: Text300 | None = None
    warranty_months: Annotated[int, Field(ge=0, le=600)] | None = None
    payment_terms: Text2000 | None = None
    delivery_terms: Text2000 | None = None
    notes: LongText | None = None


class SalesOrderFromQuote(SalesOrderHead):
    quote_id: uuid.UUID


class SalesOrderFromProposal(SalesOrderHead):
    tender_proposal_id: uuid.UUID


class SalesOrderManual(SalesOrderHead):
    currency: Currency | None = None
    price_basis: PriceBasis | None = None
    incoterm: Text300 | None = None
    incoterm_place: Text300 | None = None


class SalesOrderPatch(InputModel):
    contact_id: uuid.UUID | None = None
    customer_ref: Text300 | None = None
    contract_date: date | None = None
    signed_document_id: uuid.UUID | None = None
    delivery_place: Text300 | None = None
    warranty_months: Annotated[int, Field(ge=0, le=600)] | None = None
    performance_guarantee_id: uuid.UUID | None = None
    notes: LongText | None = None
    price_basis: PriceBasis | None = None
    incoterm: Text300 | None = None
    incoterm_place: Text300 | None = None
    payment_terms: Text2000 | None = None
    delivery_terms: Text2000 | None = None
    delivery_due_on: date | None = None


class SalesOrderItemPatch(InputModel):
    description: Text2000 | None = None
    quantity: Positive | None = None
    unit: Text300 | None = None
    unit_price: Amount | None = None
    delivery_due_on: date | None = None


class ConfirmIn(InputModel):
    signed_document_id: uuid.UUID | None = None
    no_document_reason: Text2000 | None = None


class AmendItem(InputModel):
    sales_order_item_id: uuid.UUID
    quantity: Positive | None = None
    unit_price: Amount | None = None
    delivery_due_on: date | None = None


class AmendIn(InputModel):
    reason: Text2000
    document_id: uuid.UUID | None = None
    changes: dict[Literal["price_basis", "incoterm", "incoterm_place", "payment_terms", "delivery_terms",
                          "delivery_due_on"], str | date | None] = {}
    items: list[AmendItem] = []


class ReasonIn(InputModel):
    reason: Text2000


class OutputIn(InputModel):
    format: OutputFormat
    language: Language | None = None


# ---- milestones -----------------------------------------------------------------------------------------------------

class MilestoneIn(InputModel):
    case_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    direction: Literal["in", "out"] | None = None
    party_id: uuid.UUID | None = None
    kind: MilestoneKind
    label: Text300 | None = None
    position: Annotated[int, Field(ge=0, le=10000)] | None = None
    percent: Percent | None = None
    amount: Amount | None = None
    amount_currency: Currency | None = None
    due_on: date | None = None
    due_event: Text300 | None = None
    method: Text300 | None = None
    reference: Text300 | None = None
    receipt_document_id: uuid.UUID | None = None
    note: Text2000 | None = None


class MilestonePatch(InputModel):
    party_id: uuid.UUID | None = None
    kind: MilestoneKind | None = None
    label: Text300 | None = None
    position: Annotated[int, Field(ge=0, le=10000)] | None = None
    percent: Percent | None = None
    amount: Amount | None = None
    amount_currency: Currency | None = None
    due_on: date | None = None
    due_event: Text300 | None = None
    method: Text300 | None = None
    reference: Text300 | None = None
    receipt_document_id: uuid.UUID | None = None
    note: Text2000 | None = None


class PaymentIn(InputModel):
    amount: Positive
    amount_currency: Currency | None = None
    paid_on: date
    method: Text300 | None = None
    reference: Text300 | None = None
    document_id: uuid.UUID | None = None
    note: Text2000 | None = None


__all__ = ["AmendIn", "ConfirmIn", "MilestoneIn", "MilestonePatch", "OutputIn", "PaymentIn", "ReasonIn",
           "SalesOrderFromProposal", "SalesOrderFromQuote", "SalesOrderItemPatch", "SalesOrderManual",
           "SalesOrderPatch", "datetime"]


# ---- purchase orders -------------------------------------------------------------------------------------------------

class PurchaseOrderPatch(InputModel):
    contact_id: uuid.UUID | None = None
    language: Language | None = None
    incoterm: Text300 | None = None
    incoterm_place: Text300 | None = None
    payment_terms: Text2000 | None = None
    delivery_terms: Text2000 | None = None
    ready_due_on: date | None = None
    delivery_place: Text300 | None = None
    direct_to_customer: bool | None = None
    terms_text: LongText | None = None
    notes: LongText | None = None


class PurchaseOrderItemPatch(InputModel):
    description: Text2000 | None = None
    quantity: Positive | None = None
    unit: Text300 | None = None
    unit_price: Amount | None = None


class PoApproveIn(InputModel):
    confirm_above_cost: bool = False
    reason: Text2000 | None = None


class PoSentIn(InputModel):
    channel: Literal["email", "whatsapp", "phone", "in_person", "letter", "other"] = "email"
    sent_at: datetime | None = None
    confirm_without_prepayment: bool = False
    reason: Text2000 | None = None


class PoConfirmIn(InputModel):
    supplier_ref: Text300 | None = None
    confirmed_ready_on: date | None = None
    confirmation_document_id: uuid.UUID | None = None
    confirmed_at: datetime | None = None


class PoReadyDateIn(InputModel):
    ready_due_on: date
    reason: Text2000
    document_id: uuid.UUID | None = None


class PoStatusIn(InputModel):
    status: Literal["in_production", "ready", "shipped", "closed"]
    note: Text2000 | None = None
    on_date: date | None = None


# ---- process checklists ------------------------------------------------------------------------------------------------

DealType = Literal["import", "export", "domestic"]
StepStatus = Literal["pending", "in_progress", "done", "not_applicable"]
DayOffsets = Annotated[list[Annotated[int, Field(ge=0, le=365)]], Field(max_length=10)]


class TemplateStepIn(InputModel):
    group: Text300 | None = None
    code: Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")]
    label_fa: Annotated[str, Field(min_length=1, max_length=300)]
    label_en: Annotated[str, Field(min_length=1, max_length=300)]
    reference_label: Text300 | None = None
    requires_document: bool = False
    default_offset_days: Annotated[int, Field(ge=-365, le=3650)] | None = None


class ProcessTemplateIn(InputModel):
    deal_type: DealType
    name: Annotated[str, Field(min_length=1, max_length=200)]
    is_default: bool = False
    steps: list[TemplateStepIn] = []


class ProcessTemplatePatch(InputModel):
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    is_default: bool | None = None
    status: Literal["active", "archived"] | None = None
    steps: list[TemplateStepIn] | None = None


class ProcessIn(InputModel):
    deal_type: DealType | None = None
    template_id: uuid.UUID | None = None
    base_date: date | None = None
    sales_order_id: uuid.UUID | None = None


class StepPatch(InputModel):
    status: StepStatus | None = None
    reference: Text300 | None = None
    started_on: date | None = None
    done_on: date | None = None
    due_on: date | None = None
    remind_days_before: DayOffsets | None = None
    document_id: uuid.UUID | None = None
    no_document_reason: Text2000 | None = None
    shipment_id: uuid.UUID | None = None
    note: Text2000 | None = None
    label_fa: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    label_en: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    reference_label: Text300 | None = None
    requires_document: bool | None = None


class StepIn(InputModel):
    label_fa: Annotated[str, Field(min_length=1, max_length=300)]
    label_en: Annotated[str, Field(max_length=300)] | None = None
    code: Annotated[str, Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")] | None = None
    group: Text300 | None = None
    reference_label: Text300 | None = None
    requires_document: bool = False
    due_on: date | None = None
    remind_days_before: DayOffsets | None = None


class StepOrderIn(InputModel):
    step_ids: list[uuid.UUID]
