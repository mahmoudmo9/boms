"""System tables: user, settings, base data, jobs, backup runs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# table -> (primary key column, columns omitted from audit)
AUDITED = {
    "sys.app_user": ("id", ["password_hash"]),
    "sys.setting": ("key", []),
    "sys.country": ("iso2", []),
    "sys.currency": ("code", []),
    "sys.unit": ("code", []),
    "sys.job": ("id", []),
    "sys.backup_run": ("id", []),
}

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""


def attach_triggers(table: str, pk: str, omit: list[str]) -> None:
    name = table.replace(".", "_")
    op.execute(
        f"CREATE TRIGGER {name}_updated_at BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()"
    )
    args = ", ".join(f"'{a}'" for a in [pk, *omit])
    op.execute(
        f"CREATE TRIGGER {name}_audit AFTER INSERT OR UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION core.audit_row({args})"
    )


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE sys.app_user (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          username          text NOT NULL UNIQUE CHECK (length(btrim(username)) BETWEEN 1 AND 64),
          password_hash     text NOT NULL,
          language          text NOT NULL DEFAULT 'fa' CHECK (language IN ('fa', 'en')),
          calendar          text NOT NULL DEFAULT 'jalali' CHECK (calendar IN ('jalali', 'gregorian')),
          digits            text NOT NULL DEFAULT 'fa' CHECK (digits IN ('fa', 'latin')),
          theme             text NOT NULL DEFAULT 'system' CHECK (theme IN ('light', 'dark', 'system')),
          idle_lock_minutes integer NOT NULL DEFAULT 30 CHECK (idle_lock_minutes BETWEEN 1 AND 1440),
          {TS}
        )
        """
    )
    # Exactly one user: every row has the same index key, so a second insert fails.
    op.execute("CREATE UNIQUE INDEX app_user_single_row ON sys.app_user ((true))")

    op.execute(
        f"""
        CREATE TABLE sys.setting (
          key   text PRIMARY KEY,
          value jsonb NOT NULL,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE sys.country (
          iso2       text PRIMARY KEY CHECK (iso2 ~ '^[A-Z]{{2}}$'),
          iso3       text NOT NULL UNIQUE CHECK (iso3 ~ '^[A-Z]{{3}}$'),
          name_fa    text NOT NULL,
          name_en    text NOT NULL,
          active     boolean NOT NULL DEFAULT true,
          sort_order integer NOT NULL DEFAULT 100,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE sys.currency (
          code        text PRIMARY KEY CHECK (code ~ '^[A-Z]{{3}}$'),
          name_fa     text NOT NULL,
          name_en     text NOT NULL,
          symbol      text,
          minor_units smallint CHECK (minor_units BETWEEN 0 AND 6),
          active      boolean NOT NULL DEFAULT true,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE sys.unit (
          code        text PRIMARY KEY CHECK (code ~ '^[a-z0-9_]{{1,16}}$'),
          name_fa     text NOT NULL,
          name_en     text NOT NULL,
          kind        text NOT NULL CHECK (kind IN ('count', 'weight', 'length', 'area', 'volume', 'time', 'other')),
          base_factor numeric(30, 12) NOT NULL CHECK (base_factor > 0),
          active      boolean NOT NULL DEFAULT true,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE sys.job (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          type         text NOT NULL,
          payload      jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          status       text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
          attempts     integer NOT NULL DEFAULT 0,
          max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
          run_after    timestamptz NOT NULL DEFAULT now(),
          locked_at    timestamptz,
          last_error   text,
          finished_at  timestamptz,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX job_queue_idx ON sys.job (run_after) WHERE status = 'queued'")
    op.execute("CREATE INDEX job_status_idx ON sys.job (status, type)")

    op.execute(
        f"""
        CREATE TABLE sys.backup_run (
          id                   uuid PRIMARY KEY DEFAULT uuidv7(),
          kind                 text NOT NULL CHECK (kind IN ('nightly', 'manual', 'pre_update')),
          started_at           timestamptz NOT NULL DEFAULT now(),
          finished_at          timestamptz,
          status               text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
          db_dump_path         text,
          db_dump_sha256       text,
          db_dump_bytes        bigint,
          files_copied         integer,
          files_bytes          bigint,
          secondary_status     text,
          restore_test_at      timestamptz,
          restore_test_status  text CHECK (restore_test_status IN ('passed', 'failed')),
          restore_test_details jsonb,
          details              jsonb NOT NULL DEFAULT '{{}}'::jsonb,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX backup_run_started_idx ON sys.backup_run (started_at DESC)")

    for table, (pk, omit) in AUDITED.items():
        attach_triggers(table, pk, omit)


def downgrade() -> None:
    for table in reversed(list(AUDITED)):
        op.execute(f"DROP TABLE {table}")
