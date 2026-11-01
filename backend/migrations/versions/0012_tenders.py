"""Tender workflow (v0.6.0, Phase 7b): the tender part of a case and everything only tenders need.

Schema ``ops`` (module ``tenders``):
- tender (1:1 with a case): number, Setad listing, organizer, type, stage, participation, document price, estimate,
  proposal validity, financial mode, submission and result; tender_result_reason (seeded, editable).
- tender_date (+ tender_date_change history), tender_addendum (clarifications, Q&A, extensions, cancellation),
  tender_followup (which follow-ups BOMS created for which date / guarantee, so they move and are cancelled with it).
- company_document (the reusable library), envelope_template (+ lines, a default seeded from SetadSuite),
  envelope_item (A/B/C checklist per tender).
- guarantee (+ guarantee_event history): bid, performance, advance payment, retention, other.
- tender_cost: documents purchase, guarantee fees, deposits, travel, other.
- tender_proposal (+ lines): the financial proposal summary for the buyer's own form.
``ext.listing`` gains the Setad appendix counts (renewal, price, cancel), tracked from now on. A ``quote_terms``
template "Tender (fa)" is seeded for the letterhead mode.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
STAGES = ("('screening', 'documents', 'pricing', 'guarantee', 'envelopes', 'submitted', 'opening', 'result', "
          "'closed')")
DATE_KINDS = ("('documents_deadline', 'briefing', 'site_visit', 'questions_deadline', 'proposal_deadline', 'opening', "
              "'quality_docs_deadline', 'offer_valid_until', 'other')")
GUARANTEE_STATUSES = ("('to_request', 'requested', 'issued', 'ready_to_upload', 'submitted', 'extended', 'released', "
                      "'claimed', 'cancelled')")
ITEM_STATUSES = "('not_ready', 'in_progress', 'needs_signature', 'ready', 'submitted')"
DOC_CATEGORIES = ("('registration', 'tax', 'insurance', 'certificates', 'track_record', 'qualification', 'identity', "
                  "'other')")

RESULT_REASONS = [
    ("price", "قیمت", "Price"),
    ("technical", "رد فنی / ارزیابی کیفی", "Technical disqualification"),
    ("missing_documents", "نقص مدارک", "Missing documents"),
    ("guarantee", "مشکل تضمین", "Guarantee problem"),
    ("late", "تأخیر در ارسال", "Late"),
    ("cancelled_by_organizer", "لغو توسط برگزارکننده", "Cancelled by the organizer"),
    ("unknown", "نامعلوم", "Unknown"),
    ("other", "سایر", "Other"),
]
# SetadSuite setad_tender/workspace.py DEFAULT_TEMPLATE (titles unchanged); kind marks the bid bond and price form lines
TEMPLATE = {
    "A": [("ضمانت‌نامه / چک تضمین شرکت در مناقصه", "bid_bond")],
    "B": [(t, "document") for t in (
        "تعهدنامه‌ها و برگه‌های اسناد مناقصه (مهر و امضا)", "آگهی تأسیس و آخرین تغییرات (روزنامه رسمی)", "اساسنامه",
        "گواهی ثبت‌نام ارزش افزوده", "گواهی رتبه / صلاحیت (در صورت درخواست)", "مدارک هویتی و وکالت امضاکنندگان",
        "فهرست سوابق کاری و تأییدیه‌ها", "گواهینامه‌ها (ISO / ایمنی)", "مفاصا حساب بیمه / فهرست بیمه",
        "گواهی یا اظهارنامه مالیاتی", "مشخصات و کاتالوگ فنی / روش اجرا")],
    "C": [("فرم پیشنهاد قیمت کارفرما (تکمیل، مهر و امضا)", "price_form"), ("برگه‌های ریز قیمت (در صورت وجود)", "document")],
}
TENDER_TERMS_NAME = "Tender (fa)"
TENDER_TERMS = (
    "{addressee}\n"
    "موضوع: پیشنهاد قیمت مناقصه شماره {setad_number}\n"
    "این پیشنهاد تا تاریخ {valid_until} معتبر است.\n"
    "نحوه پرداخت: طبق اسناد مناقصه\n"
    "زمان و شرایط تحویل: طبق اسناد مناقصه\n\n"
    "مشخصات بانکی:\n{bank_details}"
)
TABLES = ["tender", "tender_addendum", "tender_date", "tender_date_change", "company_document", "envelope_template",
          "envelope_template_line", "guarantee", "guarantee_event", "envelope_item", "tender_followup", "tender_cost",
          "tender_proposal", "tender_proposal_line"]   # creation order (dropped in reverse)
APPENDIX_COLUMNS = ("renewal_appendix_count", "price_appendix_count", "cancel_appendix_count")


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
    op.execute(
        f"""
        CREATE TABLE ops.tender_result_reason (
          code       text PRIMARY KEY,
          label_fa   text NOT NULL,
          label_en   text NOT NULL,
          sort_order integer NOT NULL DEFAULT 0,
          active     boolean NOT NULL DEFAULT true,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.tender (
          id                     uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id                uuid NOT NULL UNIQUE REFERENCES ops."case" (id),
          tender_no              text,
          listing_id             uuid REFERENCES ext.listing (id) ON DELETE SET NULL,
          organizer_party_id     uuid REFERENCES core.party (id),
          tender_type            text,
          stages                 text CHECK (stages IS NULL OR stages IN ('one_stage', 'two_stage', 'quality_evaluation')),
          stage                  text NOT NULL DEFAULT 'screening' CHECK (stage IN {STAGES}),
          participation          text NOT NULL DEFAULT 'undecided' CHECK (participation IN ('undecided', 'yes', 'no')),
          participation_reason   text,
          {money("document_price")},
          documents_obtained_at  timestamptz,
          {money("estimate")},
          proposal_validity_days integer CHECK (proposal_validity_days IS NULL OR proposal_validity_days > 0),
          proposal_valid_until   date,
          financial_mode         text NOT NULL DEFAULT 'buyer_form' CHECK (financial_mode IN ('buyer_form', 'letterhead')),
          submitted_at           timestamptz,
          submit_channel         text CHECK (submit_channel IS NULL OR submit_channel IN ('setad', 'in_person', 'post', 'other')),
          submit_note            text,
          submit_override_reason text,
          result                 text CHECK (result IS NULL OR result IN ('won', 'lost', 'cancelled', 'no_result')),
          result_reason          text REFERENCES ops.tender_result_reason (code),
          result_note            text,
          winner_name            text,
          {money("winner_price")},
          our_rank               integer CHECK (our_rank IS NULL OR our_rank >= 1),
          result_on              date,
          appendix_seen          jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          {TS},
          CONSTRAINT tender_lost_reason CHECK (result IS DISTINCT FROM 'lost' OR result_reason IS NOT NULL),
          CONSTRAINT tender_participation_reason CHECK (participation <> 'no' OR btrim(coalesce(participation_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX tender_listing_idx ON ops.tender (listing_id) WHERE listing_id IS NOT NULL")
    op.execute("CREATE INDEX tender_organizer_idx ON ops.tender (organizer_party_id)")
    op.execute(
        f"""
        CREATE TABLE ops.tender_addendum (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          tender_id   uuid NOT NULL REFERENCES ops.tender (id),
          number      text,
          received_on date NOT NULL,
          kind        text NOT NULL CHECK (kind IN ('clarification', 'question_answer', 'extension', 'change',
                                                    'cancellation', 'other')),
          summary     text NOT NULL CHECK (btrim(summary) <> ''),
          document_id uuid REFERENCES core.document (id),
          question    text,
          asked_on    date,
          answer      text,
          answered_on date,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX tender_addendum_tender_idx ON ops.tender_addendum (tender_id, received_on)")
    op.execute(
        f"""
        CREATE TABLE ops.tender_date (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          tender_id          uuid NOT NULL REFERENCES ops.tender (id),
          kind               text NOT NULL CHECK (kind IN {DATE_KINDS}),
          label              text,
          at                 timestamptz NOT NULL,
          all_day            boolean NOT NULL DEFAULT false,
          note               text,
          remind_days_before integer[] NOT NULL DEFAULT '{{}}',
          source             text NOT NULL DEFAULT 'manual' CHECK (source IN ('setad', 'manual', 'addendum')),
          {TS},
          CONSTRAINT tender_date_other_label CHECK (kind <> 'other' OR btrim(coalesce(label, '')) <> '')
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX tender_date_one_per_kind ON ops.tender_date (tender_id, kind) WHERE kind <> 'other'")
    op.execute(
        f"""
        CREATE TABLE ops.tender_date_change (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          tender_date_id uuid NOT NULL REFERENCES ops.tender_date (id),
          tender_id      uuid NOT NULL REFERENCES ops.tender (id),
          old_at         timestamptz,
          new_at         timestamptz NOT NULL,
          reason         text NOT NULL CHECK (btrim(reason) <> ''),
          addendum_id    uuid REFERENCES ops.tender_addendum (id),
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX tender_date_change_date_idx ON ops.tender_date_change (tender_date_id, created_at)")
    op.execute(
        f"""
        CREATE TABLE ops.company_document (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          title       text NOT NULL CHECK (btrim(title) <> ''),
          category    text NOT NULL DEFAULT 'other' CHECK (category IN {DOC_CATEGORIES}),
          document_id uuid REFERENCES core.document (id),
          issued_on   date,
          expires_on  date,
          note        text,
          status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS},
          CONSTRAINT company_document_dates CHECK (issued_on IS NULL OR expires_on IS NULL OR expires_on >= issued_on)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.envelope_template (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          name       text NOT NULL CHECK (btrim(name) <> ''),
          is_default boolean NOT NULL DEFAULT false,
          status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS}
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX envelope_template_one_default ON ops.envelope_template (is_default) WHERE is_default")
    op.execute(
        f"""
        CREATE TABLE ops.envelope_template_line (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          template_id uuid NOT NULL REFERENCES ops.envelope_template (id) ON DELETE CASCADE,
          envelope    text NOT NULL CHECK (envelope IN ('A', 'B', 'C')),
          position    integer NOT NULL CHECK (position >= 1),
          title       text NOT NULL CHECK (btrim(title) <> ''),
          kind        text NOT NULL DEFAULT 'document' CHECK (kind IN ('document', 'bid_bond', 'price_form')),
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.guarantee (
          id                    uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id               uuid NOT NULL REFERENCES ops."case" (id),
          tender_id             uuid REFERENCES ops.tender (id),
          purpose               text NOT NULL CHECK (purpose IN ('bid', 'performance', 'advance_payment', 'retention', 'other')),
          form                  text CHECK (form IS NULL OR form IN ('bank', 'electronic_bank', 'cheque', 'cash_deposit',
                                                                      'insurance', 'promissory_note', 'other')),
          beneficiary_party_id  uuid REFERENCES core.party (id),
          reminder_party_id     uuid REFERENCES core.party (id),
          {money("amount")},
          bank_name             text,
          branch                text,
          number                text,
          issued_on             date,
          valid_until           date,
          claim_period_until    date,
          status                text NOT NULL DEFAULT 'to_request' CHECK (status IN {GUARANTEE_STATUSES}),
          {money("fee")},
          {money("blocked_deposit")},
          document_id           uuid REFERENCES core.document (id),
          description           text,
          note                  text,
          {TS},
          CONSTRAINT guarantee_dates CHECK (issued_on IS NULL OR valid_until IS NULL OR valid_until >= issued_on)
        )
        """
    )
    op.execute("CREATE INDEX guarantee_case_idx ON ops.guarantee (case_id)")
    op.execute("CREATE INDEX guarantee_status_idx ON ops.guarantee (status, valid_until)")
    op.execute(
        f"""
        CREATE TABLE ops.guarantee_event (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          guarantee_id uuid NOT NULL REFERENCES ops.guarantee (id),
          kind         text NOT NULL CHECK (kind IN ('requested', 'issued', 'extended', 'released', 'claimed', 'cancelled',
                                                     'status')),
          on_date      date NOT NULL,
          old_status   text,
          new_status   text,
          valid_until  date,
          reason       text,
          document_id  uuid REFERENCES core.document (id),
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX guarantee_event_guarantee_idx ON ops.guarantee_event (guarantee_id, created_at)")
    op.execute(
        f"""
        CREATE TABLE ops.envelope_item (
          id                  uuid PRIMARY KEY DEFAULT uuidv7(),
          tender_id           uuid NOT NULL REFERENCES ops.tender (id),
          envelope            text NOT NULL CHECK (envelope IN ('A', 'B', 'C')),
          position            integer NOT NULL CHECK (position >= 1),
          title               text NOT NULL CHECK (btrim(title) <> ''),
          kind                text NOT NULL DEFAULT 'document' CHECK (kind IN ('document', 'bid_bond', 'price_form')),
          status              text NOT NULL DEFAULT 'not_ready' CHECK (status IN {ITEM_STATUSES}),
          company_document_id uuid REFERENCES ops.company_document (id),
          document_id         uuid REFERENCES core.document (id),
          guarantee_id        uuid REFERENCES ops.guarantee (id),
          note                text,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX envelope_item_tender_idx ON ops.envelope_item (tender_id, envelope, position)")
    op.execute("CREATE INDEX envelope_item_company_doc_idx ON ops.envelope_item (company_document_id)")
    op.execute(
        f"""
        CREATE TABLE ops.tender_followup (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          tender_id   uuid REFERENCES ops.tender (id),
          followup_id uuid NOT NULL UNIQUE REFERENCES core.followup (id),
          purpose     text NOT NULL CHECK (purpose IN ('date_reminder', 'guarantee_expiry', 'guarantee_release', 'opening',
                                                       'contract')),
          ref_id      uuid,
          days_before integer,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX tender_followup_ref_idx ON ops.tender_followup (purpose, ref_id)")
    op.execute(
        f"""
        CREATE TABLE ops.tender_cost (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          tender_id   uuid NOT NULL REFERENCES ops.tender (id),
          kind        text NOT NULL CHECK (kind IN ('documents_purchase', 'guarantee_fee', 'deposit', 'travel', 'other')),
          {money("amount", null=False)},
          paid_on     date,
          refundable  boolean NOT NULL DEFAULT false,
          refunded_on date,
          note        text,
          document_id uuid REFERENCES core.document (id),
          {TS},
          CONSTRAINT tender_cost_positive CHECK (amount >= 0),
          CONSTRAINT tender_cost_refund CHECK (refunded_on IS NULL OR refundable)
        )
        """
    )
    op.execute("CREATE INDEX tender_cost_tender_idx ON ops.tender_cost (tender_id)")
    op.execute(
        f"""
        CREATE TABLE ops.tender_proposal (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          tender_id         uuid NOT NULL REFERENCES ops.tender (id),
          cost_sheet_id     uuid NOT NULL REFERENCES ops.cost_sheet (id),
          version           integer NOT NULL CHECK (version >= 1),
          status            text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'superseded')),
          price_basis       text NOT NULL DEFAULT 'before_vat' CHECK (price_basis IN ('before_vat', 'with_vat')),
          currency          text NOT NULL REFERENCES sys.currency (code),
          subtotal          numeric(20,4) NOT NULL DEFAULT 0,
          vat_amount        numeric(20,4) NOT NULL DEFAULT 0,
          total             numeric(20,4) NOT NULL DEFAULT 0,
          valid_until       date,
          supersedes_id     uuid REFERENCES ops.tender_proposal (id),
          approved_at       timestamptz,
          approved_by       text,
          below_cost_reason text,
          note              text,
          {TS},
          UNIQUE (tender_id, version),
          CONSTRAINT tender_proposal_approved CHECK (status = 'draft' OR (approved_at IS NOT NULL AND approved_by IS NOT NULL))
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ops.tender_proposal_line (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          proposal_id  uuid NOT NULL REFERENCES ops.tender_proposal (id),
          line_item_id uuid NOT NULL REFERENCES ops.line_item (id),
          position     integer NOT NULL CHECK (position >= 1),
          quantity     numeric(18,4) NOT NULL,
          unit_code    text,
          unit_text    text,
          unit_price   numeric(20,4) NOT NULL,
          total        numeric(20,4) NOT NULL,
          vat_amount   numeric(20,4) NOT NULL DEFAULT 0,
          unit_cost    numeric(20,4),
          {TS},
          UNIQUE (proposal_id, line_item_id)
        )
        """
    )
    op.execute("CREATE INDEX tender_proposal_line_item_idx ON ops.tender_proposal_line (line_item_id)")

    # ---- seeds (before the audit triggers, as 0008 does) ------------------------------------------------------
    op.execute("INSERT INTO ops.tender_result_reason (code, label_fa, label_en, sort_order) VALUES "
               + ", ".join(f"({_lit(c)}, {_lit(fa)}, {_lit(en)}, {i * 10})"
                           for i, (c, fa, en) in enumerate(RESULT_REASONS, start=1)))
    op.execute("INSERT INTO ops.envelope_template (id, name, is_default) VALUES "
               "('01900000-0000-7000-8000-000000000e01', 'پیش‌فرض (SetadSuite)', true)")
    op.execute("INSERT INTO ops.envelope_template_line (template_id, envelope, position, title, kind) VALUES "
               + ", ".join(f"('01900000-0000-7000-8000-000000000e01', {_lit(env)}, {i}, {_lit(title)}, {_lit(kind)})"
                           for env, lines in TEMPLATE.items() for i, (title, kind) in enumerate(lines, start=1)))
    op.execute("INSERT INTO ops.message_template (kind, language, channel, name, subject_template, body_template, "
               f"is_default) VALUES ('quote_terms', 'fa', 'letter', {_lit(TENDER_TERMS_NAME)}, '', {_lit(TENDER_TERMS)}, "
               "false)")
    attach_triggers("tender_result_reason", pk="code")
    for table in TABLES:
        attach_triggers(table)

    for column in APPENDIX_COLUMNS:
        op.execute(f"ALTER TABLE ext.listing ADD COLUMN {column} integer")


def downgrade() -> None:
    for column in APPENDIX_COLUMNS:
        op.execute(f"ALTER TABLE ext.listing DROP COLUMN {column}")
    op.execute(f"DELETE FROM ops.message_template WHERE kind = 'quote_terms' AND name = {_lit(TENDER_TERMS_NAME)}")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE ops.{table}")
    op.execute("DROP TABLE ops.tender_result_reason")
