"""Request models of the finance module (every body forbids unknown fields)."""
import uuid
from datetime import date
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
Rate = Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=6)]
VatRate = Annotated[Decimal, Field(ge=0, le=100, max_digits=7, decimal_places=4)]
Language = Literal["fa", "en"]
Moadian = Literal["not_required", "not_sent", "sent", "accepted", "rejected"]


# ---- sales invoices -------------------------------------------------------------------------------------------------

class InvoiceLineIn(InputModel):
    sales_order_item_id: uuid.UUID | None = None
    description: Text300 | None = None
    quantity: Positive
    unit: Annotated[str, Field(max_length=40)] | None = None
    unit_price: Amount | None = None
    discount: Amount | None = None
    hs_code: Annotated[str, Field(max_length=20)] | None = None


class InvoiceHead(InputModel):
    issue_date: date | None = None
    due_date: date | None = None
    language: Language | None = None
    discount: Amount | None = None
    incoterm: Annotated[str, Field(max_length=10)] | None = None
    incoterm_place: Text300 | None = None
    country_of_origin: Text300 | None = None
    shipping_marks: Text2000 | None = None
    gross_weight: Text300 | None = None
    net_weight: Text300 | None = None
    packages: Text300 | None = None
    transport_doc_no: Text300 | None = None
    shipment_id: uuid.UUID | None = None
    notes: LongText | None = None
    over_delivered_reason: Text2000 | None = None


class SalesInvoiceIn(InvoiceHead):
    sales_order_id: uuid.UUID
    lines: list[InvoiceLineIn] | None = Field(default=None, max_length=500)


class SalesInvoicePatch(InvoiceHead):
    vat_rate: VatRate | None = None
    vat_note: Text2000 | None = None
    lines: list[InvoiceLineIn] | None = Field(default=None, max_length=500)


class IssueIn(InputModel):
    issue_date: date | None = None
    vat_decision: Literal["apply", "zero"] | None = None     # v0.9.0: answers vat_decision_required
    vat_reason: Text300 | None = None


class NoteIn(InputModel):
    reason: Text2000
    issue_date: date | None = None
    due_date: date | None = None
    lines: list[InvoiceLineIn] = Field(min_length=1, max_length=500)


class MoadianIn(InputModel):
    moadian_status: Moadian | None = None
    moadian_tax_id: Annotated[str, Field(max_length=64)] | None = None
    moadian_on: date | None = None
    moadian_note: Text2000 | None = None


class ReasonIn(InputModel):
    reason: Text2000


class OutputIn(InputModel):
    format: Literal["pdf", "docx"]


# ---- supplier invoices -----------------------------------------------------------------------------------------------

class PurchaseLineIn(InputModel):
    purchase_order_item_id: uuid.UUID | None = None
    description: Text300 | None = None
    quantity: Positive
    unit_price: Amount | None = None


class PurchaseInvoiceIn(InputModel):
    purchase_order_id: uuid.UUID | None = None
    case_id: uuid.UUID | None = None
    supplier_party_id: uuid.UUID | None = None
    supplier_invoice_no: Annotated[str, Field(min_length=1, max_length=100)]
    invoice_date: date
    due_date: date | None = None
    currency: Currency | None = None
    vat_amount: Amount | None = None
    document_id: uuid.UUID | None = None
    notes: LongText | None = None
    lines: list[PurchaseLineIn] | None = Field(default=None, max_length=500)


class PurchaseInvoicePatch(InputModel):
    supplier_invoice_no: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    vat_amount: Amount | None = None
    document_id: uuid.UUID | None = None
    notes: LongText | None = None
    lines: list[PurchaseLineIn] | None = Field(default=None, max_length=500)


class ApproveIn(InputModel):
    reason: Text2000 | None = None


class DisputeIn(InputModel):
    reason: Text2000
    claim_id: uuid.UUID | None = None


# ---- payments and actual costs ----------------------------------------------------------------------------------------

class AllocationIn(InputModel):
    sales_invoice_id: uuid.UUID | None = None
    purchase_invoice_id: uuid.UUID | None = None
    actual_cost_id: uuid.UUID | None = None
    amount: Positive
    fx_rate: Rate | None = None
    note: Text2000 | None = None


class AllocationsIn(InputModel):
    allocations: list[AllocationIn] = Field(min_length=1, max_length=100)


CostKind = Literal["freight_international", "insurance", "bank_fees", "customs_duty", "levy", "customs_clearance",
                   "storage", "inspection", "freight_domestic", "export_clearance", "other"]


class ActualCostIn(InputModel):
    kind: CostKind
    description: Annotated[str, Field(min_length=1, max_length=500)]
    party_id: uuid.UUID | None = None
    amount: Positive
    currency: Currency
    fx_rate_to_base: Rate | None = None
    vat_amount: Amount | None = None
    incurred_on: date | None = None
    due_date: date | None = None
    document_id: uuid.UUID | None = None
    status: Literal["expected", "incurred"] = "incurred"
    shipment_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    notes: LongText | None = None


class ActualCostPatch(InputModel):
    kind: CostKind | None = None
    description: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    party_id: uuid.UUID | None = None
    amount: Positive | None = None
    currency: Currency | None = None
    fx_rate_to_base: Rate | None = None
    vat_amount: Amount | None = None
    incurred_on: date | None = None
    due_date: date | None = None
    document_id: uuid.UUID | None = None
    status: Literal["expected", "incurred"] | None = None
    shipment_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    notes: LongText | None = None


# ---- closing and ratings ----------------------------------------------------------------------------------------------

class CloseIn(InputModel):
    reasons: dict[Annotated[str, Field(max_length=60)], Text2000] = Field(default_factory=dict)
    confirm_cancel_open: bool = False


Score = Annotated[int, Field(ge=1, le=5)]


class RatingIn(InputModel):
    party_id: uuid.UUID
    role: Literal["supplier", "customer"]
    quality: Score | None = None
    timeliness: Score | None = None
    communication: Score | None = None
    price: Score | None = None
    payment_behavior: Score | None = None
    note: Annotated[str, Field(max_length=300)] | None = None
