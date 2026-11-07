"""Deal finance (v0.8.0, Phase 9): invoices, supplier invoices, payments and allocation, actual costs, the deal result
and ratings. No general ledger.

Schema ``ops`` (module ``finance``):
- invoice_sequence: gap-free numbers per kind and year (``INV-<year>-<seq>``, credit notes ``CN-``, debit notes
  ``DN-``), handed out when an invoice is issued (drafts have no number).
- sales_invoice (+ lines): from a sales order's deliveries, fa (domestic) or en (commercial invoice); credit and debit
  notes correct an issued invoice; Moadian tax ID and status typed by the owner.
- purchase_invoice (+ lines): supplier invoices, matched against the PO and its receipts.
- payment_allocation: a payment record to a sales invoice, a supplier invoice or an actual cost.
- actual_cost: freight, customs, bank and other costs as they happen, each with its own FX rate.
- deal_result: the frozen figures of a closed deal. party_rating: supplier and customer ratings per closed case.
Also (owned by their modules): ``core.party`` gains ``national_id`` and ``economic_code`` (parties; the buyer IDs of
a domestic invoice) and ``ops.payment_record`` gains the real FX rate, the base (rial) amount, the rate source and the
bank fee (execution).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-07
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
COST_KINDS = ("('freight_international', 'insurance', 'bank_fees', 'customs_duty', 'levy', 'customs_clearance', "
              "'storage', 'inspection', 'freight_domestic', 'export_clearance', 'other')")
MOADIAN = "('not_required', 'not_sent', 'sent', 'accepted', 'rejected')"
SCORE = "CHECK ({0} IS NULL OR {0} BETWEEN 1 AND 5)"

TABLES = ["invoice_sequence", "sales_invoice", "sales_invoice_line", "purchase_invoice", "purchase_invoice_line",
          "actual_cost", "payment_allocation", "deal_result", "party_rating"]   # creation order (dropped in reverse)


def _lit(text: str | None) -> str:
    return "NULL" if text is None else "'" + text.replace("'", "''") + "'"


def attach_triggers(table: str, pk: str = "id") -> None:
    op.execute(f"CREATE TRIGGER ops_{table}_updated_at BEFORE UPDATE ON ops.{table} "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    op.execute(f"CREATE TRIGGER ops_{table}_audit AFTER INSERT OR UPDATE OR DELETE ON ops.{table} "
               f"FOR EACH ROW EXECUTE FUNCTION core.audit_row({_lit(pk)})")


def upgrade() -> None:
    # ---- columns owned by other modules --------------------------------------------------------------------------
    op.execute("ALTER TABLE core.party ADD COLUMN national_id text, ADD COLUMN economic_code text")
    op.execute(
        "ALTER TABLE ops.payment_record "
        "ADD COLUMN fx_rate_to_base numeric(20,6), ADD COLUMN base_amount numeric(20,4), ADD COLUMN rate_source text, "
        "ADD COLUMN bank_fee numeric(20,4), ADD COLUMN bank_fee_currency text REFERENCES sys.currency (code), "
        "ADD CONSTRAINT payment_record_rate_positive CHECK (fx_rate_to_base IS NULL OR fx_rate_to_base > 0), "
        "ADD CONSTRAINT payment_record_fee_has_currency CHECK (bank_fee IS NULL OR bank_fee_currency IS NOT NULL), "
        "ADD CONSTRAINT payment_record_fee_positive CHECK (bank_fee IS NULL OR bank_fee >= 0)")

    op.execute(f"CREATE TABLE ops.invoice_sequence (key text PRIMARY KEY, last_number integer NOT NULL, {TS})")
    op.execute(
        f"""
        CREATE TABLE ops.sales_invoice (
          id                   uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id              uuid NOT NULL REFERENCES ops."case" (id),
          sales_order_id       uuid NOT NULL REFERENCES ops.sales_order (id),
          number               text UNIQUE,
          kind                 text NOT NULL DEFAULT 'invoice' CHECK (kind IN ('invoice', 'credit_note', 'debit_note')),
          corrects_invoice_id  uuid REFERENCES ops.sales_invoice (id),
          language             text NOT NULL CHECK (language IN ('fa', 'en')),
          customer_party_id    uuid NOT NULL REFERENCES core.party (id),
          issue_date           date,
          due_date             date,
          currency             text NOT NULL REFERENCES sys.currency (code),
          price_basis          text NOT NULL DEFAULT 'before_vat' CHECK (price_basis IN ('before_vat', 'with_vat')),
          subtotal             numeric(20,4) NOT NULL DEFAULT 0,
          discount             numeric(20,4) NOT NULL DEFAULT 0,
          vat_rate             numeric(7,4) NOT NULL DEFAULT 0,
          vat_amount           numeric(20,4) NOT NULL DEFAULT 0,
          vat_note             text,
          total                numeric(20,4) NOT NULL DEFAULT 0,
          status               text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'issued', 'cancelled')),
          issued_at            timestamptz,
          cancel_reason        text,
          over_delivered_reason text,
          moadian_tax_id       text,
          moadian_status       text NOT NULL DEFAULT 'not_required' CHECK (moadian_status IN {MOADIAN}),
          moadian_on           date,
          moadian_note         text,
          incoterm             text,
          incoterm_place       text,
          country_of_origin    text,
          shipping_marks       text,
          gross_weight         text,
          net_weight           text,
          packages             text,
          transport_doc_no     text,
          shipment_id          uuid REFERENCES ops.shipment (id),
          notes                text,
          {TS},
          CONSTRAINT sales_invoice_note_corrects CHECK ((kind = 'invoice') = (corrects_invoice_id IS NULL)),
          CONSTRAINT sales_invoice_issued CHECK (status = 'draft' OR (number IS NOT NULL AND issue_date IS NOT NULL)),
          CONSTRAINT sales_invoice_cancel_reason CHECK (status <> 'cancelled' OR btrim(coalesce(cancel_reason, '')) <> ''),
          CONSTRAINT sales_invoice_amounts CHECK (subtotal >= 0 AND discount >= 0 AND vat_amount >= 0 AND total >= 0
                                                  AND vat_rate >= 0 AND vat_rate <= 100)
        )
        """
    )
    op.execute("CREATE INDEX sales_invoice_case_idx ON ops.sales_invoice (case_id)")
    op.execute("CREATE INDEX sales_invoice_order_idx ON ops.sales_invoice (sales_order_id)")
    op.execute("CREATE INDEX sales_invoice_customer_idx ON ops.sales_invoice (customer_party_id, status)")
    op.execute("CREATE INDEX sales_invoice_moadian_idx ON ops.sales_invoice (moadian_tax_id) WHERE moadian_tax_id IS NOT NULL")
    op.execute(
        f"""
        CREATE TABLE ops.sales_invoice_line (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          sales_invoice_id    uuid NOT NULL REFERENCES ops.sales_invoice (id),
          sales_order_item_id uuid REFERENCES ops.sales_order_item (id),
          position            integer NOT NULL,
          description         text NOT NULL CHECK (btrim(description) <> ''),
          quantity            numeric(20,4) NOT NULL,
          unit                text,
          unit_price          numeric(20,4) NOT NULL,
          discount            numeric(20,4) NOT NULL DEFAULT 0,
          total               numeric(20,4) NOT NULL,
          hs_code             text,
          {TS},
          CONSTRAINT sales_invoice_line_amounts CHECK (quantity > 0 AND unit_price >= 0 AND discount >= 0 AND total >= 0)
        )
        """
    )
    op.execute("CREATE INDEX sales_invoice_line_invoice_idx ON ops.sales_invoice_line (sales_invoice_id)")
    op.execute("CREATE INDEX sales_invoice_line_item_idx ON ops.sales_invoice_line (sales_order_item_id)")
    op.execute(
        f"""
        CREATE TABLE ops.purchase_invoice (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id             uuid NOT NULL REFERENCES ops."case" (id),
          purchase_order_id   uuid REFERENCES ops.purchase_order (id),
          supplier_party_id   uuid NOT NULL REFERENCES core.party (id),
          supplier_invoice_no text NOT NULL CHECK (btrim(supplier_invoice_no) <> ''),
          invoice_date        date NOT NULL,
          due_date            date,
          currency            text NOT NULL REFERENCES sys.currency (code),
          subtotal            numeric(20,4) NOT NULL DEFAULT 0,
          vat_amount          numeric(20,4) NOT NULL DEFAULT 0,
          total               numeric(20,4) NOT NULL DEFAULT 0,
          status              text NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'approved', 'disputed', 'cancelled')),
          approved_at         timestamptz,
          difference_reason   text,
          dispute_reason      text,
          claim_id            uuid REFERENCES ops.claim (id),
          cancel_reason       text,
          document_id         uuid REFERENCES core.document (id),
          notes               text,
          {TS},
          CONSTRAINT purchase_invoice_amounts CHECK (subtotal >= 0 AND vat_amount >= 0 AND total >= 0),
          CONSTRAINT purchase_invoice_cancel_reason CHECK (status <> 'cancelled' OR btrim(coalesce(cancel_reason, '')) <> ''),
          CONSTRAINT purchase_invoice_dispute_reason CHECK (status <> 'disputed' OR btrim(coalesce(dispute_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX purchase_invoice_supplier_no ON ops.purchase_invoice (supplier_party_id, supplier_invoice_no) "
               "WHERE status <> 'cancelled'")
    op.execute("CREATE INDEX purchase_invoice_case_idx ON ops.purchase_invoice (case_id)")
    op.execute("CREATE INDEX purchase_invoice_po_idx ON ops.purchase_invoice (purchase_order_id)")
    op.execute(
        f"""
        CREATE TABLE ops.purchase_invoice_line (
          id                     uuid PRIMARY KEY DEFAULT uuidv7(),
          purchase_invoice_id    uuid NOT NULL REFERENCES ops.purchase_invoice (id),
          purchase_order_item_id uuid REFERENCES ops.purchase_order_item (id),
          position               integer NOT NULL,
          description            text NOT NULL CHECK (btrim(description) <> ''),
          quantity               numeric(20,4) NOT NULL,
          unit_price             numeric(20,4) NOT NULL,
          total                  numeric(20,4) NOT NULL,
          {TS},
          CONSTRAINT purchase_invoice_line_amounts CHECK (quantity > 0 AND unit_price >= 0 AND total >= 0)
        )
        """
    )
    op.execute("CREATE INDEX purchase_invoice_line_invoice_idx ON ops.purchase_invoice_line (purchase_invoice_id)")
    op.execute("CREATE INDEX purchase_invoice_line_item_idx ON ops.purchase_invoice_line (purchase_order_item_id)")
    op.execute(
        f"""
        CREATE TABLE ops.actual_cost (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id           uuid NOT NULL REFERENCES ops."case" (id),
          kind              text NOT NULL CHECK (kind IN {COST_KINDS}),
          description       text NOT NULL CHECK (btrim(description) <> ''),
          party_id          uuid REFERENCES core.party (id),
          amount            numeric(20,4) NOT NULL,
          currency          text NOT NULL REFERENCES sys.currency (code),
          fx_rate_to_base   numeric(20,6),
          base_amount       numeric(20,4),
          vat_amount        numeric(20,4),
          incurred_on       date,
          due_date          date,
          document_id       uuid REFERENCES core.document (id),
          status            text NOT NULL DEFAULT 'incurred' CHECK (status IN ('expected', 'incurred', 'paid')),
          shipment_id       uuid REFERENCES ops.shipment (id),
          purchase_order_id uuid REFERENCES ops.purchase_order (id),
          notes             text,
          {TS},
          CONSTRAINT actual_cost_amounts CHECK (amount > 0 AND (vat_amount IS NULL OR vat_amount >= 0)),
          CONSTRAINT actual_cost_rate_positive CHECK (fx_rate_to_base IS NULL OR fx_rate_to_base > 0)
        )
        """
    )
    op.execute("CREATE INDEX actual_cost_case_idx ON ops.actual_cost (case_id)")
    op.execute(
        f"""
        CREATE TABLE ops.payment_allocation (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          payment_record_id   uuid NOT NULL REFERENCES ops.payment_record (id),
          sales_invoice_id    uuid REFERENCES ops.sales_invoice (id),
          purchase_invoice_id uuid REFERENCES ops.purchase_invoice (id),
          actual_cost_id      uuid REFERENCES ops.actual_cost (id),
          amount              numeric(20,4) NOT NULL,
          fx_rate             numeric(20,6),
          target_amount       numeric(20,4) NOT NULL,
          note                text,
          {TS},
          CONSTRAINT payment_allocation_one_target CHECK (num_nonnulls(sales_invoice_id, purchase_invoice_id, actual_cost_id) = 1),
          CONSTRAINT payment_allocation_amounts CHECK (amount > 0 AND target_amount > 0 AND (fx_rate IS NULL OR fx_rate > 0))
        )
        """
    )
    op.execute("CREATE INDEX payment_allocation_payment_idx ON ops.payment_allocation (payment_record_id)")
    op.execute("CREATE INDEX payment_allocation_sales_idx ON ops.payment_allocation (sales_invoice_id) WHERE sales_invoice_id IS NOT NULL")
    op.execute("CREATE INDEX payment_allocation_purchase_idx ON ops.payment_allocation (purchase_invoice_id) WHERE purchase_invoice_id IS NOT NULL")
    op.execute("CREATE INDEX payment_allocation_cost_idx ON ops.payment_allocation (actual_cost_id) WHERE actual_cost_id IS NOT NULL")
    op.execute(
        f"""
        CREATE TABLE ops.deal_result (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id     uuid NOT NULL UNIQUE REFERENCES ops."case" (id),
          data        jsonb NOT NULL,
          reasons     jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          computed_at timestamptz NOT NULL DEFAULT now(),
          closed_by   text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.party_rating (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id           uuid NOT NULL REFERENCES ops."case" (id),
          party_id          uuid NOT NULL REFERENCES core.party (id),
          role              text NOT NULL CHECK (role IN ('supplier', 'customer')),
          quality           integer CONSTRAINT party_rating_quality {SCORE.format('quality')},
          timeliness        integer CONSTRAINT party_rating_timeliness {SCORE.format('timeliness')},
          communication     integer CONSTRAINT party_rating_communication {SCORE.format('communication')},
          price             integer CONSTRAINT party_rating_price {SCORE.format('price')},
          payment_behavior  integer CONSTRAINT party_rating_payment {SCORE.format('payment_behavior')},
          note              text CHECK (note IS NULL OR length(note) <= 300),
          {TS},
          UNIQUE (case_id, party_id, role),
          CONSTRAINT party_rating_criteria CHECK ((role = 'customer' AND price IS NULL)
                                                  OR (role = 'supplier' AND payment_behavior IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX party_rating_party_idx ON ops.party_rating (party_id, created_at DESC)")
    for table in TABLES:
        attach_triggers(table, pk="key" if table == "invoice_sequence" else "id")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE ops.{table}")
    op.execute("ALTER TABLE ops.payment_record DROP CONSTRAINT payment_record_rate_positive, "
               "DROP CONSTRAINT payment_record_fee_has_currency, DROP CONSTRAINT payment_record_fee_positive, "
               "DROP COLUMN fx_rate_to_base, DROP COLUMN base_amount, DROP COLUMN rate_source, DROP COLUMN bank_fee, "
               "DROP COLUMN bank_fee_currency")
    op.execute("ALTER TABLE core.party DROP COLUMN national_id, DROP COLUMN economic_code")
