"""Execution and shipping (v0.7.0, Phase 8): from a won deal to delivered goods.

Schema ``ops`` (module ``execution``):
- sales_order_sequence / purchase_order_sequence: gap-free numbers per year (``SO-<year>-<seq>``, ``PO-<year>-<seq>``).
- sales_order (+ items, + sales_order_change amendments): from an accepted quote, a won tender's approved proposal or
  by hand; the signed document, dates and obligations.
- payment_milestone (+ payment_record): money in from the customer and out to suppliers, only where it gates the work.
- purchase_order (+ items, + purchase_order_change): to suppliers, versioned (``-v2``), approval, sending, confirmation,
  production / ready tracking.
- process_template (+ steps, seeded for import, export, domestic) and process (+ process_step): the checklist per deal.
- shipment (+ items, events, documents), inspection, receipt (+ items): logistics and goods received.
- claim, delivery (+ items): claims in any direction and deliveries to the customer item by item.
- execution_followup: which follow-up BOMS created for which order, step, claim (moved and cancelled with it).
``ops.message_template`` gains kind ``po_terms`` with a default text per language.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-05
"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
SO_STATUSES = "('draft', 'confirmed', 'in_progress', 'delivered', 'closed', 'cancelled')"
PO_STATUSES = ("('draft', 'approved', 'sent', 'confirmed', 'in_production', 'ready', 'shipped', 'received', 'closed', "
               "'cancelled', 'superseded')")
MILESTONE_KINDS = "('prepayment', 'on_order_confirmation', 'on_shipment', 'on_delivery', 'balance', 'retention', 'other')"
STEP_STATUSES = "('pending', 'in_progress', 'done', 'not_applicable')"
DEAL_TYPES = "('import', 'export', 'domestic')"
SHIPMENT_STATUSES = "('planned', 'booked', 'in_transit', 'arrived', 'at_customs', 'cleared', 'delivered', 'cancelled')"
MODES = "('sea', 'air', 'road', 'rail', 'courier', 'domestic_truck', 'other')"
DOC_KINDS = ("('commercial_invoice', 'packing_list', 'bl', 'awb', 'cmr', 'certificate_of_origin', 'inspection_certificate', "
             "'insurance_policy', 'customs_declaration', 'other')")
CLAIM_STATUSES = "('open', 'submitted', 'negotiating', 'resolved', 'rejected', 'withdrawn')"
FOLLOWUP_PURPOSES = ("('po_confirm', 'po_ready', 'step_reminder', 'claim', 'invoice', 'warranty_end', "
                     "'performance_release', 'milestone')")

# Process templates (labels are DATA: the owner renames, adds, removes and reorders steps in Settings -> Execution).
# (group, code, label_fa, label_en, reference_label, requires_document, default_offset_days)
IMPORT_STEPS = [
    ("supplier_order", "supplier_proforma", "پیش‌فاکتور تأمین‌کننده", "Supplier proforma", None, True, 0),
    ("supplier_order", "order_registration", "ثبت سفارش", "Registration of order", "شماره ثبت سفارش / Order registration no.", True, 7),
    ("supplier_order", "currency_allocation", "تأمین / تخصیص ارز", "Currency provision / allocation", "شماره پرونده ارزی / FX file no.", False, 21),
    ("supplier_order", "supplier_payment", "پرداخت به تأمین‌کننده (حواله / اعتبار اسنادی)", "Payment to the supplier (transfer / LC)", "شماره حواله یا LC / Transfer or LC no.", True, 30),
    ("shipping", "cargo_insurance", "بیمهٔ باربری", "Cargo insurance", "شماره بیمه‌نامه / Policy no.", True, 35),
    ("shipping", "shipment_booked", "رزرو حمل", "Shipment booked", "شماره رزرو / Booking no.", False, 40),
    ("shipping", "shipping_documents", "دریافت اسناد حمل (بارنامه، فاکتور تجاری، لیست عدل‌بندی، گواهی مبدأ، گواهی بازرسی)",
     "Shipping documents received (B/L/AWB/CMR, commercial invoice, packing list, certificate of origin, inspection certificate)",
     "شماره بارنامه / B/L no.", True, 55),
    ("customs", "customs_arrival", "ورود به گمرک", "Arrival at customs", None, False, 70),
    ("customs", "declaration_kotaj", "اظهارنامه و کوتاژ", "Customs declaration and kotaj", "شماره کوتاژ / Kotaj no.", True, 75),
    ("customs", "permits", "مجوزها (استاندارد، بهداشت، سایر)", "Permits (standard, health, other)", "شماره مجوز / Permit no.", False, 80),
    ("customs", "duties", "ارزیابی و پرداخت حقوق ورودی", "Valuation and payment of duties", "شماره قبض / Receipt no.", True, 85),
    ("customs", "release", "ترخیص", "Customs release", "شماره پروانه / Release no.", True, 90),
    ("domestic", "domestic_freight", "حمل داخلی تا مقصد", "Domestic freight to destination", "شماره بارنامه داخلی / Waybill no.", False, 95),
]
EXPORT_STEPS = [
    ("contract", "contract", "قرارداد / پیش‌فاکتور", "Contract / proforma", "شماره قرارداد / Contract no.", True, 0),
    ("contract", "production", "تولید / تأمین", "Production / procurement", None, False, 20),
    ("contract", "packing", "بسته‌بندی", "Packing", None, False, 25),
    ("contract", "inspection", "بازرسی", "Inspection", "شماره گزارش / Report no.", False, 28),
    ("customs_shipping", "export_declaration", "اظهارنامهٔ صادراتی و کوتاژ", "Export declaration and kotaj", "شماره کوتاژ / Kotaj no.", True, 32),
    ("customs_shipping", "loading", "بارگیری و حمل", "Loading and shipment", "شماره بارنامه / B/L no.", True, 35),
    ("customs_shipping", "documents_sent", "ارسال اسناد حمل به خریدار", "Shipping documents sent to the buyer", None, False, 40),
    ("currency", "fx_repatriation", "رفع تعهد ارزی", "Foreign-currency repatriation", "شماره رفع تعهد / Repatriation ref.", True, 90),
]
DOMESTIC_STEPS = [
    ("domestic", "po_sent", "ارسال سفارش خرید", "PO sent", None, False, 1),
    ("domestic", "supplier_prepayment", "پیش‌پرداخت به تأمین‌کننده", "Supplier prepayment", "شماره پرداخت / Payment ref.", False, 3),
    ("domestic", "goods_ready", "آماده شدن کالا", "Goods ready", None, False, 14),
    ("domestic", "transport", "بارگیری / حمل", "Pickup / transport", "شماره بارنامه / Waybill no.", False, 16),
    ("domestic", "delivery", "تحویل به خریدار", "Delivery to the buyer", None, False, 18),
    ("domestic", "delivery_receipt", "رسید تحویل", "Delivery receipt", "شماره رسید / Receipt no.", True, 19),
]
TEMPLATES = [("import", "واردات (ایران) / Import (Iran)", IMPORT_STEPS), ("export", "صادرات / Export", EXPORT_STEPS),
             ("domestic", "داخلی / Domestic", DOMESTIC_STEPS)]

PO_TERMS_FA = (
    "{supplier_name} محترم\n"
    "خواهشمند است کالاهای فهرست‌شده را طبق شرایط زیر تأمین فرمایید.\n"
    "نحوه پرداخت: {payment_terms}\n"
    "شرایط تحویل: {incoterm}\n"
    "تاریخ آمادگی: {ready_due_on}\n"
    "محل تحویل: {delivery_place}\n"
    "لطفاً دریافت و تأیید این سفارش را اعلام فرمایید."
)
PO_TERMS_EN = (
    "Dear {supplier_name},\n"
    "Please supply the goods listed above on the following terms.\n"
    "Payment terms: {payment_terms}\n"
    "Incoterm: {incoterm}\n"
    "Ready by: {ready_due_on}\n"
    "Delivery place: {delivery_place}\n"
    "Please confirm receipt and acceptance of this order."
)
PO_TERMS = [("en", "Purchase order terms (English)", PO_TERMS_EN), ("fa", "شرایط سفارش خرید (فارسی)", PO_TERMS_FA)]

TABLES = ["sales_order_sequence", "purchase_order_sequence", "sales_order", "sales_order_item", "sales_order_change",
          "purchase_order", "purchase_order_item", "purchase_order_change", "payment_milestone", "payment_record",
          "process_template", "process_template_step", "process", "shipment", "process_step", "shipment_item",
          "shipment_event", "shipment_document", "inspection", "receipt", "receipt_item", "delivery", "delivery_item",
          "claim", "execution_followup"]   # creation order (dropped in reverse)


def _lit(text: str | None) -> str:
    return "NULL" if text is None else "'" + text.replace("'", "''") + "'"


def attach_triggers(table: str, pk: str = "id") -> None:
    op.execute(f"CREATE TRIGGER ops_{table}_updated_at BEFORE UPDATE ON ops.{table} "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    op.execute(f"CREATE TRIGGER ops_{table}_audit AFTER INSERT OR UPDATE OR DELETE ON ops.{table} "
               f"FOR EACH ROW EXECUTE FUNCTION core.audit_row({_lit(pk)})")


def money(name: str, null: bool = True) -> str:
    """An amount always with its currency."""
    return (f"{name} numeric(20,4){'' if null else ' NOT NULL'}, {name}_currency text REFERENCES sys.currency (code), "
            f"CONSTRAINT {name}_has_currency CHECK ({name} IS NULL OR {name}_currency IS NOT NULL)")


def upgrade() -> None:
    for kind in ("sales_order", "purchase_order"):
        op.execute(f"CREATE TABLE ops.{kind}_sequence (year integer PRIMARY KEY, last_number integer NOT NULL, {TS})")

    # ---- sales orders ---------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.sales_order (
          id                       uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id                  uuid NOT NULL REFERENCES ops."case" (id),
          number                   text NOT NULL UNIQUE,
          customer_party_id        uuid NOT NULL REFERENCES core.party (id),
          contact_id               uuid REFERENCES core.contact (id),
          source                   text NOT NULL CHECK (source IN ('quote', 'tender_proposal', 'manual')),
          quote_id                 uuid REFERENCES ops.quote (id),
          tender_proposal_id       uuid REFERENCES ops.tender_proposal (id),
          customer_ref             text,
          contract_date            date,
          signed_document_id       uuid REFERENCES core.document (id),
          currency                 text NOT NULL REFERENCES sys.currency (code),
          price_basis              text NOT NULL DEFAULT 'before_vat' CHECK (price_basis IN ('before_vat', 'with_vat')),
          incoterm                 text,
          incoterm_place           text,
          payment_terms            text,
          delivery_terms           text,
          delivery_due_on          date,
          delivery_place           text,
          warranty_months          integer CHECK (warranty_months IS NULL OR warranty_months BETWEEN 0 AND 600),
          performance_guarantee_id uuid REFERENCES ops.guarantee (id),
          status                   text NOT NULL DEFAULT 'draft' CHECK (status IN {SO_STATUSES}),
          subtotal                 numeric(20,4) NOT NULL DEFAULT 0,
          vat_amount               numeric(20,4) NOT NULL DEFAULT 0,
          total                    numeric(20,4) NOT NULL DEFAULT 0,
          confirmed_at             timestamptz,
          no_document_reason       text,
          delivered_at             timestamptz,
          cancel_reason            text,
          notes                    text,
          {TS},
          CONSTRAINT sales_order_source_link CHECK (
            (source = 'quote' AND quote_id IS NOT NULL) OR (source = 'tender_proposal' AND tender_proposal_id IS NOT NULL)
            OR source = 'manual'),
          CONSTRAINT sales_order_confirmed_document CHECK (
            status IN ('draft', 'cancelled') OR signed_document_id IS NOT NULL
            OR btrim(coalesce(no_document_reason, '')) <> ''),
          CONSTRAINT sales_order_cancel_reason CHECK (status <> 'cancelled' OR btrim(coalesce(cancel_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX sales_order_case_idx ON ops.sales_order (case_id)")
    op.execute("CREATE INDEX sales_order_customer_idx ON ops.sales_order (customer_party_id)")
    op.execute("CREATE UNIQUE INDEX sales_order_one_per_quote ON ops.sales_order (quote_id) "
               "WHERE quote_id IS NOT NULL AND status <> 'cancelled'")
    op.execute("CREATE UNIQUE INDEX sales_order_one_per_proposal ON ops.sales_order (tender_proposal_id) "
               "WHERE tender_proposal_id IS NOT NULL AND status <> 'cancelled'")
    op.execute(
        f"""
        CREATE TABLE ops.sales_order_item (
          id               uuid PRIMARY KEY DEFAULT uuidv7(),
          sales_order_id   uuid NOT NULL REFERENCES ops.sales_order (id),
          line_item_id     uuid NOT NULL REFERENCES ops.line_item (id),
          position         integer NOT NULL,
          description      text NOT NULL,
          quantity         numeric(20,4) NOT NULL CHECK (quantity > 0),
          unit             text,
          unit_price       numeric(20,4) NOT NULL CHECK (unit_price >= 0),
          total            numeric(20,4) NOT NULL,
          vat_amount       numeric(20,4) NOT NULL DEFAULT 0,
          delivery_due_on  date,
          {TS},
          UNIQUE (sales_order_id, line_item_id)
        )
        """
    )
    op.execute("CREATE INDEX sales_order_item_line_idx ON ops.sales_order_item (line_item_id)")
    op.execute(
        f"""
        CREATE TABLE ops.sales_order_change (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          sales_order_id      uuid NOT NULL REFERENCES ops.sales_order (id),
          sales_order_item_id uuid REFERENCES ops.sales_order_item (id) ON DELETE SET NULL,
          field               text NOT NULL,
          old_value           text,
          new_value           text,
          reason              text NOT NULL CHECK (btrim(reason) <> ''),
          document_id         uuid REFERENCES core.document (id),
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX sales_order_change_order_idx ON ops.sales_order_change (sales_order_id, created_at)")

    # ---- purchase orders ------------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.purchase_order (
          id                        uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id                   uuid NOT NULL REFERENCES ops."case" (id),
          sales_order_id            uuid REFERENCES ops.sales_order (id),
          number                    text NOT NULL UNIQUE,
          version                   integer NOT NULL DEFAULT 1 CHECK (version >= 1),
          supersedes_id             uuid REFERENCES ops.purchase_order (id),
          supplier_party_id         uuid NOT NULL REFERENCES core.party (id),
          contact_id                uuid REFERENCES core.contact (id),
          offer_id                  uuid REFERENCES ops.supplier_offer (id),
          language                  text NOT NULL CHECK (language IN ('fa', 'en')),
          currency                  text NOT NULL REFERENCES sys.currency (code),
          incoterm                  text,
          incoterm_place            text,
          payment_terms             text,
          delivery_terms            text,
          ready_due_on              date,
          delivery_place            text,
          direct_to_customer        boolean NOT NULL DEFAULT false,
          status                    text NOT NULL DEFAULT 'draft' CHECK (status IN {PO_STATUSES}),
          subtotal                  numeric(20,4) NOT NULL DEFAULT 0,
          total                     numeric(20,4) NOT NULL DEFAULT 0,
          approved_at               timestamptz,
          price_override_reason     text,
          sent_at                   timestamptz,
          interaction_id            uuid REFERENCES core.interaction (id),
          prepayment_override_reason text,
          confirmed_at              timestamptz,
          supplier_ref              text,
          confirmed_ready_on        date,
          confirmation_document_id  uuid REFERENCES core.document (id),
          ready_on                  date,
          status_note               text,
          terms_text                text,
          terms_manual              boolean NOT NULL DEFAULT false,
          cancel_reason             text,
          notes                     text,
          {TS},
          CONSTRAINT purchase_order_cancel_reason CHECK (status <> 'cancelled' OR btrim(coalesce(cancel_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX purchase_order_case_idx ON ops.purchase_order (case_id)")
    op.execute("CREATE INDEX purchase_order_supplier_idx ON ops.purchase_order (supplier_party_id)")
    op.execute("CREATE INDEX purchase_order_sales_order_idx ON ops.purchase_order (sales_order_id)")
    op.execute(
        f"""
        CREATE TABLE ops.purchase_order_item (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          purchase_order_id   uuid NOT NULL REFERENCES ops.purchase_order (id),
          line_item_id        uuid NOT NULL REFERENCES ops.line_item (id),
          sales_order_item_id uuid REFERENCES ops.sales_order_item (id),
          offer_item_id       uuid REFERENCES ops.offer_item (id) ON DELETE SET NULL,
          position            integer NOT NULL,
          description         text NOT NULL,
          quantity            numeric(20,4) NOT NULL CHECK (quantity > 0),
          unit                text,
          unit_price          numeric(20,4) NOT NULL CHECK (unit_price >= 0),
          total               numeric(20,4) NOT NULL,
          received_quantity   numeric(20,4) NOT NULL DEFAULT 0 CHECK (received_quantity >= 0),
          {TS},
          UNIQUE (purchase_order_id, line_item_id)
        )
        """
    )
    op.execute("CREATE INDEX purchase_order_item_line_idx ON ops.purchase_order_item (line_item_id)")
    op.execute(
        f"""
        CREATE TABLE ops.purchase_order_change (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          purchase_order_id uuid NOT NULL REFERENCES ops.purchase_order (id),
          field             text NOT NULL,
          old_value         text,
          new_value         text,
          reason            text NOT NULL CHECK (btrim(reason) <> ''),
          document_id       uuid REFERENCES core.document (id),
          {TS}
        )
        """
    )

    # ---- payment milestones -----------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.payment_milestone (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id             uuid NOT NULL REFERENCES ops."case" (id),
          direction           text NOT NULL CHECK (direction IN ('in', 'out')),
          sales_order_id      uuid REFERENCES ops.sales_order (id),
          purchase_order_id   uuid REFERENCES ops.purchase_order (id),
          party_id            uuid NOT NULL REFERENCES core.party (id),
          kind                text NOT NULL CHECK (kind IN {MILESTONE_KINDS}),
          label               text,
          position            integer NOT NULL DEFAULT 0,
          percent             numeric(9,4) CHECK (percent IS NULL OR (percent > 0 AND percent <= 100)),
          {money("amount")},
          due_on              date,
          due_event           text,
          status              text NOT NULL DEFAULT 'expected' CHECK (status IN ('expected', 'partly', 'done', 'cancelled')),
          {money("actual_amount")},
          actual_on           date,
          method              text,
          reference           text,
          receipt_document_id uuid REFERENCES core.document (id),
          cancel_reason       text,
          note                text,
          {TS},
          CONSTRAINT payment_milestone_value CHECK (percent IS NOT NULL OR amount IS NOT NULL),
          CONSTRAINT payment_milestone_percent_of_order CHECK (
            percent IS NULL OR sales_order_id IS NOT NULL OR purchase_order_id IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX payment_milestone_case_idx ON ops.payment_milestone (case_id)")
    op.execute(
        f"""
        CREATE TABLE ops.payment_record (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          milestone_id uuid NOT NULL REFERENCES ops.payment_milestone (id),
          {money("amount", null=False)},
          paid_on      date NOT NULL,
          method       text,
          reference    text,
          document_id  uuid REFERENCES core.document (id),
          note         text,
          {TS},
          CONSTRAINT payment_record_positive CHECK (amount > 0)
        )
        """
    )

    # ---- process checklists -----------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.process_template (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          deal_type  text NOT NULL CHECK (deal_type IN {DEAL_TYPES}),
          name       text NOT NULL,
          is_default boolean NOT NULL DEFAULT false,
          status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS}
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX process_template_one_default ON ops.process_template (deal_type) "
               "WHERE is_default AND status = 'active'")
    op.execute(
        f"""
        CREATE TABLE ops.process_template_step (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          template_id         uuid NOT NULL REFERENCES ops.process_template (id) ON DELETE CASCADE,
          position            integer NOT NULL,
          "group"             text,
          code                text NOT NULL,
          label_fa            text NOT NULL,
          label_en            text NOT NULL,
          reference_label     text,
          requires_document   boolean NOT NULL DEFAULT false,
          default_offset_days integer CHECK (default_offset_days IS NULL OR default_offset_days BETWEEN -365 AND 3650),
          {TS},
          UNIQUE (template_id, code)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.process (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id        uuid NOT NULL REFERENCES ops."case" (id),
          deal_type      text NOT NULL CHECK (deal_type IN {DEAL_TYPES}),
          template_id    uuid REFERENCES ops.process_template (id) ON DELETE SET NULL,
          name           text NOT NULL,
          sales_order_id uuid REFERENCES ops.sales_order (id),
          base_date      date,
          {TS},
          UNIQUE (case_id, deal_type)
        )
        """
    )

    # ---- shipments (before process_step, which may point at one) ----------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.shipment (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id            uuid NOT NULL REFERENCES ops."case" (id),
          direction          text NOT NULL CHECK (direction IN ('inbound', 'outbound')),
          purchase_order_id  uuid REFERENCES ops.purchase_order (id),
          sales_order_id     uuid REFERENCES ops.sales_order (id),
          mode               text NOT NULL DEFAULT 'sea' CHECK (mode IN {MODES}),
          carrier_party_id   uuid REFERENCES core.party (id),
          forwarder_party_id uuid REFERENCES core.party (id),
          transport_doc_kind text CHECK (transport_doc_kind IS NULL OR transport_doc_kind IN ('bl', 'awb', 'cmr', 'waybill', 'other')),
          transport_doc_no   text,
          containers         text[] NOT NULL DEFAULT '{{}}',
          vessel_or_flight   text,
          origin             text,
          destination        text,
          incoterm           text,
          etd                date,
          eta                date,
          first_eta          date,
          atd                date,
          ata                date,
          status             text NOT NULL DEFAULT 'planned' CHECK (status IN {SHIPMENT_STATUSES}),
          insurer_party_id   uuid REFERENCES core.party (id),
          policy_no          text,
          {money("insured_amount")},
          notes              text,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX shipment_case_idx ON ops.shipment (case_id)")
    op.execute(
        f"""
        CREATE TABLE ops.process_step (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          process_id         uuid NOT NULL REFERENCES ops.process (id),
          position           integer NOT NULL,
          "group"            text,
          code               text NOT NULL,
          label_fa           text NOT NULL,
          label_en           text NOT NULL,
          reference_label    text,
          requires_document  boolean NOT NULL DEFAULT false,
          status             text NOT NULL DEFAULT 'pending' CHECK (status IN {STEP_STATUSES}),
          reference          text,
          started_on         date,
          done_on            date,
          due_on             date,
          remind_days_before integer[] NOT NULL DEFAULT '{{3,1}}',
          document_id        uuid REFERENCES core.document (id),
          no_document_reason text,
          shipment_id        uuid REFERENCES ops.shipment (id) ON DELETE SET NULL,
          note               text,
          {TS},
          CONSTRAINT process_step_document CHECK (
            status <> 'done' OR NOT requires_document OR document_id IS NOT NULL
            OR btrim(coalesce(no_document_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX process_step_process_idx ON ops.process_step (process_id, position)")
    op.execute("CREATE INDEX process_step_reference_idx ON ops.process_step (reference) WHERE reference IS NOT NULL")
    op.execute(
        f"""
        CREATE TABLE ops.shipment_item (
          id                     uuid PRIMARY KEY DEFAULT uuidv7(),
          shipment_id            uuid NOT NULL REFERENCES ops.shipment (id),
          purchase_order_item_id uuid REFERENCES ops.purchase_order_item (id),
          sales_order_item_id    uuid REFERENCES ops.sales_order_item (id),
          quantity               numeric(20,4) NOT NULL CHECK (quantity > 0),
          {TS},
          CONSTRAINT shipment_item_link CHECK (purchase_order_item_id IS NOT NULL OR sales_order_item_id IS NOT NULL)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.shipment_event (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          shipment_id uuid NOT NULL REFERENCES ops.shipment (id),
          at          timestamptz NOT NULL,
          kind        text NOT NULL CHECK (btrim(kind) <> ''),
          note        text,
          document_id uuid REFERENCES core.document (id),
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.shipment_document (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          shipment_id uuid NOT NULL REFERENCES ops.shipment (id),
          kind        text NOT NULL CHECK (kind IN {DOC_KINDS}),
          document_id uuid NOT NULL REFERENCES core.document (id),
          number      text,
          issued_on   date,
          {TS}
        )
        """
    )

    # ---- inspections, receipts, deliveries, claims -------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.inspection (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id            uuid NOT NULL REFERENCES ops."case" (id),
          shipment_id        uuid REFERENCES ops.shipment (id),
          purchase_order_id  uuid REFERENCES ops.purchase_order (id),
          kind               text NOT NULL CHECK (kind IN ('pre_shipment', 'on_arrival', 'third_party', 'internal')),
          inspector_party_id uuid REFERENCES core.party (id),
          planned_on         date,
          done_on            date,
          result             text NOT NULL DEFAULT 'pending' CHECK (result IN ('pass', 'fail', 'conditional', 'pending')),
          report_document_id uuid REFERENCES core.document (id),
          items              jsonb NOT NULL DEFAULT '[]'::jsonb,
          notes              text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.receipt (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          purchase_order_id uuid NOT NULL REFERENCES ops.purchase_order (id),
          shipment_id       uuid REFERENCES ops.shipment (id),
          received_on       date NOT NULL,
          document_id       uuid REFERENCES core.document (id),
          note              text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.receipt_item (
          id                     uuid PRIMARY KEY DEFAULT uuidv7(),
          receipt_id             uuid NOT NULL REFERENCES ops.receipt (id),
          purchase_order_item_id uuid NOT NULL REFERENCES ops.purchase_order_item (id),
          quantity               numeric(20,4) NOT NULL CHECK (quantity >= 0),
          condition              text NOT NULL DEFAULT 'ok' CHECK (condition IN ('ok', 'damaged', 'short')),
          note                   text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.delivery (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          sales_order_id      uuid NOT NULL REFERENCES ops.sales_order (id),
          shipment_id         uuid REFERENCES ops.shipment (id),
          delivered_on        date NOT NULL,
          delivery_place      text,
          receiver_name       text,
          receipt_document_id uuid REFERENCES core.document (id),
          note                text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.delivery_item (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          delivery_id         uuid NOT NULL REFERENCES ops.delivery (id),
          sales_order_item_id uuid NOT NULL REFERENCES ops.sales_order_item (id),
          quantity            numeric(20,4) NOT NULL CHECK (quantity > 0),
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.claim (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id           uuid NOT NULL REFERENCES ops."case" (id),
          direction         text NOT NULL CHECK (direction IN ('against_supplier', 'against_carrier', 'against_insurer', 'from_customer')),
          counterparty_id   uuid NOT NULL REFERENCES core.party (id),
          kind              text NOT NULL CHECK (kind IN ('defect', 'shortage', 'delay', 'damage', 'wrong_item', 'documents', 'other')),
          purchase_order_id uuid REFERENCES ops.purchase_order (id),
          shipment_id       uuid REFERENCES ops.shipment (id),
          receipt_id        uuid REFERENCES ops.receipt (id) ON DELETE SET NULL,
          delivery_id       uuid REFERENCES ops.delivery (id) ON DELETE SET NULL,
          inspection_id     uuid REFERENCES ops.inspection (id) ON DELETE SET NULL,
          items             jsonb NOT NULL DEFAULT '[]'::jsonb,
          {money("claimed_amount")},
          opened_on         date NOT NULL,
          status            text NOT NULL DEFAULT 'open' CHECK (status IN {CLAIM_STATUSES}),
          resolution        text CHECK (resolution IS NULL OR resolution IN ('replacement', 'credit_note', 'refund', 'discount', 'repair', 'none')),
          {money("resolution_amount")},
          resolved_on       date,
          notes             text,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX claim_case_idx ON ops.claim (case_id)")
    op.execute("CREATE INDEX claim_counterparty_idx ON ops.claim (counterparty_id)")
    op.execute(
        f"""
        CREATE TABLE ops.execution_followup (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id     uuid NOT NULL REFERENCES ops."case" (id),
          followup_id uuid NOT NULL REFERENCES core.followup (id),
          purpose     text NOT NULL CHECK (purpose IN {FOLLOWUP_PURPOSES}),
          ref_id      uuid,
          days_before integer,
          {TS},
          UNIQUE (followup_id)
        )
        """
    )
    op.execute("CREATE INDEX execution_followup_ref_idx ON ops.execution_followup (ref_id, purpose)")

    # ---- template kind po_terms and seeds ----------------------------------------------------------------------------
    op.execute("ALTER TABLE ops.message_template DROP CONSTRAINT message_template_kind_check")
    op.execute("ALTER TABLE ops.message_template ADD CONSTRAINT message_template_kind_check "
               "CHECK (kind IN ('rfq', 'quote_terms', 'po_terms'))")
    op.execute(
        "INSERT INTO ops.message_template (kind, language, channel, name, subject_template, body_template, is_default) "
        "VALUES " + ", ".join(f"('po_terms', {_lit(lang)}, 'letter', {_lit(name)}, '', {_lit(body)}, true)"
                              for lang, name, body in PO_TERMS))
    for deal_type, name, steps in TEMPLATES:
        op.execute(f"INSERT INTO ops.process_template (deal_type, name, is_default) VALUES ({_lit(deal_type)}, {_lit(name)}, true)")
        op.execute(
            'INSERT INTO ops.process_template_step (template_id, position, "group", code, label_fa, label_en, '
            "reference_label, requires_document, default_offset_days) VALUES "
            + ", ".join(f"((SELECT id FROM ops.process_template WHERE deal_type = {_lit(deal_type)} AND is_default), {i}, "
                        f"{_lit(g)}, {_lit(code)}, {_lit(fa)}, {_lit(en)}, {_lit(ref)}, {'true' if doc else 'false'}, "
                        f"{'NULL' if off is None else off})"
                        for i, (g, code, fa, en, ref, doc, off) in enumerate(steps, start=1)))

    for table in TABLES:
        attach_triggers(table, pk="year" if table.endswith("_sequence") else "id")


def downgrade() -> None:
    op.execute("DELETE FROM ops.message_template WHERE kind = 'po_terms'")
    op.execute("ALTER TABLE ops.message_template DROP CONSTRAINT message_template_kind_check")
    op.execute("ALTER TABLE ops.message_template ADD CONSTRAINT message_template_kind_check "
               "CHECK (kind IN ('rfq', 'quote_terms'))")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE ops.{table}")
