"""Schemas, extensions, shared functions, append-only core.event and core.audit.

Revision ID: 0001
Revises:
"""

from alembic import op

from app.core.text import normalize_fa_sql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ["sys", "ref", "core", "outreach", "tender", "ops", "fin", "compliance", "analytics"]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    op.execute(normalize_fa_sql())

    op.execute("""
        CREATE FUNCTION core.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END $$
    """)

    op.execute("""
        CREATE FUNCTION core.reject_modification() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% on %.% is not allowed: table is append-only', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END $$
    """)

    # Generic row audit. TG_ARGV[0] = primary key column. Derived/bulky columns are left out.
    op.execute("""
        CREATE FUNCTION core.audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            b jsonb;
            a jsonb;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                b := to_jsonb(OLD) - 'search_vector' - 'text_content';
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                a := to_jsonb(NEW) - 'search_vector' - 'text_content';
            END IF;
            INSERT INTO core.audit (table_name, row_id, op, before, after)
            VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, coalesce(a, b) ->> TG_ARGV[0], left(TG_OP, 1), b, a);
            RETURN NULL;
        END $$
    """)

    op.execute("""
        CREATE TABLE core.event (
            id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            actor       text NOT NULL,
            entity_type text NOT NULL,
            entity_id   text NOT NULL,
            action      text NOT NULL,
            data        jsonb NOT NULL DEFAULT '{}'::jsonb,
            source      text NOT NULL CHECK (source IN ('ui', 'api', 'worker', 'script'))
        )
    """)
    op.execute("CREATE INDEX event_entity_idx ON core.event (entity_type, entity_id)")
    op.execute("CREATE INDEX event_occurred_idx ON core.event (occurred_at DESC)")
    op.execute("CREATE INDEX event_action_idx ON core.event (action)")

    op.execute("""
        CREATE TABLE core.audit (
            id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            table_name text NOT NULL,
            row_id     text,
            op         char(1) NOT NULL CHECK (op IN ('I', 'U', 'D')),
            before     jsonb,
            after      jsonb,
            changed_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX audit_row_idx ON core.audit (table_name, row_id)")

    for table in ("core.event", "core.audit"):
        name = table.split(".")[1]
        op.execute(
            f"CREATE TRIGGER {name}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION core.reject_modification()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION core.reject_modification()"
        )
        # The app role owns these tables; it gives up its own right to change or remove rows.
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM PUBLIC, CURRENT_USER")


def downgrade() -> None:
    op.execute("DROP TABLE core.audit")
    op.execute("DROP TABLE core.event")
    op.execute("DROP FUNCTION core.audit_row()")
    op.execute("DROP FUNCTION core.reject_modification()")
    op.execute("DROP FUNCTION core.touch_updated_at()")
    op.execute("DROP FUNCTION core.normalize_fa(text)")
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
