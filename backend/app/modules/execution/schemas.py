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
