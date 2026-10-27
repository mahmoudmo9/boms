"""Quotes / proforma invoices (Phase 6, v0.4.0): numbering, versions, items, outcomes.

Schema ``ops``: quote_sequence (one row per year, gap-free numbers handed out under a row lock in the creating
transaction), quote (versioned per case, status draft -> approved -> sent -> accepted / partially_accepted /
rejected / expired / withdrawn / superseded), quote_item (prices locked at approval, per-item outcome),
outcome_reason (seeded choices). ``ops.message_template`` gains kind ``quote_terms`` with a default text per
language (channel ``letter``).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-27
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
INCOTERMS = "('EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP')"
QUOTE_STATUSES = ("('draft', 'approved', 'sent', 'accepted', 'partially_accepted', 'rejected', 'expired', "
                  "'withdrawn', 'superseded')")

OUTCOME_REASONS = [
    ("price", "قیمت", "Price"),
    ("lead_time", "زمان تحویل", "Lead time"),
    ("payment_terms", "شرایط پرداخت", "Payment terms"),
    ("specification", "مشخصات فنی", "Specification"),
    ("competitor", "رقیب", "Competitor"),
    ("project_cancelled", "لغو پروژه", "Project cancelled"),
    ("no_budget", "نبود بودجه", "No budget"),
    ("other", "سایر", "Other"),
]

EN_TERMS = (
    "Dear {buyer_name},\n"
    "This proforma invoice is valid until {valid_until}.\n"
    "Payment terms: {payment_terms}\n"
    "Delivery terms: {incoterm}\n"
    "Lead time: {lead_time}\n\n"
    "Bank details:\n{bank_details}"
)
FA_TERMS = (
    "{buyer_name} گرامی،\n"
    "این پیش‌فاکتور تا تاریخ {valid_until} معتبر است.\n"
    "شرایط پرداخت: {payment_terms}\n"
    "شرایط تحویل: {incoterm}\n"
    "زمان تحویل: {lead_time}\n\n"
    "مشخصات بانکی:\n{bank_details}"
)
TERMS = [("en", "Proforma terms (English)", EN_TERMS), ("fa", "شرایط پیش‌فاکتور (فارسی)", FA_TERMS)]

TABLES = ["quote_sequence", "quote", "quote_item"]


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
        CREATE TABLE ops.outcome_reason (
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
        CREATE TABLE ops.quote_sequence (
          year        integer PRIMARY KEY,
          last_number integer NOT NULL CHECK (last_number >= 1),
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.quote (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id        uuid NOT NULL REFERENCES ops."case" (id),
          cost_sheet_id  uuid NOT NULL REFERENCES ops.cost_sheet (id),
          number         text NOT NULL UNIQUE CHECK (number ~ '^PI-[0-9]{{4}}-[0-9]+$'),
          version        integer NOT NULL CHECK (version >= 1),
          status         text NOT NULL DEFAULT 'draft' CHECK (status IN {QUOTE_STATUSES}),
          language       text NOT NULL CHECK (language IN ('fa', 'en')),
          price_basis    text NOT NULL DEFAULT 'before_vat' CHECK (price_basis IN ('before_vat', 'with_vat')),
          currency       text NOT NULL REFERENCES sys.currency (code),
          valid_until    date NOT NULL,
          incoterm       text CHECK (incoterm IS NULL OR incoterm IN {INCOTERMS}),
          incoterm_place text,
          payment_terms  text,
          delivery_terms text,
          lead_time_days integer CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
          terms_text     text,
          notes          text,
          subtotal       numeric(18,4) NOT NULL DEFAULT 0,
          vat_amount     numeric(18,4) NOT NULL DEFAULT 0,
          total          numeric(18,4) NOT NULL DEFAULT 0,
          buyer_party_id uuid REFERENCES core.party (id),
          contact_id     uuid REFERENCES core.contact (id),
          supersedes_id  uuid REFERENCES ops.quote (id),
          interaction_id uuid REFERENCES core.interaction (id),
          approved_at    timestamptz,
          approved_by    text,
          sent_at        timestamptz,
          decided_at     timestamptz,
          {TS},
          UNIQUE (case_id, version),
          CONSTRAINT quote_approved CHECK (status = 'draft' OR (approved_at IS NOT NULL AND approved_by IS NOT NULL)
                                           OR status = 'withdrawn'),
          CONSTRAINT quote_sent CHECK (status NOT IN ('sent', 'accepted', 'partially_accepted', 'rejected', 'expired')
                                       OR sent_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX quote_case_idx ON ops.quote (case_id, version DESC)")
    op.execute("CREATE INDEX quote_buyer_idx ON ops.quote (buyer_party_id)")
    op.execute("CREATE INDEX quote_status_idx ON ops.quote (status, valid_until)")
    op.execute(
        f"""
        CREATE TABLE ops.quote_item (
          id                   uuid PRIMARY KEY DEFAULT uuidv7(),
          quote_id             uuid NOT NULL REFERENCES ops.quote (id),
          line_item_id         uuid NOT NULL REFERENCES ops.line_item (id),
          position             integer NOT NULL,
          description_override text,
          quantity             numeric(18,4) NOT NULL CHECK (quantity > 0),
          unit_code            text REFERENCES sys.unit (code),
          unit_text            text,
          unit_price           numeric(18,4) NOT NULL CHECK (unit_price >= 0),
          total                numeric(18,4) NOT NULL CHECK (total >= 0),
          vat_amount           numeric(18,4) NOT NULL DEFAULT 0 CHECK (vat_amount >= 0),
          unit_cost            numeric(18,4),
          price_manual         boolean NOT NULL DEFAULT false,
          lead_time_days       integer CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
          note                 text,
          outcome              text CHECK (outcome IS NULL OR outcome IN ('accepted', 'rejected', 'no_reply', 'negotiating')),
          outcome_reason       text REFERENCES ops.outcome_reason (code),
          outcome_note         text,
          competitor_price     numeric(18,4) CHECK (competitor_price IS NULL OR competitor_price >= 0),
          competitor_currency  text REFERENCES sys.currency (code),
          decided_on           date,
          {TS},
          UNIQUE (quote_id, line_item_id),
          CONSTRAINT quote_item_rejected_reason CHECK (outcome IS DISTINCT FROM 'rejected' OR outcome_reason IS NOT NULL),
          CONSTRAINT quote_item_competitor CHECK (competitor_price IS NULL OR competitor_currency IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX quote_item_line_idx ON ops.quote_item (line_item_id)")

    op.execute("ALTER TABLE ops.message_template DROP CONSTRAINT message_template_kind_check")
    op.execute("ALTER TABLE ops.message_template ADD CONSTRAINT message_template_kind_check "
               "CHECK (kind IN ('rfq', 'quote_terms'))")

    # ---- seeds (outcome reasons before the audit trigger; templates go through the existing trigger) -----
    op.execute("INSERT INTO ops.outcome_reason (code, label_fa, label_en, sort_order) VALUES "
               + ", ".join(f"({_lit(c)}, {_lit(fa)}, {_lit(en)}, {i * 10})"
                           for i, (c, fa, en) in enumerate(OUTCOME_REASONS, start=1)))
    op.execute(
        "INSERT INTO ops.message_template (kind, language, channel, name, subject_template, body_template, is_default) "
        "VALUES " + ", ".join(f"('quote_terms', {_lit(lang)}, 'letter', {_lit(name)}, '', {_lit(body)}, true)"
                              for lang, name, body in TERMS)
    )

    attach_triggers("outcome_reason", pk="code")
    for table in TABLES:
        attach_triggers(table, pk="year" if table == "quote_sequence" else "id")


def downgrade() -> None:
    op.execute("DELETE FROM ops.message_template WHERE kind = 'quote_terms'")
    op.execute("ALTER TABLE ops.message_template DROP CONSTRAINT message_template_kind_check")
    op.execute("ALTER TABLE ops.message_template ADD CONSTRAINT message_template_kind_check CHECK (kind IN ('rfq'))")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE ops.{table}")
    op.execute("DROP TABLE ops.outcome_reason")
