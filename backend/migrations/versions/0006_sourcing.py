"""Sourcing and RFQ (Phase 5): inquiries, decisions, cases, line items, RFQs, message templates, supplier offers;
catalog (products, aliases, categories); HS/ISIC reference codes and party capability tags.

Schema ``ops``: payment_term, item_status, inquiry, decision, "case", line_item, rfq, rfq_item, rfq_recipient,
message_template, supplier_offer, offer_item.
Schema ``core``: product_category, product, product_alias, party_capability.
Schema ``ref``: hs_code (HS 2022 chapters + headings), isic_code (ISIC Rev.4 sections + divisions), seeded from
``migrations/data/*.tsv``. Capability rows keep the code as text (no FK), so a new edition can replace the reference
rows without breaking links.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27
"""

from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

DATA = Path(__file__).resolve().parents[1] / "data"
HS_EDITION = "HS 2022"
ISIC_EDITION = "ISIC Rev.4"
FTS_TEXT_LIMIT = 300000

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
INCOTERMS = "('EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP')"

PAYMENT_TERMS = [
    ("full_prepayment", "پیش‌پرداخت کامل", "Full prepayment", False),
    ("partial_prepayment", "پیش‌پرداخت بخشی", "Partial prepayment", False),
    ("lc_or_guarantee", "اعتبار اسنادی یا ضمانت‌نامه", "LC or guarantee", False),
    ("pay_after_delivery", "پرداخت پس از تحویل", "Pay after delivery", False),
    ("order_before_payment", "سفارش پیش از پرداخت (ریسک پذیرفته‌شده)", "Order before payment (accepted risk)", True),
]
ITEM_STATUSES = [
    ("uncovered", "بدون پوشش", "Uncovered"),
    ("rfq_sent", "استعلام‌شده", "RFQ sent"),
    ("has_offer", "دارای پیشنهاد", "Has offer"),
    ("selected", "انتخاب‌شده", "Selected"),
    ("sold", "فروخته‌شده", "Sold"),
    ("delivered", "تحویل‌شده", "Delivered"),
    ("closed", "بسته‌شده", "Closed"),
    ("cancelled", "لغوشده", "Cancelled"),
]

EN_EMAIL = (
    "Dear {contact_name},\n\n"
    "We would like to receive your best offer for the items below.\n\n"
    "{items_table}\n\n"
    "Please include unit price, currency, Incoterm, minimum order quantity, lead time, payment terms and the "
    "validity of your offer.\n"
    "We would appreciate your reply by {respond_by}.\n\n"
    "{signature}"
)
EN_WHATSAPP = (
    "Hello {contact_name},\n"
    "Could you please quote for the following items:\n\n"
    "{items_table}\n\n"
    "Price, Incoterm, MOQ, lead time and validity please. Reply by {respond_by} if possible.\n\n"
    "{signature}"
)
FA_EMAIL = (
    "{contact_name} گرامی،\n\n"
    "با سلام و احترام، خواهشمند است بهترین قیمت خود را برای اقلام زیر اعلام فرمایید.\n\n"
    "{items_table}\n\n"
    "لطفاً قیمت واحد، ارز، شرایط تحویل (اینکوترمز)، حداقل سفارش، زمان تحویل، شرایط پرداخت و مدت اعتبار "
    "پیشنهاد را ذکر کنید.\n"
    "خواهشمندیم پاسخ را تا {respond_by} ارسال فرمایید.\n\n"
    "{signature}"
)
FA_WHATSAPP = (
    "سلام {contact_name}،\n"
    "لطفاً برای اقلام زیر قیمت بدهید:\n\n"
    "{items_table}\n\n"
    "قیمت، شرایط تحویل، حداقل سفارش، زمان تحویل و مدت اعتبار قیمت. در صورت امکان تا {respond_by} پاسخ دهید.\n\n"
    "{signature}"
)
TEMPLATES = [
    ("en", "email", "RFQ email (English)", "Request for quotation: {case_title}", EN_EMAIL),
    ("en", "whatsapp", "RFQ WhatsApp (English)", "", EN_WHATSAPP),
    ("fa", "email", "استعلام ایمیلی (فارسی)", "درخواست استعلام قیمت: {case_title}", FA_EMAIL),
    ("fa", "whatsapp", "استعلام واتس‌اپ (فارسی)", "", FA_WHATSAPP),
]

OPS_TABLES = ["payment_term", "item_status", "inquiry", "decision", "case", "line_item", "rfq", "rfq_item",
              "rfq_recipient", "message_template", "supplier_offer", "offer_item"]
CORE_TABLES = ["product_category", "product", "product_alias", "party_capability"]
REF_TABLES = ["hs_code", "isic_code"]


def _lit(text: str | None) -> str:
    return "NULL" if text is None else "'" + text.replace("'", "''") + "'"


def _q(schema: str, table: str) -> str:
    return f'{schema}."{table}"'


def attach_triggers(schema: str, table: str, pk: str = "id", omit: tuple[str, ...] = ()) -> None:
    name = f"{schema}_{table}"
    op.execute(f"CREATE TRIGGER {name}_updated_at BEFORE UPDATE ON {_q(schema, table)} "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    args = ", ".join(_lit(x) for x in (pk, *omit))
    op.execute(f"CREATE TRIGGER {name}_audit AFTER INSERT OR UPDATE OR DELETE ON {_q(schema, table)} "
               f"FOR EACH ROW EXECUTE FUNCTION core.audit_row({args})")


def _read_tsv(name: str) -> list[list[str]]:
    rows = []
    for line in (DATA / name).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            rows.append(line.split("\t"))
    return rows


def upgrade() -> None:
    # ---- reference codes -------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ref.hs_code (
          code        text PRIMARY KEY CHECK (code ~ '^[0-9]{{2}}([0-9]{{2}})?$'),
          level       smallint NOT NULL CHECK (level IN (2, 4)),
          parent_code text REFERENCES ref.hs_code (code),
          title_en    text NOT NULL,
          title_fa    text,
          title_norm  text GENERATED ALWAYS AS
                        (lower(core.normalize_fa(code || ' ' || title_en || ' ' || coalesce(title_fa, '')))) STORED,
          edition     text NOT NULL,
          {TS},
          CONSTRAINT hs_code_level CHECK (length(code) = level),
          CONSTRAINT hs_code_parent CHECK ((level = 2) = (parent_code IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX hs_code_title_trgm_idx ON ref.hs_code USING gin (title_norm gin_trgm_ops)")
    op.execute("CREATE INDEX hs_code_parent_idx ON ref.hs_code (parent_code)")
    op.execute(
        f"""
        CREATE TABLE ref.isic_code (
          code        text PRIMARY KEY CHECK (code ~ '^([A-U]|[0-9]{{2}})$'),
          level       text NOT NULL CHECK (level IN ('section', 'division')),
          parent_code text REFERENCES ref.isic_code (code),
          title_en    text NOT NULL,
          title_fa    text,
          title_norm  text GENERATED ALWAYS AS
                        (lower(core.normalize_fa(code || ' ' || title_en || ' ' || coalesce(title_fa, '')))) STORED,
          edition     text NOT NULL,
          {TS},
          CONSTRAINT isic_code_parent CHECK ((level = 'section') = (parent_code IS NULL))
        )
        """
    )
    op.execute("CREATE INDEX isic_code_title_trgm_idx ON ref.isic_code USING gin (title_norm gin_trgm_ops)")

    # ---- catalog (core) ---------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE core.product_category (
          id        uuid PRIMARY KEY DEFAULT uuidv7(),
          parent_id uuid REFERENCES core.product_category (id),
          name_fa   text,
          name_en   text,
          status    text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS},
          CONSTRAINT product_category_name CHECK (btrim(coalesce(name_fa, '')) <> '' OR btrim(coalesce(name_en, '')) <> ''),
          CONSTRAINT product_category_not_self CHECK (parent_id IS NULL OR parent_id <> id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE core.product (
          id              uuid PRIMARY KEY DEFAULT uuidv7(),
          name_fa         text,
          name_en         text,
          name_norm       text GENERATED ALWAYS AS
                            (core.normalize_fa(coalesce(name_fa, '') || ' ' || coalesce(name_en, ''))) STORED,
          kind_note       text,
          default_unit_code text REFERENCES sys.unit (code),
          hs_code         text CHECK (hs_code IS NULL OR hs_code ~ '^[0-9]{{2,10}}$'),
          category_id     uuid REFERENCES core.product_category (id),
          notes           text,
          status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS},
          CONSTRAINT product_name_required CHECK (btrim(coalesce(name_fa, '')) <> '' OR btrim(coalesce(name_en, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX product_name_trgm_idx ON core.product USING gin (name_norm gin_trgm_ops)")
    op.execute("CREATE INDEX product_hs_idx ON core.product (hs_code)")
    op.execute(
        f"""
        CREATE TABLE core.product_alias (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          product_id uuid NOT NULL REFERENCES core.product (id),
          alias      text NOT NULL CHECK (btrim(alias) <> ''),
          alias_norm text GENERATED ALWAYS AS (core.normalize_fa(alias)) STORED,
          {TS},
          UNIQUE (product_id, alias_norm)
        )
        """
    )
    op.execute("CREATE INDEX product_alias_trgm_idx ON core.product_alias USING gin (alias_norm gin_trgm_ops)")

    op.execute(
        f"""
        CREATE TABLE core.party_capability (
          id       uuid PRIMARY KEY DEFAULT uuidv7(),
          party_id uuid NOT NULL REFERENCES core.party (id),
          kind     text NOT NULL CHECK (kind IN ('hs', 'isic', 'tag')),
          code     text,
          tag_text text,
          tag_norm text GENERATED ALWAYS AS (lower(core.normalize_fa(tag_text))) STORED,
          notes    text,
          {TS},
          CONSTRAINT party_capability_shape CHECK (
            (kind = 'tag' AND code IS NULL AND btrim(coalesce(tag_text, '')) <> '')
            OR (kind <> 'tag' AND code IS NOT NULL AND tag_text IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX party_capability_unique ON core.party_capability "
        "(party_id, kind, coalesce(code, tag_norm))"
    )
    op.execute("CREATE INDEX party_capability_code_idx ON core.party_capability (kind, code)")
    op.execute("CREATE INDEX party_capability_tag_trgm_idx ON core.party_capability USING gin (tag_norm gin_trgm_ops)")

    # ---- vocabularies (ops) ------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.payment_term (
          code            text PRIMARY KEY,
          label_fa        text NOT NULL,
          label_en        text NOT NULL,
          sort_order      integer NOT NULL,
          requires_reason boolean NOT NULL DEFAULT false,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.item_status (
          code       text PRIMARY KEY,
          label_fa   text NOT NULL,
          label_en   text NOT NULL,
          sort_order integer NOT NULL,
          {TS}
        )
        """
    )

    # ---- inquiry, decision, case ----------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.inquiry (
          id                    uuid PRIMARY KEY DEFAULT uuidv7(),
          party_id              uuid REFERENCES core.party (id),
          source_channel        text NOT NULL CHECK (source_channel IN
                                  ('whatsapp', 'email', 'phone', 'tender_portal', 'in_person', 'letter', 'other')),
          kind                  text NOT NULL DEFAULT 'rfq' CHECK (kind IN ('rfq', 'tender', 'direct_order', 'other')),
          received_at           timestamptz NOT NULL,
          response_due_on       date,
          subject               text,
          raw_text              text,
          search_norm           text GENERATED ALWAYS AS
                                  (core.normalize_fa(coalesce(subject, '') || ' ' || coalesce(raw_text, ''))) STORED,
          status                text NOT NULL DEFAULT 'new' CHECK (status IN
                                  ('new', 'needs_info', 'ready_for_screening', 'rejected', 'no_reply', 'converted')),
          source_interaction_id uuid REFERENCES core.interaction (id),
          reject_reason         text,
          {TS},
          CONSTRAINT inquiry_reject_reason CHECK (status <> 'rejected' OR btrim(coalesce(reject_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX inquiry_status_idx ON ops.inquiry (status, received_at DESC)")
    op.execute("CREATE INDEX inquiry_party_idx ON ops.inquiry (party_id)")
    op.execute(
        "CREATE INDEX inquiry_fts_idx ON ops.inquiry USING gin "
        f"(to_tsvector('simple', left(search_norm, {FTS_TEXT_LIMIT})))"
    )
    op.execute(
        "CREATE INDEX inquiry_subject_trgm_idx ON ops.inquiry USING gin "
        "(core.normalize_fa(coalesce(subject, '')) gin_trgm_ops)"
    )

    check = "text NOT NULL DEFAULT 'unknown' CHECK ({0} IN ('yes', 'no', 'unknown'))"
    op.execute(
        f"""
        CREATE TABLE ops.decision (
          id                             uuid PRIMARY KEY DEFAULT uuidv7(),
          inquiry_id                     uuid NOT NULL UNIQUE REFERENCES ops.inquiry (id),
          light                          text NOT NULL CHECK (light IN ('green', 'yellow', 'red')),
          reason                         text NOT NULL CHECK (btrim(reason) <> ''),
          feasible_sourcing              {check.format('feasible_sourcing')},
          feasible_sourcing_note         text,
          exposure_acceptable            {check.format('exposure_acceptable')},
          exposure_acceptable_note       text,
          requirements_ok                {check.format('requirements_ok')},
          requirements_ok_note           text,
          exposure_estimate              numeric(18, 4),
          exposure_currency              text REFERENCES sys.currency (code),
          payment_term                   text REFERENCES ops.payment_term (code),
          ordering_before_payment_reason text,
          confirmed                      boolean NOT NULL DEFAULT false,
          {TS},
          CONSTRAINT decision_exposure_currency CHECK (exposure_estimate IS NULL OR exposure_currency IS NOT NULL),
          CONSTRAINT decision_obp_reason CHECK (payment_term IS DISTINCT FROM 'order_before_payment'
                                                OR btrim(coalesce(ordering_before_payment_reason, '')) <> '')
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE ops."case" (
          id                             uuid PRIMARY KEY DEFAULT uuidv7(),
          inquiry_id                     uuid UNIQUE REFERENCES ops.inquiry (id),
          party_id                       uuid REFERENCES core.party (id),
          title                          text NOT NULL CHECK (btrim(title) <> ''),
          title_norm                     text GENERATED ALWAYS AS (core.normalize_fa(title)) STORED,
          status                         text NOT NULL DEFAULT 'open' CHECK (status IN
                                           ('open', 'won', 'lost', 'closed', 'cancelled')),
          payment_term                   text REFERENCES ops.payment_term (code),
          ordering_before_payment_reason text,
          exposure_estimate              numeric(18, 4),
          exposure_currency              text REFERENCES sys.currency (code),
          notes                          text,
          {TS},
          CONSTRAINT case_exposure_currency CHECK (exposure_estimate IS NULL OR exposure_currency IS NOT NULL),
          CONSTRAINT case_obp_reason CHECK (payment_term IS DISTINCT FROM 'order_before_payment'
                                            OR btrim(coalesce(ordering_before_payment_reason, '')) <> '')
        )
        """
    )
    op.execute('CREATE INDEX case_status_idx ON ops."case" (status, updated_at DESC)')
    op.execute('CREATE INDEX case_title_trgm_idx ON ops."case" USING gin (title_norm gin_trgm_ops)')

    # ---- line items -----------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.line_item (
          id                       uuid PRIMARY KEY DEFAULT uuidv7(),
          inquiry_id               uuid REFERENCES ops.inquiry (id),
          case_id                  uuid REFERENCES ops."case" (id),
          position                 integer NOT NULL DEFAULT 1,
          name                     text NOT NULL CHECK (btrim(name) <> ''),
          name_norm                text GENERATED ALWAYS AS (core.normalize_fa(name)) STORED,
          description              text,
          product_id               uuid REFERENCES core.product (id),
          quantity                 numeric(18, 4) CHECK (quantity IS NULL OR quantity > 0),
          unit_code                text REFERENCES sys.unit (code),
          unit_text                text,
          target_price             numeric(18, 4) CHECK (target_price IS NULL OR target_price >= 0),
          target_currency          text REFERENCES sys.currency (code),
          destination_country_iso2 text REFERENCES sys.country (iso2),
          incoterm                 text CHECK (incoterm IS NULL OR incoterm IN {INCOTERMS}),
          incoterm_place           text,
          required_by              date,
          packaging                text,
          hs_code                  text CHECK (hs_code IS NULL OR hs_code ~ '^[0-9]{{2,10}}$'),
          route                    text NOT NULL DEFAULT 'unknown' CHECK (route IN ('domestic', 'foreign', 'both', 'unknown')),
          notes                    text,
          specs                    jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(specs) = 'array'),
          status                   text NOT NULL DEFAULT 'uncovered' REFERENCES ops.item_status (code),
          no_coverage_confirmed    boolean NOT NULL DEFAULT false,
          no_coverage_reason       text,
          selected_offer_item_id   uuid,
          {TS},
          CONSTRAINT line_item_owner CHECK (inquiry_id IS NOT NULL OR case_id IS NOT NULL),
          CONSTRAINT line_item_target_currency CHECK (target_price IS NULL OR target_currency IS NOT NULL),
          CONSTRAINT line_item_no_coverage_reason CHECK (NOT no_coverage_confirmed
                                                         OR btrim(coalesce(no_coverage_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX line_item_inquiry_idx ON ops.line_item (inquiry_id, position)")
    op.execute("CREATE INDEX line_item_case_idx ON ops.line_item (case_id, position)")
    op.execute("CREATE INDEX line_item_product_idx ON ops.line_item (product_id)")
    op.execute("CREATE INDEX line_item_name_trgm_idx ON ops.line_item USING gin (name_norm gin_trgm_ops)")

    # ---- RFQ ------------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.message_template (
          id               uuid PRIMARY KEY DEFAULT uuidv7(),
          kind             text NOT NULL DEFAULT 'rfq' CHECK (kind IN ('rfq')),
          language         text NOT NULL CHECK (language ~ '^[a-z]{{2,3}}$'),
          channel          text NOT NULL CHECK (channel IN ('email', 'whatsapp', 'letter')),
          name             text NOT NULL CHECK (btrim(name) <> ''),
          subject_template text NOT NULL DEFAULT '',
          body_template    text NOT NULL CHECK (btrim(body_template) <> ''),
          is_default       boolean NOT NULL DEFAULT false,
          status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS}
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX message_template_one_default ON ops.message_template (kind, language, channel) "
        "WHERE is_default AND status = 'active'"
    )
    op.execute(
        f"""
        CREATE TABLE ops.rfq (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id    uuid NOT NULL REFERENCES ops."case" (id),
          title      text NOT NULL CHECK (btrim(title) <> ''),
          title_norm text GENERATED ALWAYS AS (core.normalize_fa(title)) STORED,
          status     text NOT NULL DEFAULT 'draft' CHECK (status IN
                       ('draft', 'sent', 'answered', 'no_response', 'expired', 'cancelled')),
          language   text NOT NULL DEFAULT 'en' CHECK (language ~ '^[a-z]{{2,3}}$'),
          respond_by date,
          notes      text,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX rfq_case_idx ON ops.rfq (case_id)")
    op.execute("CREATE INDEX rfq_title_trgm_idx ON ops.rfq USING gin (title_norm gin_trgm_ops)")
    op.execute(
        f"""
        CREATE TABLE ops.rfq_item (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          rfq_id       uuid NOT NULL REFERENCES ops.rfq (id),
          line_item_id uuid NOT NULL REFERENCES ops.line_item (id),
          quantity     numeric(18, 4) CHECK (quantity IS NULL OR quantity > 0),
          unit_code    text REFERENCES sys.unit (code),
          unit_text    text,
          note         text,
          {TS},
          UNIQUE (rfq_id, line_item_id)
        )
        """
    )
    op.execute("CREATE INDEX rfq_item_line_idx ON ops.rfq_item (line_item_id)")
    op.execute(
        f"""
        CREATE TABLE ops.rfq_recipient (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          rfq_id         uuid NOT NULL REFERENCES ops.rfq (id),
          party_id       uuid NOT NULL REFERENCES core.party (id),
          contact_id     uuid REFERENCES core.contact (id),
          channel        text NOT NULL CHECK (channel IN ('email', 'whatsapp', 'letter', 'phone', 'other')),
          language       text NOT NULL DEFAULT 'en' CHECK (language ~ '^[a-z]{{2,3}}$'),
          template_id    uuid REFERENCES ops.message_template (id),
          status         text NOT NULL DEFAULT 'draft' CHECK (status IN
                           ('draft', 'sent', 'replied', 'declined', 'no_response', 'expired')),
          sent_at        timestamptz,
          subject        text,
          message_text   text,
          interaction_id uuid REFERENCES core.interaction (id),
          {TS},
          UNIQUE (rfq_id, party_id),
          CONSTRAINT rfq_recipient_sent_at CHECK (status = 'draft' OR status = 'declined' OR sent_at IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX rfq_recipient_party_idx ON ops.rfq_recipient (party_id)")
    op.execute("CREATE INDEX rfq_recipient_status_idx ON ops.rfq_recipient (status)")

    # ---- offers ---------------------------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE ops.supplier_offer (
          id               uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id          uuid NOT NULL REFERENCES ops."case" (id),
          party_id         uuid NOT NULL REFERENCES core.party (id),
          contact_id       uuid REFERENCES core.contact (id),
          rfq_recipient_id uuid REFERENCES ops.rfq_recipient (id),
          received_at      timestamptz NOT NULL,
          channel          text NOT NULL CHECK (channel IN ('email', 'whatsapp', 'wechat', 'phone', 'letter', 'other')),
          valid_until      date,
          currency         text NOT NULL REFERENCES sys.currency (code),
          incoterm         text CHECK (incoterm IS NULL OR incoterm IN {INCOTERMS}),
          incoterm_place   text,
          payment_terms    text,
          lead_time_days   integer CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
          compliance_notes text,
          notes            text,
          raw_text         text,
          raw_norm         text GENERATED ALWAYS AS (core.normalize_fa(raw_text)) STORED,
          status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'superseded', 'withdrawn', 'expired')),
          superseded_by_id uuid REFERENCES ops.supplier_offer (id),
          interaction_id   uuid REFERENCES core.interaction (id),
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX supplier_offer_case_idx ON ops.supplier_offer (case_id)")
    op.execute("CREATE INDEX supplier_offer_party_idx ON ops.supplier_offer (party_id)")
    op.execute("CREATE INDEX supplier_offer_valid_idx ON ops.supplier_offer (status, valid_until)")
    op.execute(
        "CREATE INDEX supplier_offer_fts_idx ON ops.supplier_offer USING gin "
        f"(to_tsvector('simple', left(coalesce(raw_norm, ''), {FTS_TEXT_LIMIT})))"
    )
    op.execute(
        f"""
        CREATE TABLE ops.offer_item (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          offer_id           uuid NOT NULL REFERENCES ops.supplier_offer (id),
          line_item_id       uuid NOT NULL REFERENCES ops.line_item (id),
          available          boolean NOT NULL DEFAULT true,
          unit_price         numeric(18, 4) CHECK (unit_price IS NULL OR unit_price >= 0),
          price_per_quantity numeric(18, 4) NOT NULL DEFAULT 1 CHECK (price_per_quantity > 0),
          unit_code          text REFERENCES sys.unit (code),
          unit_text          text,
          moq                numeric(18, 4) CHECK (moq IS NULL OR moq > 0),
          moq_unit           text,
          lead_time_days     integer CHECK (lead_time_days IS NULL OR lead_time_days >= 0),
          spec_deviation     text,
          packaging          text,
          notes              text,
          {TS},
          UNIQUE (offer_id, line_item_id),
          CONSTRAINT offer_item_price CHECK (NOT available OR unit_price IS NOT NULL)
        )
        """
    )
    op.execute("CREATE INDEX offer_item_line_idx ON ops.offer_item (line_item_id)")
    op.execute(
        "ALTER TABLE ops.line_item ADD CONSTRAINT line_item_selected_offer_fk "
        "FOREIGN KEY (selected_offer_item_id) REFERENCES ops.offer_item (id)"
    )

    # ---- seed data (before the audit triggers, so seeding does not fill core.audit) ----------------
    op.execute(
        "INSERT INTO ops.payment_term (code, label_fa, label_en, sort_order, requires_reason) VALUES "
        + ", ".join(f"({_lit(c)}, {_lit(fa)}, {_lit(en)}, {i * 10}, {str(r).lower()})"
                    for i, (c, fa, en, r) in enumerate(PAYMENT_TERMS, start=1))
    )
    op.execute(
        "INSERT INTO ops.item_status (code, label_fa, label_en, sort_order) VALUES "
        + ", ".join(f"({_lit(c)}, {_lit(fa)}, {_lit(en)}, {i * 10})" for i, (c, fa, en) in enumerate(ITEM_STATUSES, start=1))
    )
    op.execute(
        "INSERT INTO ops.message_template (kind, language, channel, name, subject_template, body_template, is_default) "
        "VALUES " + ", ".join(f"('rfq', {_lit(lang)}, {_lit(ch)}, {_lit(name)}, {_lit(subj)}, {_lit(body)}, true)"
                              for lang, ch, name, subj, body in TEMPLATES)
    )
    hs = _read_tsv("hs_2022.tsv")
    for level in ("2", "4"):
        values = [f"({_lit(c)}, {lv}, {_lit(p or None)}, {_lit(en)}, {_lit(fa or None)}, {_lit(HS_EDITION)})"
                  for c, lv, p, en, fa in hs if lv == level]
        op.execute("INSERT INTO ref.hs_code (code, level, parent_code, title_en, title_fa, edition) VALUES "
                   + ", ".join(values))
    isic = _read_tsv("isic_rev4.tsv")
    for level in ("section", "division"):
        values = [f"({_lit(c)}, {_lit(lv)}, {_lit(p or None)}, {_lit(en)}, {_lit(fa or None)}, {_lit(ISIC_EDITION)})"
                  for c, lv, p, en, fa in isic if lv == level]
        op.execute("INSERT INTO ref.isic_code (code, level, parent_code, title_en, title_fa, edition) VALUES "
                   + ", ".join(values))

    for table in REF_TABLES:
        attach_triggers("ref", table, pk="code", omit=("title_norm",))
    for table in CORE_TABLES:
        omit = {"product": ("name_norm",), "product_alias": ("alias_norm",), "party_capability": ("tag_norm",)}
        attach_triggers("core", table, omit=omit.get(table, ()))
    for table in OPS_TABLES:
        pk = "code" if table in ("payment_term", "item_status") else "id"
        omit = {"inquiry": ("search_norm",), "case": ("title_norm",), "line_item": ("name_norm",),
                "rfq": ("title_norm",), "supplier_offer": ("raw_norm",)}
        attach_triggers("ops", table, pk=pk, omit=omit.get(table, ()))


def downgrade() -> None:
    op.execute("ALTER TABLE ops.line_item DROP CONSTRAINT line_item_selected_offer_fk")
    for table in ["offer_item", "supplier_offer", "rfq_recipient", "rfq_item", "rfq", "message_template",
                  "line_item", "case", "decision", "inquiry", "item_status", "payment_term"]:
        op.execute(f"DROP TABLE {_q('ops', table)}")
    for table in ["party_capability", "product_alias", "product", "product_category"]:
        op.execute(f"DROP TABLE core.{table}")
    for table in ["isic_code", "hs_code"]:
        op.execute(f"DROP TABLE ref.{table}")
