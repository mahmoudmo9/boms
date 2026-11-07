"""Tables of the finance module (schema ``ops``, migration 0015)."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.modules.parties.models import TZ, Timestamps, _id

AMOUNT = Numeric(20, 4)
RATE = Numeric(20, 6)


class InvoiceSequence(Timestamps, Base):
    __tablename__ = "invoice_sequence"
    __table_args__ = {"schema": "ops"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer)


class SalesInvoice(Timestamps, Base):
    __tablename__ = "sales_invoice"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(UUID)
    number: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, default="invoice")
    corrects_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    language: Mapped[str] = mapped_column(Text)
    customer_party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    issue_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(Text)
    price_basis: Mapped[str] = mapped_column(Text, default="before_vat")
    subtotal: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    discount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    vat_note: Mapped[str | None] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    status: Mapped[str] = mapped_column(Text, default="draft")
    issued_at: Mapped[datetime | None] = mapped_column(TZ)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    over_delivered_reason: Mapped[str | None] = mapped_column(Text)
    moadian_tax_id: Mapped[str | None] = mapped_column(Text)
    moadian_status: Mapped[str] = mapped_column(Text, default="not_required")
    moadian_on: Mapped[date | None] = mapped_column(Date)
    moadian_note: Mapped[str | None] = mapped_column(Text)
    incoterm: Mapped[str | None] = mapped_column(Text)
    incoterm_place: Mapped[str | None] = mapped_column(Text)
    country_of_origin: Mapped[str | None] = mapped_column(Text)
    shipping_marks: Mapped[str | None] = mapped_column(Text)
    gross_weight: Mapped[str | None] = mapped_column(Text)
    net_weight: Mapped[str | None] = mapped_column(Text)
    packages: Mapped[str | None] = mapped_column(Text)
    transport_doc_no: Mapped[str | None] = mapped_column(Text)
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    notes: Mapped[str | None] = mapped_column(Text)


class SalesInvoiceLine(Timestamps, Base):
    __tablename__ = "sales_invoice_line"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.sales_invoice.id"))
    sales_order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    unit: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    discount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(AMOUNT)
    hs_code: Mapped[str | None] = mapped_column(Text)


class PurchaseInvoice(Timestamps, Base):
    __tablename__ = "purchase_invoice"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    supplier_party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    supplier_invoice_no: Mapped[str] = mapped_column(Text)
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    status: Mapped[str] = mapped_column(Text, default="received")
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    difference_reason: Mapped[str | None] = mapped_column(Text)
    dispute_reason: Mapped[str | None] = mapped_column(Text)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    notes: Mapped[str | None] = mapped_column(Text)


class PurchaseInvoiceLine(Timestamps, Base):
    __tablename__ = "purchase_invoice_line"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    purchase_invoice_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.purchase_invoice.id"))
    purchase_order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    total: Mapped[Decimal] = mapped_column(AMOUNT)


class ActualCost(Timestamps, Base):
    __tablename__ = "actual_cost"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    kind: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    amount: Mapped[Decimal] = mapped_column(AMOUNT)
    currency: Mapped[str] = mapped_column(Text)
    fx_rate_to_base: Mapped[Decimal | None] = mapped_column(RATE)
    base_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    vat_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    incurred_on: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    status: Mapped[str] = mapped_column(Text, default="incurred")
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    notes: Mapped[str | None] = mapped_column(Text)


class PaymentAllocation(Timestamps, Base):
    __tablename__ = "payment_allocation"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    payment_record_id: Mapped[uuid.UUID] = mapped_column(UUID)
    sales_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    purchase_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    actual_cost_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    amount: Mapped[Decimal] = mapped_column(AMOUNT)
    fx_rate: Mapped[Decimal | None] = mapped_column(RATE)
    target_amount: Mapped[Decimal] = mapped_column(AMOUNT)
    note: Mapped[str | None] = mapped_column(Text)


class DealResult(Timestamps, Base):
    __tablename__ = "deal_result"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reasons: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    computed_at: Mapped[datetime] = mapped_column(TZ)
    closed_by: Mapped[str | None] = mapped_column(Text)


class PartyRating(Timestamps, Base):
    __tablename__ = "party_rating"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    role: Mapped[str] = mapped_column(Text)
    quality: Mapped[int | None] = mapped_column(Integer)
    timeliness: Mapped[int | None] = mapped_column(Integer)
    communication: Mapped[int | None] = mapped_column(Integer)
    price: Mapped[int | None] = mapped_column(Integer)
    payment_behavior: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
