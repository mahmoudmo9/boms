"""AI layer (v0.9.0 sections 1-2), module ``ai`` in schema ``ai``.

- provider: Claude subscription (Claude Agent SDK), Anthropic / OpenAI / Gemini API, Ollama, OpenAI-compatible; the
  API key lives in Windows Credential Manager under ``secret_name`` (never in the database or files).
- price: input / output USD per million tokens per API provider and model (an API provider is enabled only with prices).
- route: per task kind the primary and fallback provider + model and the privacy level.
- call: the privacy log «چه چیزی کجا رفت» (never the content: file names, pages, characters, redactions, tokens, cost).
- draft / draft_field: proposals the owner reviews field by field; correction: his edits, reused as examples.
- case_setting: «فقط محلی» per case.
``sys.job.lane`` gains ``ai``. Seeded: the six providers (disabled, no models), routes for extraction, drafting and
light classification.

Downgrade: the owner's providers, prices, routes, drafts and corrections are archived in ``sys.downgrade_archive``
(the privacy log is a log and is archived too); nothing is silently dropped.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-09
"""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
TABLES = ["provider", "price", "route", "call", "draft", "draft_field", "correction", "case_setting"]
PROVIDERS = [("claude_subscription", "Claude (اشتراک Pro)", None),
             ("anthropic_api", "Anthropic API", None),
             ("openai_api", "OpenAI API", None),
             ("gemini_api", "Gemini API", None),
             ("ollama", "Ollama (محلی)", "http://127.0.0.1:11434"),
             ("openai_compatible", "OpenAI-compatible", None)]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS ai")
    op.execute(f"""
        CREATE TABLE ai.provider (
          id              uuid PRIMARY KEY DEFAULT uuidv7(),
          kind            text NOT NULL CHECK (kind IN ('claude_subscription', 'anthropic_api', 'openai_api', 'gemini_api',
                                                        'ollama', 'openai_compatible')),
          label           text NOT NULL CHECK (btrim(label) <> ''),
          enabled         boolean NOT NULL DEFAULT false,
          base_url        text CHECK (base_url IS NULL OR base_url ~ '^https?://'),
          models          text[] NOT NULL DEFAULT '{{}}',
          secret_name     text CHECK (secret_name IS NULL OR secret_name ~ '^ai\\.[a-z0-9_.-]{{1,60}}$'),
          status          text NOT NULL DEFAULT 'unknown' CHECK (status IN ('unknown', 'ok', 'error')),
          status_detail   text,
          last_checked_at timestamptz,
          last_latency_ms integer,
          {TS},
          UNIQUE (label)
        )""")
    op.execute(f"""
        CREATE TABLE ai.price (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          provider_id        uuid NOT NULL REFERENCES ai.provider (id),
          model              text NOT NULL CHECK (btrim(model) <> ''),
          input_per_mtok     numeric(12,4) NOT NULL CHECK (input_per_mtok >= 0),
          output_per_mtok    numeric(12,4) NOT NULL CHECK (output_per_mtok >= 0),
          {TS},
          UNIQUE (provider_id, model)
        )""")
    op.execute(f"""
        CREATE TABLE ai.route (
          id                   uuid PRIMARY KEY DEFAULT uuidv7(),
          task                 text NOT NULL UNIQUE CHECK (task ~ '^[a-z][a-z0-9_]{{1,60}}$'),
          primary_provider_id  uuid REFERENCES ai.provider (id),
          primary_model        text,
          fallback_provider_id uuid REFERENCES ai.provider (id),
          fallback_model       text,
          privacy              text NOT NULL DEFAULT 'cloud_redacted' CHECK (privacy IN ('cloud', 'cloud_redacted', 'local_only')),
          {TS},
          CONSTRAINT route_fallback_differs CHECK (fallback_provider_id IS NULL OR fallback_provider_id <> primary_provider_id
                                                   OR fallback_model IS DISTINCT FROM primary_model)
        )""")
    op.execute(f"""
        CREATE TABLE ai.call (
          id              uuid PRIMARY KEY DEFAULT uuidv7(),
          task            text NOT NULL,
          entity_type     text,
          entity_id       text,
          case_id         uuid,
          provider_id     uuid REFERENCES ai.provider (id),
          provider_kind   text,
          model           text,
          prompt_version  text,
          input           jsonb NOT NULL DEFAULT '{{}}',
          redactions      jsonb NOT NULL DEFAULT '{{}}',
          privacy         text,
          tokens_in       integer,
          tokens_out      integer,
          cost_usd        numeric(12,6),
          subscription    boolean NOT NULL DEFAULT false,
          duration_ms     integer,
          status          text NOT NULL CHECK (status IN ('ok', 'error', 'invalid_output', 'cap_reached', 'skipped')),
          error           text,
          attempt         integer NOT NULL DEFAULT 1,
          fallback_of_id  uuid REFERENCES ai.call (id),
          job_id          uuid,
          {TS}
        )""")
    op.execute("CREATE INDEX call_created_idx ON ai.call (created_at DESC)")
    op.execute("CREATE INDEX call_case_idx ON ai.call (case_id)")
    op.execute(f"""
        CREATE TABLE ai.draft (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          task               text NOT NULL,
          target_type        text NOT NULL,
          target_id          text,
          case_id            uuid,
          sources            jsonb NOT NULL DEFAULT '[]',
          payload            jsonb NOT NULL DEFAULT '{{}}',
          checks             jsonb NOT NULL DEFAULT '[]',
          status             text NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'ready', 'accepted', 'partly_accepted', 'rejected', 'failed', 'superseded')),
          error              text,
          created_by_call_id uuid REFERENCES ai.call (id),
          job_id             uuid,
          committed_at       timestamptz,
          result             jsonb,
          {TS}
        )""")
    op.execute("CREATE INDEX draft_target_idx ON ai.draft (target_type, target_id)")
    op.execute("CREATE INDEX draft_case_idx ON ai.draft (case_id)")
    op.execute(f"""
        CREATE TABLE ai.draft_field (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          draft_id    uuid NOT NULL REFERENCES ai.draft (id) ON DELETE CASCADE,
          position    integer NOT NULL,
          path        text NOT NULL,
          label       text,
          proposed    jsonb,
          confidence  text NOT NULL DEFAULT 'medium' CHECK (confidence IN ('high', 'medium', 'low')),
          source      jsonb NOT NULL DEFAULT '{{}}',
          decision    text CHECK (decision IN ('accepted', 'edited', 'rejected')),
          final       jsonb,
          {TS},
          UNIQUE (draft_id, path),
          CONSTRAINT draft_field_final CHECK (decision IS NULL OR decision = 'rejected' OR final IS NOT NULL)
        )""")
    op.execute(f"""
        CREATE TABLE ai.correction (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          task        text NOT NULL,
          draft_id    uuid REFERENCES ai.draft (id) ON DELETE SET NULL,
          field       text NOT NULL,
          proposed    jsonb,
          final       jsonb,
          context     text,
          {TS}
        )""")
    op.execute("CREATE INDEX correction_task_idx ON ai.correction (task, created_at DESC)")
    op.execute(f"""
        CREATE TABLE ai.case_setting (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          case_id     uuid NOT NULL UNIQUE,
          local_only  boolean NOT NULL DEFAULT false,
          {TS}
        )""")
    for table in TABLES:
        op.execute(f"CREATE TRIGGER ai_{table}_updated_at BEFORE UPDATE ON ai.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
        op.execute(f"CREATE TRIGGER ai_{table}_audit AFTER INSERT OR UPDATE OR DELETE ON ai.{table} "
                   "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")
    op.execute("ALTER TABLE sys.job DROP CONSTRAINT IF EXISTS job_lane_check")
    op.execute("ALTER TABLE sys.job ADD CONSTRAINT job_lane_check CHECK (lane IN ('default', 'setad', 'ai'))")

    for kind, label, base in PROVIDERS:
        op.execute(f"INSERT INTO ai.provider (kind, label, base_url) VALUES ('{kind}', '{label}', "
                   f"{'NULL' if base is None else repr(base)})")
    op.execute("INSERT INTO ai.route (task, primary_provider_id, fallback_provider_id, privacy) VALUES "
               "('extraction', (SELECT id FROM ai.provider WHERE kind = 'claude_subscription'), "
               " (SELECT id FROM ai.provider WHERE kind = 'anthropic_api'), 'cloud_redacted'), "
               "('drafting', (SELECT id FROM ai.provider WHERE kind = 'claude_subscription'), NULL, 'cloud_redacted'), "
               "('party_parse', (SELECT id FROM ai.provider WHERE kind = 'claude_subscription'), "
               " (SELECT id FROM ai.provider WHERE kind = 'anthropic_api'), 'cloud_redacted'), "
               "('classification', (SELECT id FROM ai.provider WHERE kind = 'ollama'), NULL, 'local_only')")
    # an earlier downgrade archived the owner's AI setup: put it back
    op.execute("""
        DO $$
        BEGIN
          IF to_regclass('sys.downgrade_archive') IS NOT NULL THEN
            UPDATE ai.provider p SET enabled = (a.data->>'enabled')::boolean, base_url = a.data->>'base_url',
                   models = ARRAY(SELECT jsonb_array_elements_text(a.data->'models')), secret_name = a.data->>'secret_name'
              FROM sys.downgrade_archive a
             WHERE a.migration = '0019' AND a.table_name = 'ai.provider' AND a.restored_at IS NULL
               AND a.data->>'kind' = p.kind AND a.data->>'label' = p.label;
            INSERT INTO ai.provider (kind, label, enabled, base_url, models, secret_name)
            SELECT a.data->>'kind', a.data->>'label', (a.data->>'enabled')::boolean, a.data->>'base_url',
                   ARRAY(SELECT jsonb_array_elements_text(a.data->'models')), a.data->>'secret_name'
              FROM sys.downgrade_archive a
             WHERE a.migration = '0019' AND a.table_name = 'ai.provider' AND a.restored_at IS NULL
               AND NOT EXISTS (SELECT 1 FROM ai.provider p WHERE p.label = a.data->>'label');
            INSERT INTO ai.price (provider_id, model, input_per_mtok, output_per_mtok)
            SELECT p.id, a.data->>'model', (a.data->>'input_per_mtok')::numeric, (a.data->>'output_per_mtok')::numeric
              FROM sys.downgrade_archive a JOIN ai.provider p ON p.label = a.data->>'provider_label'
             WHERE a.migration = '0019' AND a.table_name = 'ai.price' AND a.restored_at IS NULL
            ON CONFLICT DO NOTHING;
            UPDATE ai.route r SET primary_provider_id = (SELECT id FROM ai.provider WHERE label = a.data->>'primary_label'),
                   primary_model = a.data->>'primary_model',
                   fallback_provider_id = (SELECT id FROM ai.provider WHERE label = a.data->>'fallback_label'),
                   fallback_model = a.data->>'fallback_model', privacy = a.data->>'privacy'
              FROM sys.downgrade_archive a
             WHERE a.migration = '0019' AND a.table_name = 'ai.route' AND a.restored_at IS NULL AND a.data->>'task' = r.task;
            INSERT INTO ai.correction (task, field, proposed, final, context, created_at)
            SELECT a.data->>'task', a.data->>'field', a.data->'proposed', a.data->'final', a.data->>'context',
                   (a.data->>'created_at')::timestamptz
              FROM sys.downgrade_archive a
             WHERE a.migration = '0019' AND a.table_name = 'ai.correction' AND a.restored_at IS NULL;
            INSERT INTO ai.case_setting (case_id, local_only)
            SELECT a.row_id, (a.data->>'local_only')::boolean
              FROM sys.downgrade_archive a
             WHERE a.migration = '0019' AND a.table_name = 'ai.case_setting' AND a.restored_at IS NULL
            ON CONFLICT DO NOTHING;
            UPDATE sys.downgrade_archive SET restored_at = now()
             WHERE migration = '0019' AND restored_at IS NULL
               AND table_name IN ('ai.provider', 'ai.price', 'ai.route', 'ai.correction', 'ai.case_setting');
          END IF;
        END $$""")


def downgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS sys.downgrade_archive (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
               "migration text NOT NULL, table_name text NOT NULL, row_id uuid, data jsonb NOT NULL, "
               "archived_at timestamptz NOT NULL DEFAULT now(), restored_at timestamptz)")
    op.execute("DROP TRIGGER IF EXISTS sys_downgrade_archive_audit ON sys.downgrade_archive")
    op.execute("CREATE TRIGGER sys_downgrade_archive_audit AFTER INSERT OR UPDATE OR DELETE ON sys.downgrade_archive "
               "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")
    op.execute("INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
               "SELECT '0019', 'ai.provider', id, to_jsonb(p) - 'id' FROM ai.provider p")
    op.execute("INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
               "SELECT '0019', 'ai.price', x.id, to_jsonb(x) - 'id' || jsonb_build_object('provider_label', p.label) "
               "FROM ai.price x JOIN ai.provider p ON p.id = x.provider_id")
    op.execute("INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
               "SELECT '0019', 'ai.route', r.id, to_jsonb(r) - 'id' || jsonb_build_object("
               "'primary_label', (SELECT label FROM ai.provider WHERE id = r.primary_provider_id), "
               "'fallback_label', (SELECT label FROM ai.provider WHERE id = r.fallback_provider_id)) FROM ai.route r")
    for table in ("call", "draft", "draft_field", "correction"):
        op.execute(f"INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
                   f"SELECT '0019', 'ai.{table}', id, to_jsonb(t) - 'id' FROM ai.{table} t")
    op.execute("INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
               "SELECT '0019', 'ai.case_setting', case_id, jsonb_build_object('local_only', local_only) FROM ai.case_setting")
    op.execute("UPDATE sys.job SET lane = 'default', status = CASE WHEN status = 'queued' THEN 'failed' ELSE status END, "
               "last_error = coalesce(last_error, 'AI lane removed by a downgrade') WHERE lane = 'ai'")
    op.execute("ALTER TABLE sys.job DROP CONSTRAINT IF EXISTS job_lane_check")
    op.execute("ALTER TABLE sys.job ADD CONSTRAINT job_lane_check CHECK (lane IN ('default', 'setad'))")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE ai.{table}")
    op.execute("DROP SCHEMA ai")
