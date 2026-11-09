"""Reference data (v0.9.0 section 4), module ``reference`` in schema ``ref``.

- location: UN/LOCODE (country, 3-character location code, the full 5-character code, name, name without diacritics,
  name_fa curated, subdivision, function flags, coordinates, IATA), with the source release and whether the row was
  confirmed by an official UN/LOCODE file (``verified``).
- airport: IATA / ICAO (OurAirports), linked to a location when the UN/LOCODE carries the IATA code.
- legal_form: ISO 20275 ELF codes, plus Iranian forms curated by BOMS (``curated``).
- container_type: ISO 6346 size/type codes. transport_mode: UN/ECE Recommendation 19. incoterm: Incoterms® 2020.
- dataset_import: one row per import with its report.
``sys.unit`` gains ``unece_code`` (UN/ECE Recommendation 20). New nullable references (the text fields stay):
shipment origin / destination location, shipment event location, Incoterm place location on quotes, sales orders, POs
and invoices, party legal form; ``ops.shipment_container`` gives each container number its ISO 6346 type.

Downgrade keeps user data: the references set on business rows (as natural keys: UN/LOCODE, legal-form code, container
code) and the container rows are copied into ``sys.downgrade_archive`` (kept), and a later upgrade puts them back.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-09
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
REF_TABLES = ["location", "airport", "legal_form", "container_type", "transport_mode", "incoterm", "dataset_import"]
# (table, column, referenced ref table, natural key of the referenced row)
LINKS = [("ops.shipment", "origin_location_id", "location", "unlocode"),
         ("ops.shipment", "destination_location_id", "location", "unlocode"),
         ("ops.shipment_event", "location_id", "location", "unlocode"),
         ("ops.quote", "incoterm_place_location_id", "location", "unlocode"),
         ("ops.sales_order", "incoterm_place_location_id", "location", "unlocode"),
         ("ops.purchase_order", "incoterm_place_location_id", "location", "unlocode"),
         ("ops.sales_invoice", "incoterm_place_location_id", "location", "unlocode"),
         ("core.party", "legal_form_id", "legal_form", "code")]


def _audit(schema: str, table: str) -> None:
    op.execute(f"CREATE TRIGGER {schema}_{table}_updated_at BEFORE UPDATE ON {schema}.{table} "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    op.execute(f"CREATE TRIGGER {schema}_{table}_audit AFTER INSERT OR UPDATE OR DELETE ON {schema}.{table} "
               "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE ref.location (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          country_iso2 text NOT NULL CHECK (country_iso2 ~ '^[A-Z]{{2}}$'),
          code         text NOT NULL CHECK (code ~ '^[A-Z2-9]{{3}}$'),
          unlocode     text NOT NULL UNIQUE CHECK (unlocode = country_iso2 || code),
          name         text NOT NULL,
          name_ascii   text NOT NULL,
          name_fa      text,
          subdivision  text,
          functions    text,
          is_port boolean NOT NULL DEFAULT false, is_rail boolean NOT NULL DEFAULT false,
          is_road boolean NOT NULL DEFAULT false, is_airport boolean NOT NULL DEFAULT false,
          is_postal boolean NOT NULL DEFAULT false, is_multimodal boolean NOT NULL DEFAULT false,
          is_fixed boolean NOT NULL DEFAULT false, is_border boolean NOT NULL DEFAULT false,
          latitude     numeric(9,6),
          longitude    numeric(9,6),
          iata         text CHECK (iata IS NULL OR iata ~ '^[A-Z0-9]{{3}}$'),
          active       boolean NOT NULL DEFAULT true,
          verified     boolean NOT NULL DEFAULT false,
          source       text NOT NULL,
          release      text,
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX location_name_trgm ON ref.location USING gin (lower(name_ascii) gin_trgm_ops)")
    op.execute("CREATE INDEX location_country_idx ON ref.location (country_iso2, code)")
    op.execute(
        f"""
        CREATE TABLE ref.airport (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          iata         text NOT NULL UNIQUE CHECK (iata ~ '^[A-Z0-9]{{3}}$'),
          icao         text,
          name         text NOT NULL,
          name_fa      text,
          city         text,
          country_iso2 text,
          kind         text,
          location_id  uuid REFERENCES ref.location (id),
          active       boolean NOT NULL DEFAULT true,
          source       text NOT NULL,
          release      text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ref.legal_form (
          id              uuid PRIMARY KEY DEFAULT uuidv7(),
          code            text NOT NULL UNIQUE,
          elf_code        text CHECK (elf_code IS NULL OR elf_code ~ '^[A-Z0-9]{{4}}$'),
          country_iso2    text NOT NULL,
          local_name      text NOT NULL,
          transliterated  text,
          name_fa         text,
          abbreviations   text[] NOT NULL DEFAULT '{{}}',
          curated         boolean NOT NULL DEFAULT false,
          active          boolean NOT NULL DEFAULT true,
          source          text NOT NULL,
          release         text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ref.container_type (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          code           text NOT NULL UNIQUE CHECK (code ~ '^[0-9A-Z]{{4}}$'),
          description_en text NOT NULL,
          description_fa text NOT NULL,
          length_ft      numeric(4,1),
          teu            numeric(4,2) NOT NULL,
          active         boolean NOT NULL DEFAULT true,
          source         text NOT NULL,
          release        text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ref.transport_mode (
          id      uuid PRIMARY KEY DEFAULT uuidv7(),
          code    text NOT NULL UNIQUE CHECK (code ~ '^[0-9]$'),
          name_en text NOT NULL,
          name_fa text NOT NULL,
          active  boolean NOT NULL DEFAULT true,
          source  text NOT NULL,
          release text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ref.incoterm (
          id        uuid PRIMARY KEY DEFAULT uuidv7(),
          code      text NOT NULL UNIQUE CHECK (code ~ '^[A-Z]{{3}}$'),
          name_en   text NOT NULL,
          name_fa   text NOT NULL,
          any_mode  boolean NOT NULL,
          version   text NOT NULL DEFAULT '2020',
          position  integer NOT NULL,
          active    boolean NOT NULL DEFAULT true,
          source    text NOT NULL,
          release   text,
          {TS}
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE ref.dataset_import (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          dataset     text NOT NULL,
          release     text,
          source      text NOT NULL,
          file_sha256 text,
          report      jsonb NOT NULL,
          imported_at timestamptz NOT NULL DEFAULT now(),
          {TS}
        )
        """
    )
    for table in REF_TABLES:
        _audit("ref", table)

    op.execute("ALTER TABLE sys.unit ADD COLUMN unece_code text CHECK (unece_code IS NULL OR unece_code ~ '^[A-Z0-9]{2,3}$')")
    for table, column, ref_table, _key in LINKS:
        op.execute(f"ALTER TABLE {table} ADD COLUMN {column} uuid REFERENCES ref.{ref_table} (id)")
    op.execute(
        f"""
        CREATE TABLE ops.shipment_container (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          shipment_id    uuid NOT NULL REFERENCES ops.shipment (id),
          number         text NOT NULL CHECK (number ~ '^[A-Z]{{3}}[UJZ][0-9]{{7}}$'),
          container_type text REFERENCES ref.container_type (code),
          seal_no        text,
          {TS},
          UNIQUE (shipment_id, number)
        )
        """
    )
    _audit("ops", "shipment_container")
    # an earlier downgrade archived the references: they come back once the reference rows exist (see reference-import)
    op.execute("CREATE TABLE IF NOT EXISTS sys.downgrade_archive (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
               "migration text NOT NULL, table_name text NOT NULL, row_id uuid, data jsonb NOT NULL, "
               "archived_at timestamptz NOT NULL DEFAULT now(), restored_at timestamptz)")
    _archive_audit()


ARCHIVE_AUDIT = ("DROP TRIGGER IF EXISTS sys_downgrade_archive_audit ON sys.downgrade_archive",
                 "CREATE TRIGGER sys_downgrade_archive_audit AFTER INSERT OR UPDATE OR DELETE ON sys.downgrade_archive "
                 "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")


def _archive_audit() -> None:
    for statement in ARCHIVE_AUDIT:
        op.execute(statement)


def downgrade() -> None:
    op.execute("CREATE TABLE IF NOT EXISTS sys.downgrade_archive (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
               "migration text NOT NULL, table_name text NOT NULL, row_id uuid, data jsonb NOT NULL, "
               "archived_at timestamptz NOT NULL DEFAULT now(), restored_at timestamptz)")
    _archive_audit()
    for table, column, ref_table, key in LINKS:
        op.execute(f"INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
                   f"SELECT '0017', '{table}', t.id, jsonb_build_object('column', '{column}', 'key', r.{key}) "
                   f"FROM {table} t JOIN ref.{ref_table} r ON r.id = t.{column}")
    op.execute("INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
               "SELECT '0017', 'ops.shipment_container', shipment_id, to_jsonb(c) - 'id' FROM ops.shipment_container c")
    op.execute("DROP TABLE ops.shipment_container")
    for table, column, _ref, _key in LINKS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
    op.execute("ALTER TABLE sys.unit DROP COLUMN unece_code")
    for table in reversed(REF_TABLES):
        op.execute(f"DROP TABLE ref.{table}")
