"""sys tables: app_user, setting, country, currency, unit, job, backup_run.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# table -> primary key column (used by the audit trigger)
AUDITED = {
    "sys.app_user": "id",
    "sys.setting": "key",
    "sys.country": "iso2",
    "sys.currency": "code",
    "sys.unit": "code",
    "sys.job": "id",
    "sys.backup_run": "id",
}


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sys.app_user (
            id                uuid PRIMARY KEY DEFAULT uuidv7(),
            username          text NOT NULL UNIQUE CHECK (length(username) BETWEEN 1 AND 64),
            password_hash     text NOT NULL,
            language          text NOT NULL DEFAULT 'fa' CHECK (language IN ('fa', 'en')),
            calendar          text NOT NULL DEFAULT 'jalali' CHECK (calendar IN ('jalali', 'gregorian')),
            digits            text NOT NULL DEFAULT 'fa' CHECK (digits IN ('fa', 'latin')),
            theme             text NOT NULL DEFAULT 'system' CHECK (theme IN ('light', 'dark', 'system')),
            idle_lock_minutes integer NOT NULL DEFAULT 30 CHECK (idle_lock_minutes BETWEEN 1 AND 1440),
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now()
        )
    """)
    # Single-user application: at most one row can ever exist.
    op.execute("CREATE UNIQUE INDEX app_user_single_row ON sys.app_user ((true))")

    op.execute("""
        CREATE TABLE sys.setting (
            key        text PRIMARY KEY,
            value      jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE sys.country (
            iso2       char(2) PRIMARY KEY CHECK (iso2 ~ '^[A-Z]{2}$'),
            iso3       char(3) NOT NULL UNIQUE CHECK (iso3 ~ '^[A-Z]{3}$'),
            name_fa    text NOT NULL,
            name_en    text NOT NULL,
            active     boolean NOT NULL DEFAULT true,
            sort_order integer NOT NULL DEFAULT 100,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE sys.currency (
            code        char(3) PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),
            name_fa     text NOT NULL,
            name_en     text NOT NULL,
            symbol      text NOT NULL DEFAULT '',
            minor_units smallint NOT NULL DEFAULT 2 CHECK (minor_units BETWEEN 0 AND 4),
            active      boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE sys.unit (
            code        text PRIMARY KEY CHECK (code ~ '^[a-z0-9_]{1,20}$'),
            name_fa     text NOT NULL,
            name_en     text NOT NULL,
            kind        text NOT NULL CHECK (kind IN ('count', 'weight', 'length', 'area', 'volume', 'time', 'other')),
            base_factor numeric(24, 12) NOT NULL CHECK (base_factor > 0),
            active      boolean NOT NULL DEFAULT true,
            created_at  timestamptz NOT NULL DEFAULT now(),
            updated_at  timestamptz NOT NULL DEFAULT now()
        )
    """)

    # Search over base data (both languages, normalized).
    for table, cols in (
        ("country", "iso2 || ' ' || iso3 || ' ' || name_fa || ' ' || name_en"),
        ("currency", "code || ' ' || name_fa || ' ' || name_en"),
        ("unit", "code || ' ' || name_fa || ' ' || name_en"),
    ):
        op.execute(f"CREATE INDEX {table}_search_trgm ON sys.{table} USING gin (core.normalize_fa({cols}) gin_trgm_ops)")
        op.execute(
            f"CREATE INDEX {table}_search_fts ON sys.{table} "
            f"USING gin (to_tsvector('simple'::regconfig, core.normalize_fa({cols})))"
        )

    op.execute("""
        CREATE TABLE sys.job (
            id           uuid PRIMARY KEY DEFAULT uuidv7(),
            type         text NOT NULL,
            payload      jsonb NOT NULL DEFAULT '{}'::jsonb,
            status       text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
            attempts     integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
            run_after    timestamptz NOT NULL DEFAULT now(),
            locked_at    timestamptz,
            last_error   text,
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),
            finished_at  timestamptz
        )
    """)
    op.execute("CREATE INDEX job_queue_idx ON sys.job (run_after) WHERE status = 'queued'")
    op.execute("CREATE INDEX job_status_idx ON sys.job (status)")

    op.execute("""
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
            secondary_status     text CHECK (secondary_status IN ('disabled', 'succeeded', 'skipped', 'failed')),
            restore_test_at      timestamptz,
            restore_test_status  text CHECK (restore_test_status IN ('running', 'passed', 'failed')),
            restore_test_details jsonb,
            details              jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at           timestamptz NOT NULL DEFAULT now(),
            updated_at           timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX backup_run_started_idx ON sys.backup_run (started_at DESC)")

    for table, pk in AUDITED.items():
        name = table.split(".")[1]
        op.execute(
            f"CREATE TRIGGER {name}_touch BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION core.touch_updated_at()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_audit AFTER INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION core.audit_row('{pk}')"
        )


def downgrade() -> None:
    for table in reversed(AUDITED):
        op.execute(f"DROP TABLE {table}")
