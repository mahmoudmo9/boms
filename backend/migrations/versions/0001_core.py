"""Schemas, extensions, shared SQL functions, append-only event log and audit.

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMAS = ["sys", "ref", "core", "outreach", "tender", "ops", "fin", "compliance", "analytics"]

# Frozen copy of the character tables in app/core/text.py.
# tests/test_text.py asserts the SQL and Python functions agree.
MAP_FROM = (
    "يى"
    "ك"
    "ة"
    "۰۱۲۳۴۵۶۷۸۹"
    "٠١٢٣٤٥٦٧٨٩"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏ"
    "ÐÑÒÓÔÕÖØÙÚÛÜÝÞ"
)
MAP_TO = (
    "یی"
    "ک"
    "ه"
    "01234567890123456789"
    "abcdefghijklmnopqrstuvwxyz"
    "àáâãäåæçèéêëìíîï"
    "ðñòóôõöøùúûüýþ"
)
SPACE_CHARS = (
    "\t\n\u000b\u000c\r\u0085  "
    "           "
    "    　"
    "​‌‍‎‏⁠﻿᠎"
    "‪‫‬‭‮⁦⁧⁨⁩"
)
REMOVE_CHARS = (
    "ـ"
    + "".join(chr(c) for c in range(0x0610, 0x061B))
    + "".join(chr(c) for c in range(0x064B, 0x0660))
    + "ٰ"
)


def _sql_literal(text: str) -> str:
    """Escape-string literal with every non-ASCII/control char as a \\uXXXX escape."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "'":
            out.append("\\'")
        elif 0x20 <= ord(ch) < 0x7F:
            out.append(ch)
        else:
            out.append(f"\\u{ord(ch):04x}")
    return "E'" + "".join(out) + "'"


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    # PostgreSQL 18 has a built-in uuidv7(). On older servers (dev machines) add a
    # compatible implementation in the core schema; column defaults written as
    # uuidv7() then resolve to whichever exists.
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regprocedure('pg_catalog.uuidv7()') IS NULL THEN
            CREATE FUNCTION core.uuidv7() RETURNS uuid
            LANGUAGE sql VOLATILE PARALLEL SAFE AS $f$
              SELECT encode(
                set_bit(set_bit(
                  overlay(uuid_send(gen_random_uuid())
                          PLACING substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
                          FROM 1 FOR 6),
                  52, 1), 53, 1),
                'hex')::uuid
            $f$;
          END IF;
        END $$;
        """
    )

    src = MAP_FROM + SPACE_CHARS + REMOVE_CHARS
    dst = MAP_TO + " " * len(SPACE_CHARS)
    op.execute(
        f"""
        CREATE FUNCTION core.normalize_fa(value text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
          SELECT btrim(regexp_replace(translate(value, {_sql_literal(src)}, {_sql_literal(dst)}), ' {{2,}}', ' ', 'g'), ' ')
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION core.set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          NEW.updated_at := now();
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION '%.% is append-only (% rejected)', TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE core.event (
          id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          occurred_at timestamptz NOT NULL DEFAULT now(),
          actor       text NOT NULL,
          entity_type text NOT NULL,
          entity_id   text,
          action      text NOT NULL,
          data        jsonb NOT NULL DEFAULT '{}'::jsonb,
          source      text NOT NULL CHECK (source IN ('ui', 'api', 'worker', 'script'))
        )
        """
    )
    op.execute("CREATE INDEX event_occurred_at_idx ON core.event (occurred_at DESC, id DESC)")
    op.execute("CREATE INDEX event_entity_idx ON core.event (entity_type, entity_id)")
    op.execute("CREATE INDEX event_action_idx ON core.event (action)")

    op.execute(
        """
        CREATE TABLE core.audit (
          id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
          table_name text NOT NULL,
          row_id     text,
          op         char(1) NOT NULL CHECK (op IN ('I', 'U', 'D')),
          before     jsonb,
          after      jsonb,
          changed_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX audit_row_idx ON core.audit (table_name, row_id)")
    op.execute("CREATE INDEX audit_changed_at_idx ON core.audit (changed_at DESC)")

    for table in ("core.event", "core.audit"):
        name = table.split(".")[1]
        op.execute(
            f"CREATE TRIGGER {name}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION core.forbid_change()"
        )
        op.execute(
            f"CREATE TRIGGER {name}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION core.forbid_change()"
        )
        # The app role owns the table; remove its own UPDATE/DELETE/TRUNCATE rights.
        op.execute(f"REVOKE UPDATE, DELETE, TRUNCATE ON {table} FROM CURRENT_USER")

    # Generic audit trigger. TG_ARGV[0] = primary key column, TG_ARGV[1..] = columns to omit.
    op.execute(
        """
        CREATE FUNCTION core.audit_row() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          b jsonb;
          a jsonb;
          i int;
        BEGIN
          IF TG_OP <> 'INSERT' THEN b := to_jsonb(OLD); END IF;
          IF TG_OP <> 'DELETE' THEN a := to_jsonb(NEW); END IF;
          FOR i IN 1 .. TG_NARGS - 1 LOOP
            b := b - TG_ARGV[i];
            a := a - TG_ARGV[i];
          END LOOP;
          INSERT INTO core.audit (table_name, row_id, op, before, after)
          VALUES (TG_TABLE_SCHEMA || '.' || TG_TABLE_NAME, coalesce(a, b) ->> TG_ARGV[0], left(TG_OP, 1), b, a);
          RETURN NULL;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE core.audit")
    op.execute("DROP TABLE core.event")
    op.execute("DROP FUNCTION core.audit_row()")
    op.execute("DROP FUNCTION core.forbid_change()")
    op.execute("DROP FUNCTION core.set_updated_at()")
    op.execute("DROP FUNCTION core.normalize_fa(text)")
    op.execute("DROP FUNCTION IF EXISTS core.uuidv7()")
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
