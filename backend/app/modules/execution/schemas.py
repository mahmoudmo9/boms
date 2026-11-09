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
    incoterm_place_location_id: uuid.UUID | None = None   # v0.9.0: UN/LOCODE place


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
    incoterm_place_location_id: uuid.UUID | None = None   # v0.9.0: UN/LOCODE place
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
    changes: dict[Literal["price_basis", "incoterm", "incoterm_place", "incoterm_place_location_id", "payment_terms", "delivery_terms",
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
    # v0.8.0: the real rate to the base currency (required for a foreign currency), its source, the bank fee
    fx_rate_to_base: Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=6)] | None = None
    rate_source: Text300 | None = None
    bank_fee: Amount | None = None
    bank_fee_currency: Currency | None = None


class PaymentRecordPatch(InputModel):
    fx_rate_to_base: Annotated[Decimal, Field(gt=0, max_digits=20, decimal_places=6)] | None = None
    rate_source: Text300 | None = None
    bank_fee: Amount | None = None
    bank_fee_currency: Currency | None = None
    method: Text300 | None = None
    reference: Text300 | None = None
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
    incoterm_place_location_id: uuid.UUID | None = None   # v0.9.0: UN/LOCODE place
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


# ---- shipments, inspections, receipts (M3) ------------------------------------------------------------------------------

Mode = Literal["sea", "air", "road", "rail", "courier", "domestic_truck", "other"]
DocKind = Literal["bl", "awb", "cmr", "waybill", "other"]
ShipmentStatus = Literal["planned", "booked", "in_transit", "arrived", "at_customs", "cleared", "delivered", "cancelled"]
ShipmentDocKind = Literal["commercial_invoice", "packing_list", "bl", "awb", "cmr", "certificate_of_origin",
                          "inspection_certificate", "insurance_policy", "customs_declaration", "other"]


class ShipmentItemIn(InputModel):
    purchase_order_item_id: uuid.UUID | None = None
    sales_order_item_id: uuid.UUID | None = None
    quantity: Positive


class ContainerIn(InputModel):
    number: Annotated[str, Field(min_length=11, max_length=15)]
    container_type: Annotated[str, Field(pattern=r"^[0-9A-Z]{4}$")] | None = None
    seal_no: Annotated[str, Field(max_length=40)] | None = None


class ShipmentBase(InputModel):
    mode: Mode | None = None
    carrier_party_id: uuid.UUID | None = None
    forwarder_party_id: uuid.UUID | None = None
    transport_doc_kind: DocKind | None = None
    transport_doc_no: Text300 | None = None
    containers: Annotated[list[Annotated[str, Field(max_length=40)]], Field(max_length=200)] | None = None
    # v0.9.0: ISO 6346 numbers (check digit validated) with their size/type code; the plain list above stays
    container_units: Annotated[list["ContainerIn"], Field(max_length=200)] | None = None
    origin_location_id: uuid.UUID | None = None
    destination_location_id: uuid.UUID | None = None
    vessel_or_flight: Text300 | None = None
    origin: Text300 | None = None
    destination: Text300 | None = None
    incoterm: Text300 | None = None
    etd: date | None = None
    eta: date | None = None
    atd: date | None = None
    ata: date | None = None
    status: ShipmentStatus | None = None
    insurer_party_id: uuid.UUID | None = None
    policy_no: Text300 | None = None
    insured_amount: Amount | None = None
    insured_amount_currency: Currency | None = None
    notes: LongText | None = None
    items: list[ShipmentItemIn] | None = None


class ShipmentIn(ShipmentBase):
    case_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    sales_order_id: uuid.UUID | None = None
    direction: Literal["inbound", "outbound"] | None = None


class ShipmentPatch(ShipmentBase):
    pass


class ShipmentEventIn(InputModel):
    kind: Annotated[str, Field(min_length=1, max_length=60)]
    location_id: uuid.UUID | None = None          # v0.9.0: e.g. the transshipment port
    at: datetime | None = None
    note: Text2000 | None = None
    document_id: uuid.UUID | None = None


class ShipmentDocumentIn(InputModel):
    kind: ShipmentDocKind
    document_id: uuid.UUID
    number: Text300 | None = None
    issued_on: date | None = None


class InspectionItem(InputModel):
    description: Text300 | None = None
    purchase_order_item_id: uuid.UUID | None = None
    quantity: Amount | None = None
    result: Literal["pass", "fail", "conditional", "pending"] | None = None
    note: Text300 | None = None


class InspectionIn(InputModel):
    case_id: uuid.UUID | None = None
    shipment_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    kind: Literal["pre_shipment", "on_arrival", "third_party", "internal"]
    inspector_party_id: uuid.UUID | None = None
    planned_on: date | None = None
    done_on: date | None = None
    result: Literal["pass", "fail", "conditional", "pending"] | None = None
    report_document_id: uuid.UUID | None = None
    items: list[InspectionItem] | None = None
    notes: LongText | None = None


class InspectionPatch(InputModel):
    kind: Literal["pre_shipment", "on_arrival", "third_party", "internal"] | None = None
    inspector_party_id: uuid.UUID | None = None
    planned_on: date | None = None
    done_on: date | None = None
    result: Literal["pass", "fail", "conditional", "pending"] | None = None
    report_document_id: uuid.UUID | None = None
    items: list[InspectionItem] | None = None
    notes: LongText | None = None


class ReceiptLine(InputModel):
    purchase_order_item_id: uuid.UUID
    quantity: Amount
    condition: Literal["ok", "damaged", "short"] = "ok"
    note: Text300 | None = None


class ReceiptIn(InputModel):
    purchase_order_id: uuid.UUID
    shipment_id: uuid.UUID | None = None
    received_on: date
    document_id: uuid.UUID | None = None
    note: Text2000 | None = None
    items: list[ReceiptLine]


# ---- claims and deliveries (M3) --------------------------------------------------------------------------------------------

ClaimKind = Literal["defect", "shortage", "delay", "damage", "wrong_item", "documents", "other"]
ClaimDirection = Literal["against_supplier", "against_carrier", "against_insurer", "from_customer"]


class ClaimItem(InputModel):
    description: Text300 | None = None
    purchase_order_item_id: uuid.UUID | None = None
    sales_order_item_id: uuid.UUID | None = None
    quantity: Amount | None = None
    condition: Text300 | None = None
    result: Text300 | None = None
    note: Text300 | None = None


class ClaimIn(InputModel):
    case_id: uuid.UUID | None = None
    direction: ClaimDirection
    counterparty_id: uuid.UUID | None = None
    kind: ClaimKind
    purchase_order_id: uuid.UUID | None = None
    shipment_id: uuid.UUID | None = None
    receipt_id: uuid.UUID | None = None
    delivery_id: uuid.UUID | None = None
    inspection_id: uuid.UUID | None = None
    items: list[ClaimItem] | None = None
    claimed_amount: Amount | None = None
    claimed_amount_currency: Currency | None = None
    opened_on: date | None = None
    notes: LongText | None = None


class ClaimPatch(InputModel):
    counterparty_id: uuid.UUID | None = None
    kind: ClaimKind | None = None
    items: list[ClaimItem] | None = None
    claimed_amount: Amount | None = None
    claimed_amount_currency: Currency | None = None
    opened_on: date | None = None
    notes: LongText | None = None


class ClaimStatusIn(InputModel):
    status: Literal["open", "submitted", "negotiating", "resolved", "rejected", "withdrawn"]
    note: Text2000 | None = None
    resolution: Literal["replacement", "credit_note", "refund", "discount", "repair", "none"] | None = None
    resolution_amount: Amount | None = None
    resolution_amount_currency: Currency | None = None
    resolved_on: date | None = None


class DeliveryLine(InputModel):
    sales_order_item_id: uuid.UUID
    quantity: Positive


class DeliveryIn(InputModel):
    sales_order_id: uuid.UUID
    shipment_id: uuid.UUID | None = None
    delivered_on: date
    delivery_place: Text300 | None = None
    receiver_name: Text300 | None = None
    receipt_document_id: uuid.UUID | None = None
    note: Text2000 | None = None
    items: list[DeliveryLine]
