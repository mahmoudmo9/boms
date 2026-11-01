"""Setad listings and screening (v0.5.0, Phase 7a): schema ``ext``, the ``setad`` job lane, Setad origin on inquiries.

Schema ``ext`` (module ``listings``):
- listing: machine rows refreshed from the site (no audit trigger: refreshed thousands of times a day), unique per
  (source, external_id); normalized search text with a trigram index.
- listing_change: one row per real change of a tracked field (never for volatile list metadata).
- listing_detail (1:1, refreshed), listing_file (attachments and their download state).
- listing_screening: the owner's decisions, separate from machine rows, audited; a refresh never touches it.
- harvest_run: one row per fetch (SetadSuite's sync report); agent_status: one row the UI polls.
``sys.job`` gains ``lane``: the Setad agent takes only lane ``setad``, the normal worker only lane ``default``.
``ops.inquiry`` gains the Setad origin (listing, number, link), the exact response deadline, the buyer's required
price validity and the delivery place; ``source_channel`` accepts ``setad``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01
"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
SOURCES = "('setad_purchase', 'setad_tender')"
CHANNELS_OLD = "('whatsapp', 'email', 'phone', 'tender_portal', 'in_person', 'letter', 'other')"
CHANNELS_NEW = "('whatsapp', 'email', 'phone', 'tender_portal', 'in_person', 'letter', 'other', 'setad')"


def updated_at(table: str) -> None:
    op.execute(f"CREATE TRIGGER ext_{table}_updated_at BEFORE UPDATE ON ext.{table} "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ext")

    op.execute(
        f"""
        CREATE TABLE ext.harvest_run (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          source         text NOT NULL CHECK (source IN {SOURCES}),
          kind           text NOT NULL CHECK (kind IN ('full', 'quick')),
          started_at     timestamptz NOT NULL DEFAULT now(),
          finished_at    timestamptz,
          status         text NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running', 'done', 'needs_review', 'cancelled', 'error')),
          reported_count integer,
          pages_total    integer,
          pages_done     integer NOT NULL DEFAULT 0,
          rows_seen      integer NOT NULL DEFAULT 0,
          new_count      integer NOT NULL DEFAULT 0,
          changed_count  integer NOT NULL DEFAULT 0,
          duplicates     integer NOT NULL DEFAULT 0,
          errors         text NOT NULL DEFAULT '',
          issues         jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX harvest_run_source_idx ON ext.harvest_run (source, started_at DESC)")
    updated_at("harvest_run")

    op.execute(
        f"""
        CREATE TABLE ext.listing (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          source             text NOT NULL CHECK (source IN {SOURCES}),
          external_id        text NOT NULL,
          external_no        text NOT NULL DEFAULT '',
          title              text NOT NULL DEFAULT '',
          organization       text NOT NULL DEFAULT '',
          province           text NOT NULL DEFAULT '',
          city               text NOT NULL DEFAULT '',
          category           text NOT NULL DEFAULT '',
          goods_group        text NOT NULL DEFAULT '',
          service_group      text NOT NULL DEFAULT '',
          type_name          text NOT NULL DEFAULT '',
          need_type          text NOT NULL DEFAULT '',
          description        text NOT NULL DEFAULT '',
          published_at       timestamptz,
          documents_deadline timestamptz,
          proposal_deadline  timestamptz,
          inquiry_deadline   timestamptz,
          opening_at         timestamptz,
          edition_date       timestamptz,
          edition_no         text NOT NULL DEFAULT '',
          response_deadline  timestamptz,
          deadline_exact     boolean NOT NULL DEFAULT false,
          price_valid_until  timestamptz,
          document_price     numeric(20,4),
          guarantee_amount   numeric(20,4),
          estimate           numeric(20,4),
          site_state         text NOT NULL DEFAULT '',
          site_state_name    text NOT NULL DEFAULT '',
          in_my_calls        boolean NOT NULL DEFAULT false,
          detail_url         text,
          raw                jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          content_hash       text NOT NULL DEFAULT '',
          search_norm        text GENERATED ALWAYS AS (core.normalize_fa(
                               external_no || ' ' || title || ' ' || organization || ' ' || description)) STORED,
          first_seen         timestamptz NOT NULL DEFAULT now(),
          last_seen          timestamptz NOT NULL DEFAULT now(),
          first_run_id       uuid REFERENCES ext.harvest_run (id) ON DELETE SET NULL,
          last_full_run_id   uuid REFERENCES ext.harvest_run (id) ON DELETE SET NULL,
          {TS},
          CONSTRAINT listing_external UNIQUE (source, external_id)
        )
        """
    )
    # the screening table filters and sorts on these; counts per filter run over the whole result
    op.execute("CREATE INDEX listing_no_idx ON ext.listing (source, external_no)")
    op.execute("CREATE INDEX listing_published_idx ON ext.listing (source, published_at DESC)")
    op.execute("CREATE INDEX listing_deadline_idx ON ext.listing (source, "
               "(coalesce(response_deadline, documents_deadline, proposal_deadline)))")
    op.execute("CREATE INDEX listing_org_idx ON ext.listing (source, organization)")
    op.execute("CREATE INDEX listing_province_idx ON ext.listing (source, province)")
    op.execute("CREATE INDEX listing_category_idx ON ext.listing (source, category)")
    op.execute("CREATE INDEX listing_first_run_idx ON ext.listing (first_run_id)")
    op.execute("CREATE INDEX listing_full_run_idx ON ext.listing (last_full_run_id)")
    op.execute("CREATE INDEX listing_search_trgm_idx ON ext.listing USING gin (search_norm gin_trgm_ops)")
    updated_at("listing")

    op.execute(
        """
        CREATE TABLE ext.listing_change (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          listing_id uuid NOT NULL REFERENCES ext.listing (id) ON DELETE CASCADE,
          run_id     uuid REFERENCES ext.harvest_run (id) ON DELETE SET NULL,
          field      text NOT NULL,
          old_value  text,
          new_value  text,
          at         timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX listing_change_listing_idx ON ext.listing_change (listing_id, at DESC)")

    op.execute(
        f"""
        CREATE TABLE ext.listing_detail (
          listing_id  uuid PRIMARY KEY REFERENCES ext.listing (id) ON DELETE CASCADE,
          fields      jsonb NOT NULL DEFAULT '[]'::jsonb,
          buyer_note  text NOT NULL DEFAULT '',
          items       jsonb NOT NULL DEFAULT '{{"headers": [], "rows": []}}'::jsonb,
          text        text NOT NULL DEFAULT '',
          info        jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          fetched_at  timestamptz NOT NULL DEFAULT now(),
          {TS}
        )
        """
    )
    updated_at("listing_detail")

    op.execute(
        f"""
        CREATE TABLE ext.listing_file (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          listing_id     uuid NOT NULL REFERENCES ext.listing (id) ON DELETE CASCADE,
          group_key      text NOT NULL DEFAULT '',
          group_title    text NOT NULL DEFAULT '',
          appendix_id    text NOT NULL,
          display_name   text NOT NULL,
          extension      text NOT NULL DEFAULT '',
          size           text NOT NULL DEFAULT '',
          state          text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'downloaded', 'missing', 'error')),
          local_path     text,
          sha256         text,
          document_id    uuid REFERENCES core.document (id) ON DELETE SET NULL,
          reported_count integer,
          error          text NOT NULL DEFAULT '',
          meta           jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          {TS},
          CONSTRAINT listing_file_key UNIQUE (listing_id, group_key, appendix_id)
        )
        """
    )
    updated_at("listing_file")

    op.execute(
        f"""
        CREATE TABLE ext.listing_screening (
          listing_id     uuid PRIMARY KEY REFERENCES ext.listing (id) ON DELETE CASCADE,
          status         text NOT NULL DEFAULT 'new'
                         CHECK (status IN ('new', 'starred', 'reviewing', 'converted', 'dismissed')),
          dismiss_reason text,
          note           text,
          checklist      jsonb NOT NULL DEFAULT '[]'::jsonb,
          inquiry_id     uuid REFERENCES ops.inquiry (id) ON DELETE SET NULL,
          starred_at     timestamptz,
          converted_at   timestamptz,
          {TS},
          CONSTRAINT screening_dismiss_reason CHECK (status <> 'dismissed' OR btrim(coalesce(dismiss_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX listing_screening_status_idx ON ext.listing_screening (status)")
    op.execute("CREATE INDEX listing_screening_inquiry_idx ON ext.listing_screening (inquiry_id)")
    updated_at("listing_screening")
    op.execute("CREATE TRIGGER ext_listing_screening_audit AFTER INSERT OR UPDATE OR DELETE ON ext.listing_screening "
               "FOR EACH ROW EXECUTE FUNCTION core.audit_row('listing_id')")

    op.execute(
        f"""
        CREATE TABLE ext.agent_status (
          id               smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          pid              integer,
          connected        boolean NOT NULL DEFAULT false,
          role             text,
          browser_channel  text,
          command          text,
          job_id           uuid,
          pages_done       integer,
          pages_total      integer,
          rows_seen        integer,
          captcha_waiting  boolean NOT NULL DEFAULT false,
          captcha_message  text,
          message          text,
          last_error       text,
          cancel_requested boolean NOT NULL DEFAULT false,
          recording        boolean NOT NULL DEFAULT false,
          heartbeat_at     timestamptz,
          started_at       timestamptz,
          {TS}
        )
        """
    )
    op.execute("INSERT INTO ext.agent_status (id) VALUES (1)")
    updated_at("agent_status")

    op.execute("ALTER TABLE sys.job ADD COLUMN lane text NOT NULL DEFAULT 'default' "
               "CHECK (lane IN ('default', 'setad'))")
    op.execute("CREATE INDEX job_lane_queue_idx ON sys.job (lane, run_after) WHERE status = 'queued'")

    op.execute("ALTER TABLE ops.inquiry DROP CONSTRAINT inquiry_source_channel_check")
    op.execute(f"ALTER TABLE ops.inquiry ADD CONSTRAINT inquiry_source_channel_check CHECK (source_channel IN {CHANNELS_NEW})")
    for column in ("listing_id uuid", "external_no text", "external_url text", "response_due_at timestamptz",
                   "required_price_validity date", "delivery_province text", "delivery_city text"):
        op.execute(f"ALTER TABLE ops.inquiry ADD COLUMN {column}")
    op.execute("CREATE INDEX inquiry_listing_idx ON ops.inquiry (listing_id) WHERE listing_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX ops.inquiry_listing_idx")
    for column in ("listing_id", "external_no", "external_url", "response_due_at", "required_price_validity",
                   "delivery_province", "delivery_city"):
        op.execute(f"ALTER TABLE ops.inquiry DROP COLUMN {column}")
    op.execute("UPDATE ops.inquiry SET source_channel = 'tender_portal' WHERE source_channel = 'setad'")
    op.execute("ALTER TABLE ops.inquiry DROP CONSTRAINT inquiry_source_channel_check")
    op.execute(f"ALTER TABLE ops.inquiry ADD CONSTRAINT inquiry_source_channel_check CHECK (source_channel IN {CHANNELS_OLD})")
    op.execute("DROP INDEX sys.job_lane_queue_idx")
    op.execute("DELETE FROM sys.job WHERE lane = 'setad'")
    op.execute("ALTER TABLE sys.job DROP COLUMN lane")
    for table in ("agent_status", "listing_screening", "listing_file", "listing_detail", "listing_change", "listing",
                  "harvest_run"):
        op.execute(f"DROP TABLE ext.{table}")
    op.execute("DROP SCHEMA ext")
