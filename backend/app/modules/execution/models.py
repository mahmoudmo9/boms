"""Execution and shipping tables (schema ``ops``, migration 0013)."""
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


class SalesOrder(Timestamps, Base):
    __tablename__ = "sales_order"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    number: Mapped[str] = mapped_column(Text)
    customer_party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    source: Mapped[str] = mapped_column(Text)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    tender_proposal_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    customer_ref: Mapped[str | None] = mapped_column(Text)
    contract_date: Mapped[date | None] = mapped_column(Date)
    signed_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    currency: Mapped[str] = mapped_column(Text)
    price_basis: Mapped[str] = mapped_column(Text, default="before_vat")
    incoterm: Mapped[str | None] = mapped_column(Text)
    incoterm_place: Mapped[str | None] = mapped_column(Text)
    incoterm_place_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID)   # v0.9.0
    payment_terms: Mapped[str | None] = mapped_column(Text)
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    delivery_due_on: Mapped[date | None] = mapped_column(Date)
    delivery_place: Mapped[str | None] = mapped_column(Text)
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    performance_guarantee_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    status: Mapped[str] = mapped_column(Text, default="draft")
    subtotal: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    confirmed_at: Mapped[datetime | None] = mapped_column(TZ)
    no_document_reason: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(TZ)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class SalesOrderItem(Timestamps, Base):
    __tablename__ = "sales_order_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    sales_order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.sales_order.id"))
    line_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    unit: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    total: Mapped[Decimal] = mapped_column(AMOUNT)
    vat_amount: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    delivery_due_on: Mapped[date | None] = mapped_column(Date)


class SalesOrderChange(Timestamps, Base):
    __tablename__ = "sales_order_change"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    sales_order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.sales_order.id"))
    sales_order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    field: Mapped[str] = mapped_column(Text)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class PurchaseOrder(Timestamps, Base):
    __tablename__ = "purchase_order"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    number: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    supplier_party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    language: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    incoterm: Mapped[str | None] = mapped_column(Text)
    incoterm_place: Mapped[str | None] = mapped_column(Text)
    incoterm_place_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID)   # v0.9.0
    payment_terms: Mapped[str | None] = mapped_column(Text)
    delivery_terms: Mapped[str | None] = mapped_column(Text)
    ready_due_on: Mapped[date | None] = mapped_column(Date)
    delivery_place: Mapped[str | None] = mapped_column(Text)
    direct_to_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="draft")
    subtotal: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    total: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    price_override_reason: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(TZ)
    interaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    prepayment_override_reason: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(TZ)
    supplier_ref: Mapped[str | None] = mapped_column(Text)
    confirmed_ready_on: Mapped[date | None] = mapped_column(Date)
    confirmation_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    ready_on: Mapped[date | None] = mapped_column(Date)
    status_note: Mapped[str | None] = mapped_column(Text)
    terms_text: Mapped[str | None] = mapped_column(Text)
    terms_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class PurchaseOrderItem(Timestamps, Base):
    __tablename__ = "purchase_order_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.purchase_order.id"))
    line_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    sales_order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    offer_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    unit: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(AMOUNT)
    total: Mapped[Decimal] = mapped_column(AMOUNT)
    received_quantity: Mapped[Decimal] = mapped_column(AMOUNT, default=Decimal(0))


class PurchaseOrderChange(Timestamps, Base):
    __tablename__ = "purchase_order_change"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.purchase_order.id"))
    field: Mapped[str] = mapped_column(Text)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)


class PaymentMilestone(Timestamps, Base):
    __tablename__ = "payment_milestone"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    direction: Mapped[str] = mapped_column(Text)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    party_id: Mapped[uuid.UUID] = mapped_column(UUID)
    kind: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    amount_currency: Mapped[str | None] = mapped_column(Text)
    due_on: Mapped[date | None] = mapped_column(Date)
    due_event: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="expected")
    actual_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    actual_amount_currency: Mapped[str | None] = mapped_column(Text)
    actual_on: Mapped[date | None] = mapped_column(Date)
    method: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class PaymentRecord(Timestamps, Base):
    __tablename__ = "payment_record"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str | None] = mapped_column(Text)     # v0.9.0: the record's code (codes module)
    milestone_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.payment_milestone.id"))
    amount: Mapped[Decimal] = mapped_column(AMOUNT)
    amount_currency: Mapped[str] = mapped_column(Text)
    paid_on: Mapped[date] = mapped_column(Date)
    method: Mapped[str | None] = mapped_column(Text)
    reference: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    note: Mapped[str | None] = mapped_column(Text)
    # v0.8.0: the real rate of a foreign-currency payment and its rial amount; a bank fee becomes an actual cost
    fx_rate_to_base: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    base_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    rate_source: Mapped[str | None] = mapped_column(Text)
    bank_fee: Mapped[Decimal | None] = mapped_column(AMOUNT)
    bank_fee_currency: Mapped[str | None] = mapped_column(Text)


class ProcessTemplate(Timestamps, Base):
    __tablename__ = "process_template"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    deal_type: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="active")


class ProcessTemplateStep(Timestamps, Base):
    __tablename__ = "process_template_step"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    template_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.process_template.id"))
    position: Mapped[int] = mapped_column(Integer)
    group: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    reference_label: Mapped[str | None] = mapped_column(Text)
    requires_document: Mapped[bool] = mapped_column(Boolean, default=False)
    default_offset_days: Mapped[int | None] = mapped_column(Integer)


class Process(Timestamps, Base):
    __tablename__ = "process"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    deal_type: Mapped[str] = mapped_column(Text)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    name: Mapped[str] = mapped_column(Text)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    base_date: Mapped[date | None] = mapped_column(Date)


class ProcessStep(Timestamps, Base):
    __tablename__ = "process_step"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    process_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.process.id"))
    position: Mapped[int] = mapped_column(Integer)
    group: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    label_fa: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    reference_label: Mapped[str | None] = mapped_column(Text)
    requires_document: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="pending")
    reference: Mapped[str | None] = mapped_column(Text)
    started_on: Mapped[date | None] = mapped_column(Date)
    done_on: Mapped[date | None] = mapped_column(Date)
    due_on: Mapped[date | None] = mapped_column(Date)
    remind_days_before: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=lambda: [3, 1])
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    no_document_reason: Mapped[str | None] = mapped_column(Text)
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    note: Mapped[str | None] = mapped_column(Text)


class Shipment(Timestamps, Base):
    __tablename__ = "shipment"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str | None] = mapped_column(Text)     # v0.9.0: the record's code (codes module)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    direction: Mapped[str] = mapped_column(Text)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    mode: Mapped[str] = mapped_column(Text, default="sea")
    carrier_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    forwarder_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    transport_doc_kind: Mapped[str | None] = mapped_column(Text)
    transport_doc_no: Mapped[str | None] = mapped_column(Text)
    containers: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    vessel_or_flight: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str | None] = mapped_column(Text)
    destination: Mapped[str | None] = mapped_column(Text)
    incoterm: Mapped[str | None] = mapped_column(Text)
    etd: Mapped[date | None] = mapped_column(Date)
    eta: Mapped[date | None] = mapped_column(Date)
    first_eta: Mapped[date | None] = mapped_column(Date)
    atd: Mapped[date | None] = mapped_column(Date)
    ata: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="planned")
    insurer_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    policy_no: Mapped[str | None] = mapped_column(Text)
    insured_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    insured_amount_currency: Mapped[str | None] = mapped_column(Text)
    origin_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID)        # v0.9.0: UN/LOCODE
    destination_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    notes: Mapped[str | None] = mapped_column(Text)


class ShipmentItem(Timestamps, Base):
    __tablename__ = "shipment_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    shipment_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.shipment.id"))
    purchase_order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    sales_order_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)


class ShipmentEvent(Timestamps, Base):
    __tablename__ = "shipment_event"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    shipment_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.shipment.id"))
    at: Mapped[datetime] = mapped_column(TZ)
    kind: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID)   # v0.9.0: a transshipment port


class ShipmentContainer(Timestamps, Base):
    """v0.9.0: a container number (ISO 6346, check digit validated) with its size/type code."""
    __tablename__ = "shipment_container"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    shipment_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.shipment.id"))
    number: Mapped[str] = mapped_column(Text)
    container_type: Mapped[str | None] = mapped_column(Text)
    seal_no: Mapped[str | None] = mapped_column(Text)


class ShipmentDocument(Timestamps, Base):
    __tablename__ = "shipment_document"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    shipment_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.shipment.id"))
    kind: Mapped[str] = mapped_column(Text)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID)
    number: Mapped[str | None] = mapped_column(Text)
    issued_on: Mapped[date | None] = mapped_column(Date)


class Inspection(Timestamps, Base):
    __tablename__ = "inspection"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str | None] = mapped_column(Text)     # v0.9.0: the record's code (codes module)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    kind: Mapped[str] = mapped_column(Text)
    inspector_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    planned_on: Mapped[date | None] = mapped_column(Date)
    done_on: Mapped[date | None] = mapped_column(Date)
    result: Mapped[str] = mapped_column(Text, default="pending")
    report_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    items: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    notes: Mapped[str | None] = mapped_column(Text)


class Receipt(Timestamps, Base):
    __tablename__ = "receipt"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str | None] = mapped_column(Text)     # v0.9.0: the record's code (codes module)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.purchase_order.id"))
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    received_on: Mapped[date] = mapped_column(Date)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    note: Mapped[str | None] = mapped_column(Text)


class ReceiptItem(Timestamps, Base):
    __tablename__ = "receipt_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.receipt.id"))
    purchase_order_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)
    condition: Mapped[str] = mapped_column(Text, default="ok")
    note: Mapped[str | None] = mapped_column(Text)


class Delivery(Timestamps, Base):
    __tablename__ = "delivery"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str | None] = mapped_column(Text)     # v0.9.0: the record's code (codes module)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.sales_order.id"))
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    delivered_on: Mapped[date] = mapped_column(Date)
    delivery_place: Mapped[str | None] = mapped_column(Text)
    receiver_name: Mapped[str | None] = mapped_column(Text)
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    note: Mapped[str | None] = mapped_column(Text)


class DeliveryItem(Timestamps, Base):
    __tablename__ = "delivery_item"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    delivery_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("ops.delivery.id"))
    sales_order_item_id: Mapped[uuid.UUID] = mapped_column(UUID)
    quantity: Mapped[Decimal] = mapped_column(AMOUNT)


class Claim(Timestamps, Base):
    __tablename__ = "claim"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    code: Mapped[str | None] = mapped_column(Text)     # v0.9.0: the record's code (codes module)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    direction: Mapped[str] = mapped_column(Text)
    counterparty_id: Mapped[uuid.UUID] = mapped_column(UUID)
    kind: Mapped[str] = mapped_column(Text)
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    shipment_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    receipt_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    items: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    claimed_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    claimed_amount_currency: Mapped[str | None] = mapped_column(Text)
    opened_on: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, default="open")
    resolution: Mapped[str | None] = mapped_column(Text)
    resolution_amount: Mapped[Decimal | None] = mapped_column(AMOUNT)
    resolution_amount_currency: Mapped[str | None] = mapped_column(Text)
    resolved_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class ExecutionFollowup(Timestamps, Base):
    __tablename__ = "execution_followup"
    __table_args__ = {"schema": "ops"}

    id: Mapped[uuid.UUID] = _id()
    case_id: Mapped[uuid.UUID] = mapped_column(UUID)
    followup_id: Mapped[uuid.UUID] = mapped_column(UUID)
    purpose: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    days_before: Mapped[int | None] = mapped_column(Integer)
