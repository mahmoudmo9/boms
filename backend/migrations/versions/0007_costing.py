"""Costing (Phase 6, v0.4.0): tax parameters, cost templates, cost sheets with FX entries and cost lines.

Schema ``ops``: tax_kind (seeded vocabulary), tax_parameter (rates are data entered by the owner; no rates are
seeded), cost_template + cost_template_line (three default templates: import, export, domestic), cost_sheet
(versioned per case: draft -> final -> superseded), fx_rate_entry (entered by hand per sheet), cost_line.
Money is NUMERIC(18,4) with a currency code; FX rates NUMERIC(24,10); percentages NUMERIC(9,4).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
DEAL_TYPES = "('import', 'export', 'domestic')"
LINE_KINDS = ("('purchase', 'freight_international', 'insurance', 'bank_fees', 'customs_duty', 'levy', "
              "'customs_clearance', 'storage', 'inspection', 'freight_domestic', 'export_clearance', 'vat', 'other')")
BASES = "('total', 'per_unit', 'percent_of_cif', 'percent_of_purchase')"
ALLOCATIONS = "('by_value', 'by_quantity', 'equal', 'manual')"

TAX_KINDS = [
    ("vat", "مالیات بر ارزش افزوده", "VAT"),
    ("income_tax", "مالیات بر درآمد", "Income tax"),
    ("duty_default", "حقوق ورودی (پیش‌فرض)", "Customs duty (default)"),
    ("levy", "عوارض", "Levy"),
    ("other", "سایر", "Other"),
]

# (kind, label_fa, label_en, basis, allocation, paid_before_receipt, tax_kind)
TEMPLATES = {
    "import": ("واردات (پیش‌فرض)", "Import (default)", [
        ("purchase", "خرید", "Purchase", "per_unit", "by_value", True, None),
        ("freight_international", "حمل بین‌المللی", "International freight", "total", "by_value", True, None),
        ("insurance", "بیمه", "Insurance", "total", "by_value", True, None),
        ("bank_fees", "کارمزد بانکی و انتقال", "Bank / transfer fees", "total", "by_value", True, None),
        ("customs_duty", "حقوق گمرکی", "Customs duty", "percent_of_cif", "by_value", False, "duty_default"),
        ("levy", "عوارض و سایر حقوق", "Levies / other duties", "percent_of_cif", "by_value", False, "levy"),
        ("customs_clearance", "ترخیص گمرکی", "Customs clearance", "total", "by_value", False, None),
        ("storage", "انبارداری و دموراژ", "Storage and demurrage", "total", "by_value", False, None),
        ("inspection", "بازرسی", "Inspection", "total", "by_value", False, None),
        ("freight_domestic", "حمل داخلی تا مقصد", "Domestic freight to destination", "total", "by_value", False, None),
    ]),
    "export": ("صادرات (پیش‌فرض)", "Export (default)", [
        ("purchase", "خرید", "Purchase", "per_unit", "by_value", True, None),
        ("freight_domestic", "حمل داخلی تا بندر/مرز", "Domestic freight to port / border", "total", "by_value", False, None),
        ("export_clearance", "ترخیص صادراتی", "Export clearance", "total", "by_value", False, None),
        ("inspection", "بازرسی", "Inspection", "total", "by_value", False, None),
        ("freight_international", "حمل بین‌المللی (در CIF/CFR و مانند آن)", "International freight (CIF/CFR etc.)",
         "total", "by_value", False, None),
        ("insurance", "بیمه", "Insurance", "total", "by_value", False, None),
        ("bank_fees", "کارمزد بانکی", "Bank fees", "total", "by_value", False, None),
    ]),
    "domestic": ("داخلی (پیش‌فرض)", "Domestic (default)", [
        ("purchase", "خرید", "Purchase", "per_unit", "by_value", True, None),
        ("freight_domestic", "حمل تا مقصد", "Freight to destination", "total", "by_value", False, None),
        ("other", "سایر", "Other", "total", "by_value", False, None),
    ]),
}

TABLES = ["tax_parameter", "cost_template", "cost_template_line", "cost_sheet", "fx_rate_entry", "cost_line"]


def _lit(text: str | None) -> str:
    return "NULL" if text is None else "'" + text.replace("'", "''") + "'"


def attach_triggers(table: str, pk: str = "id") -> None:
    op.execute(f"CREATE TRIGGER ops_{table}_updated_at BEFORE UPDATE ON ops.{table} "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    op.execute(f"CREATE TRIGGER ops_{table}_audit AFTER INSERT OR UPDATE OR DELETE ON ops.{table} "
               f"FOR EACH ROW EXECUTE FUNCTION core.audit_row({_lit(pk)})")


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE ops.tax_kind (
          code       text PRIMARY KEY,
          label_fa   text NOT NULL,
          label_en   text NOT NULL,
          sort_order integer NOT NULL DEFAULT 0,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.tax_parameter (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          kind           text NOT NULL REFERENCES ops.tax_kind (code),
          name           text NOT NULL CHECK (btrim(name) <> ''),
          rate_percent   numeric(9,4) NOT NULL CHECK (rate_percent >= 0 AND rate_percent <= 1000),
          deal_type      text NOT NULL CHECK (deal_type IN ('import', 'export', 'domestic', 'all')),
          effective_from date NOT NULL,
          effective_to   date,
          note           text,
          confirmed_by   text,
          confirmed_on   date,
          {TS},
          CONSTRAINT tax_parameter_period CHECK (effective_to IS NULL OR effective_to >= effective_from),
          CONSTRAINT tax_parameter_confirmed CHECK ((confirmed_by IS NULL) = (confirmed_on IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX tax_parameter_kind_idx ON ops.tax_parameter (kind, deal_type, effective_from DESC)")
    op.execute(
        f"""
        CREATE TABLE ops.cost_template (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          name       text NOT NULL CHECK (btrim(name) <> ''),
          name_fa    text,
          deal_type  text NOT NULL CHECK (deal_type IN {DEAL_TYPES}),
          is_default boolean NOT NULL DEFAULT false,
          status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS}
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX cost_template_one_default ON ops.cost_template (deal_type) "
               "WHERE is_default AND status = 'active'")
    op.execute(
        f"""
        CREATE TABLE ops.cost_template_line (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          template_id         uuid NOT NULL REFERENCES ops.cost_template (id),
          position            integer NOT NULL,
          kind                text NOT NULL CHECK (kind IN {LINE_KINDS}),
          label_fa            text,
          label_en            text,
          basis               text NOT NULL CHECK (basis IN {BASES}),
          allocation          text NOT NULL DEFAULT 'by_value' CHECK (allocation IN {ALLOCATIONS}),
          paid_before_receipt boolean NOT NULL DEFAULT false,
          tax_kind            text REFERENCES ops.tax_kind (code),
          {TS},
          CONSTRAINT cost_template_line_label CHECK (btrim(coalesce(label_fa, '')) <> '' OR btrim(coalesce(label_en, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX cost_template_line_template_idx ON ops.cost_template_line (template_id, position)")
    op.execute(
        f"""
        CREATE TABLE ops.cost_sheet (
          id                           uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id                      uuid NOT NULL REFERENCES ops."case" (id),
          version                      integer NOT NULL CHECK (version >= 1),
          status                       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'final', 'superseded')),
          deal_type                    text NOT NULL CHECK (deal_type IN {DEAL_TYPES}),
          pricing_currency             text NOT NULL REFERENCES sys.currency (code),
          template_id                  uuid REFERENCES ops.cost_template (id),
          sheet_date                   date NOT NULL DEFAULT current_date,
          notes                        text,
          supplier_prepay_percent      numeric(9,4) NOT NULL DEFAULT 0 CHECK (supplier_prepay_percent BETWEEN 0 AND 100),
          customer_prepay_percent      numeric(9,4) NOT NULL DEFAULT 0 CHECK (customer_prepay_percent BETWEEN 0 AND 100),
          days_from_payment_to_receipt integer NOT NULL DEFAULT 0 CHECK (days_from_payment_to_receipt >= 0),
          annual_cost_of_money_percent numeric(9,4) NOT NULL DEFAULT 0 CHECK (annual_cost_of_money_percent >= 0),
          guarantee_percent            numeric(9,4) NOT NULL DEFAULT 0 CHECK (guarantee_percent BETWEEN 0 AND 100),
          guarantee_days               integer NOT NULL DEFAULT 0 CHECK (guarantee_days >= 0),
          pricing_method               text NOT NULL DEFAULT 'margin' CHECK (pricing_method IN ('margin', 'markup')),
          target_percent               numeric(9,4) CHECK (target_percent IS NULL OR target_percent >= 0),
          min_acceptable_price         numeric(18,4) CHECK (min_acceptable_price IS NULL OR min_acceptable_price >= 0),
          item_min_prices              jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          price_overrides              jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          rounding                     text NOT NULL DEFAULT 'none' CHECK (rounding IN ('none', 'nearest', 'up')),
          rounding_step                numeric(18,4) CHECK (rounding_step IS NULL OR rounding_step > 0),
          validity_days                integer CHECK (validity_days IS NULL OR validity_days >= 0),
          fx_override_reason           text,
          parameter_override_reason    text,
          finalized_at                 timestamptz,
          {TS},
          UNIQUE (case_id, version),
          CONSTRAINT cost_sheet_rounding_step CHECK (rounding = 'none' OR rounding_step IS NOT NULL)
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX cost_sheet_one_final ON ops.cost_sheet (case_id) WHERE status = 'final'")
    op.execute(
        f"""
        CREATE TABLE ops.fx_rate_entry (
          id            uuid PRIMARY KEY DEFAULT uuidv7(),
          cost_sheet_id uuid NOT NULL REFERENCES ops.cost_sheet (id),
          from_currency text NOT NULL REFERENCES sys.currency (code),
          to_currency   text NOT NULL REFERENCES sys.currency (code),
          rate          numeric(24,10) NOT NULL CHECK (rate > 0),
          rate_kind     text,
          source_note   text,
          as_of         date NOT NULL,
          {TS},
          UNIQUE (cost_sheet_id, from_currency, to_currency),
          CONSTRAINT fx_rate_entry_pair CHECK (from_currency <> to_currency)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.cost_line (
          id                   uuid PRIMARY KEY DEFAULT uuidv7(),
          cost_sheet_id        uuid NOT NULL REFERENCES ops.cost_sheet (id),
          position             integer NOT NULL,
          kind                 text NOT NULL CHECK (kind IN {LINE_KINDS}),
          label                text NOT NULL CHECK (btrim(label) <> ''),
          scope                text NOT NULL CHECK (scope IN ('case', 'item')),
          line_item_id         uuid REFERENCES ops.line_item (id),
          amount               numeric(18,4),
          currency             text REFERENCES sys.currency (code),
          basis                text NOT NULL CHECK (basis IN {BASES}),
          percent              numeric(9,4) CHECK (percent IS NULL OR percent >= 0),
          allocation           text NOT NULL DEFAULT 'by_value' CHECK (allocation IN {ALLOCATIONS}),
          manual_shares        jsonb,
          paid_before_receipt  boolean NOT NULL DEFAULT false,
          tax_parameter_id     uuid REFERENCES ops.tax_parameter (id),
          source_offer_item_id uuid REFERENCES ops.offer_item (id),
          notes                text,
          {TS},
          CONSTRAINT cost_line_scope CHECK ((scope = 'item') = (line_item_id IS NOT NULL)),
          CONSTRAINT cost_line_amount_currency CHECK (amount IS NULL OR currency IS NOT NULL),
          CONSTRAINT cost_line_amount_basis CHECK (basis LIKE 'percent_%' OR percent IS NULL)
        )
        """
    )
    op.execute("CREATE INDEX cost_line_sheet_idx ON ops.cost_line (cost_sheet_id, position)")
    op.execute("CREATE INDEX cost_line_item_idx ON ops.cost_line (line_item_id)")

    # ---- seeds (before the audit triggers) --------------------------------------------------------
    op.execute("INSERT INTO ops.tax_kind (code, label_fa, label_en, sort_order) VALUES "
               + ", ".join(f"({_lit(c)}, {_lit(fa)}, {_lit(en)}, {i * 10})"
                           for i, (c, fa, en) in enumerate(TAX_KINDS, start=1)))
    for deal_type, (name_fa, name_en, lines) in TEMPLATES.items():
        op.execute(f"INSERT INTO ops.cost_template (name, name_fa, deal_type, is_default) VALUES "
                   f"({_lit(name_en)}, {_lit(name_fa)}, {_lit(deal_type)}, true)")
        op.execute(
            "INSERT INTO ops.cost_template_line (template_id, position, kind, label_fa, label_en, basis, allocation, "
            "paid_before_receipt, tax_kind) SELECT t.id, v.position, v.kind, v.label_fa, v.label_en, v.basis, "
            "v.allocation, v.paid, v.tax_kind FROM ops.cost_template t, (VALUES "
            + ", ".join(f"({i}, {_lit(k)}, {_lit(fa)}, {_lit(en)}, {_lit(b)}, {_lit(a)}, {str(p).lower()}, "
                        f"{_lit(tk)})" for i, (k, fa, en, b, a, p, tk) in enumerate(lines, start=1))
            + ") AS v (position, kind, label_fa, label_en, basis, allocation, paid, tax_kind) "
            f"WHERE t.deal_type = {_lit(deal_type)} AND t.is_default"
        )

    attach_triggers("tax_kind", pk="code")
    for table in TABLES:
        attach_triggers(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE ops.{table}")
    op.execute("DROP TABLE ops.tax_kind")
