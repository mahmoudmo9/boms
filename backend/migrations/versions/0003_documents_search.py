"""Documents, document links and global-search indexes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

# Text beyond this many characters is not indexed (tsvector size limit is 1 MB).
FTS_TEXT_LIMIT = 300000

BASEDATA_TRGM = {
    "sys.country": "iso2 || ' ' || iso3 || ' ' || name_fa || ' ' || name_en",
    "sys.currency": "code || ' ' || name_fa || ' ' || name_en",
    "sys.unit": "code || ' ' || name_fa || ' ' || name_en",
}


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE core.document (
          id                uuid PRIMARY KEY DEFAULT uuidv7(),
          sha256            text NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
          original_filename text NOT NULL,
          mime_type         text NOT NULL,
          size_bytes        bigint NOT NULL CHECK (size_bytes >= 0),
          storage_relpath   text NOT NULL,
          title             text NOT NULL,
          notes             text,
          language          text CHECK (language IN ('fa', 'en', 'other')),
          text_content      text,
          text_status       text NOT NULL DEFAULT 'none' CHECK (text_status IN ('none', 'pending', 'done', 'empty', 'failed')),
          search_vector     tsvector GENERATED ALWAYS AS (
              setweight(to_tsvector('simple', coalesce(core.normalize_fa(title), '')), 'A')
           || setweight(to_tsvector('simple', coalesce(core.normalize_fa(original_filename), '')), 'A')
           || setweight(to_tsvector('simple', coalesce(core.normalize_fa(notes), '')), 'B')
           || setweight(to_tsvector('simple', left(coalesce(core.normalize_fa(text_content), ''), {FTS_TEXT_LIMIT})), 'C')
          ) STORED,
          source            text NOT NULL CHECK (source IN ('ui', 'api', 'worker', 'script')),
          uploaded_at       timestamptz NOT NULL DEFAULT now(),
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX document_search_idx ON core.document USING gin (search_vector)")
    op.execute(
        "CREATE INDEX document_trgm_idx ON core.document USING gin "
        "(core.normalize_fa(title || ' ' || original_filename) gin_trgm_ops)"
    )
    op.execute("CREATE INDEX document_uploaded_idx ON core.document (uploaded_at DESC)")

    op.execute(
        """
        CREATE TABLE core.document_link (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          document_id uuid NOT NULL REFERENCES core.document (id),
          entity_type text NOT NULL,
          entity_id   text NOT NULL,
          role        text NOT NULL DEFAULT 'attachment',
          created_at  timestamptz NOT NULL DEFAULT now(),
          UNIQUE (document_id, entity_type, entity_id, role)
        )
        """
    )
    op.execute("CREATE INDEX document_link_entity_idx ON core.document_link (entity_type, entity_id)")

    op.execute(
        "CREATE TRIGGER core_document_updated_at BEFORE UPDATE ON core.document "
        "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER core_document_audit AFTER INSERT OR UPDATE OR DELETE ON core.document "
        "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id', 'text_content', 'search_vector')"
    )
    op.execute(
        "CREATE TRIGGER core_document_link_audit AFTER INSERT OR UPDATE OR DELETE ON core.document_link "
        "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')"
    )

    for table, expr in BASEDATA_TRGM.items():
        name = table.split(".")[1]
        op.execute(f"CREATE INDEX {name}_trgm_idx ON {table} USING gin (core.normalize_fa({expr}) gin_trgm_ops)")


def downgrade() -> None:
    for table in BASEDATA_TRGM:
        op.execute(f"DROP INDEX {table.split('.')[0]}.{table.split('.')[1]}_trgm_idx")
    op.execute("DROP TABLE core.document_link")
    op.execute("DROP TABLE core.document")
