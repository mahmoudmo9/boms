"""v0.10.1 section 0: Ollama model facts and thinking per route; carrier tracking link and shipment tracking number.

- ``ai.provider.model_info``: what the provider's own model list (Ollama ``/api/tags``) said about each model — size,
  family and whether it is a cloud model (``remote_host`` / ``remote_model``). The local/cloud decision reads it; a
  model missing from it counts as cloud (fail-safe).
- ``ai.route.think``: send ``think`` to the model for this task (NULL = the task's default: off for short tasks).
- ``core.party.tracking_url_template``: a carrier's public tracking page with ``{number}`` as the placeholder.
- ``ops.shipment.tracking_number``: the number to track (the B/L, AWB or CMR number when empty).
- ``ref.import_run`` (section 0.2): one reference import — the uploaded file, its preview (dry run), progress (stage,
  rows read) for the event stream, the cancel request and the final report.
- ``ref.legal_form.names``: an ELF code's names per language (the GLEIF list has one row per language).

Additive only: nothing existing changes, and the downgrade drops only these columns and the new table.

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-14
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai.provider ADD COLUMN IF NOT EXISTS model_info jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE ai.route ADD COLUMN IF NOT EXISTS think boolean")
    op.execute("ALTER TABLE core.party ADD COLUMN IF NOT EXISTS tracking_url_template text")
    op.execute("ALTER TABLE core.party ADD CONSTRAINT party_tracking_template CHECK (tracking_url_template IS NULL OR "
               "(tracking_url_template ~* '^https?://' AND position('{number}' in tracking_url_template) > 0))")
    op.execute("ALTER TABLE ops.shipment ADD COLUMN IF NOT EXISTS tracking_number text")
    op.execute("ALTER TABLE ref.legal_form ADD COLUMN IF NOT EXISTS names jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("""
        CREATE TABLE IF NOT EXISTS ref.import_run (
            id uuid PRIMARY KEY DEFAULT core.uuidv7(),
            dataset text NOT NULL,
            file_name text NOT NULL,
            file_path text NOT NULL,
            file_sha256 text NOT NULL,
            release text,
            status text NOT NULL DEFAULT 'previewing' CHECK (status IN
                ('previewing', 'preview_ready', 'preview_failed', 'importing', 'done', 'failed', 'cancelled', 'discarded')),
            stage text,
            rows_read integer NOT NULL DEFAULT 0,
            rows_total integer,
            started_at timestamptz,
            preview jsonb,
            report jsonb,
            error text,
            cancel_requested boolean NOT NULL DEFAULT false,
            job_id uuid,
            actor text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now())""")
    op.execute("CREATE INDEX IF NOT EXISTS ref_import_run_updated_at_idx ON ref.import_run (updated_at)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ref_import_run_one_active ON ref.import_run (dataset) "
               "WHERE status IN ('previewing', 'importing')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref.import_run")
    op.execute("ALTER TABLE ref.legal_form DROP COLUMN IF EXISTS names")
    op.execute("ALTER TABLE ops.shipment DROP COLUMN IF EXISTS tracking_number")
    op.execute("ALTER TABLE core.party DROP CONSTRAINT IF EXISTS party_tracking_template")
    op.execute("ALTER TABLE core.party DROP COLUMN IF EXISTS tracking_url_template")
    op.execute("ALTER TABLE ai.route DROP COLUMN IF EXISTS think")
    op.execute("ALTER TABLE ai.provider DROP COLUMN IF EXISTS model_info")
