"""Structured item descriptions (v0.9.0 section 7, noun-modifier as in ERP catalogues and ISO 8000 practice).

``core.product_template``: a noun (fa/en) and ordered attributes, each with a UN/ECE unit and allowed values or a range,
and which attributes form the short description. Seeded: pump, valve, pipe, flange, gasket, mechanical seal, electric
motor, resin/chemical. Products and line items keep their free names and specifications and gain ``template_id``,
``attributes`` (validated against the template), a generated canonical description fa/en, and an override flag.

Downgrade: the attributes and descriptions set on products and line items, and the owner's templates, are archived in
``sys.downgrade_archive``; a later upgrade puts them back.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-09
"""
import json

from alembic import op
from sqlalchemy import text

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
COLUMNS = ["template_id uuid REFERENCES core.product_template (id)", "attributes jsonb NOT NULL DEFAULT '{}'",
           "canonical_fa text", "canonical_en text", "canonical_override boolean NOT NULL DEFAULT false"]
TARGETS = ["core.product", "ops.line_item"]


def _a(key, fa, en, unit=None, kind="text", values=None, short=True, minimum=None, maximum=None):
    out = {"key": key, "label_fa": fa, "label_en": en, "type": kind, "short": short}
    if unit:
        out["unit"] = unit
    if values:
        out["values"] = [{"value": v, "fa": f, "en": e} for v, f, e in values]
    if minimum is not None:
        out["min"] = minimum
    if maximum is not None:
        out["max"] = maximum
    return out


MATERIALS = [("cs", "فولاد کربنی", "CARBON STEEL"), ("ss304", "فولاد ضدزنگ ۳۰۴", "SS 304"),
             ("ss316", "فولاد ضدزنگ ۳۱۶", "SS 316"), ("cast_iron", "چدن", "CAST IRON"),
             ("duplex", "داپلکس", "DUPLEX"), ("bronze", "برنز", "BRONZE")]
TEMPLATES = [
    ("pump", "پمپ", "PUMP", [
        _a("type", "نوع", "Type", kind="choice", values=[("centrifugal", "گریز از مرکز", "CENTRIFUGAL"),
                                                       ("gear", "دنده‌ای", "GEAR"), ("screw", "اسکرو", "SCREW"),
                                                       ("diaphragm", "دیافراگمی", "DIAPHRAGM"),
                                                       ("submersible", "شناور", "SUBMERSIBLE")]),
        _a("standard", "استاندارد", "Standard"),
        _a("flow", "دبی", "Flow", "MQH", "number", minimum=0),
        _a("head", "ارتفاع", "Head", "MTR", "number", minimum=0),
        _a("material", "جنس بدنه", "Casing material", kind="choice", values=MATERIALS, short=False),
        _a("power", "توان", "Power", "KWT", "number", minimum=0, short=False)]),
    ("valve", "شیر", "VALVE", [
        _a("type", "نوع", "Type", kind="choice", values=[("gate", "کشویی", "GATE"), ("globe", "سوزنی", "GLOBE"),
                                                       ("ball", "توپی", "BALL"), ("butterfly", "پروانه‌ای", "BUTTERFLY"),
                                                       ("check", "یک‌طرفه", "CHECK")]),
        _a("size", "سایز", "Size", "INH", "number", minimum=0),
        _a("rating", "کلاس فشار", "Pressure class", kind="choice", values=[(c, f"کلاس {c}", f"CLASS {c}") for c in
                                                                           ("150", "300", "600", "900", "1500", "2500")]),
        _a("material", "جنس بدنه", "Body material", kind="choice", values=MATERIALS),
        _a("end", "اتصال", "End connection", kind="choice", values=[("rf", "فلنجی RF", "FLANGED RF"),
                                                                   ("bw", "جوشی", "BUTT WELD"), ("thd", "دنده‌ای", "THREADED")],
           short=False),
        _a("standard", "استاندارد", "Standard", short=False)]),
    ("pipe", "لوله", "PIPE", [
        _a("type", "نوع", "Type", kind="choice", values=[("seamless", "بدون درز", "SEAMLESS"), ("welded", "درزدار", "WELDED")]),
        _a("size", "سایز", "Size", "INH", "number", minimum=0),
        _a("schedule", "اسکجول", "Schedule"),
        _a("material", "جنس", "Material"),
        _a("standard", "استاندارد", "Standard", short=False)]),
    ("flange", "فلنج", "FLANGE", [
        _a("type", "نوع", "Type", kind="choice", values=[("wn", "گردن‌دار", "WELD NECK"), ("so", "اسلیپ‌آن", "SLIP-ON"),
                                                       ("blind", "کور", "BLIND"), ("sw", "ساکت‌ولد", "SOCKET WELD")]),
        _a("size", "سایز", "Size", "INH", "number", minimum=0),
        _a("rating", "کلاس فشار", "Pressure class"),
        _a("face", "رویه", "Facing", kind="choice", values=[("rf", "RF", "RF"), ("ff", "FF", "FF"), ("rtj", "RTJ", "RTJ")]),
        _a("material", "جنس", "Material", short=False)]),
    ("gasket", "واشر", "GASKET", [
        _a("type", "نوع", "Type", kind="choice", values=[("spiral", "اسپیرال", "SPIRAL WOUND"), ("ring", "رینگی", "RING JOINT"),
                                                       ("sheet", "ورقی", "SHEET")]),
        _a("size", "سایز", "Size", "INH", "number", minimum=0),
        _a("rating", "کلاس فشار", "Pressure class"),
        _a("material", "جنس", "Material", short=False)]),
    ("mechanical_seal", "مکانیکال سیل", "MECHANICAL SEAL", [
        _a("type", "نوع", "Type", kind="choice", values=[("single", "تکی", "SINGLE"), ("double", "دوبل", "DOUBLE"),
                                                       ("cartridge", "کارتریجی", "CARTRIDGE")]),
        _a("shaft", "قطر شفت", "Shaft size", "MMT", "number", minimum=0),
        _a("standard", "استاندارد", "Standard"),
        _a("faces", "جنس رینگ‌ها", "Face materials", short=False)]),
    ("electric_motor", "الکتروموتور", "ELECTRIC MOTOR", [
        _a("power", "توان", "Power", "KWT", "number", minimum=0),
        _a("speed", "دور", "Speed", "RPM", "number", minimum=0),
        _a("voltage", "ولتاژ", "Voltage", "VLT", "number", minimum=0),
        _a("protection", "حفاظت", "Protection"),
        _a("efficiency", "کلاس راندمان", "Efficiency class", kind="choice",
           values=[(c, c.upper(), c.upper()) for c in ("ie1", "ie2", "ie3", "ie4")], short=False)]),
    ("resin_chemical", "رزین / ماده شیمیایی", "RESIN", [
        _a("polymer", "نوع", "Polymer"),
        _a("grade", "گرید", "Grade"),
        _a("form", "شکل", "Form", kind="choice", values=[("granule", "گرانول", "GRANULE"), ("powder", "پودر", "POWDER"),
                                                       ("liquid", "مایع", "LIQUID")], short=False),
        _a("mfi", "شاخص جریان مذاب", "Melt flow index", short=False)]),
]


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE core.product_template (
          id           uuid PRIMARY KEY DEFAULT uuidv7(),
          key          text NOT NULL UNIQUE CHECK (key ~ '^[a-z][a-z0-9_]{{1,60}}$'),
          category_id  uuid REFERENCES core.product_category (id),
          noun_fa      text NOT NULL CHECK (btrim(noun_fa) <> ''),
          noun_en      text NOT NULL CHECK (btrim(noun_en) <> ''),
          attributes   jsonb NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(attributes) = 'array'),
          status       text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          seeded       boolean NOT NULL DEFAULT false,
          {TS}
        )""")
    op.execute("CREATE TRIGGER core_product_template_updated_at BEFORE UPDATE ON core.product_template "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    op.execute("CREATE TRIGGER core_product_template_audit AFTER INSERT OR UPDATE OR DELETE ON core.product_template "
               "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")
    conn = op.get_bind()
    for key, fa, en, attrs in TEMPLATES:
        conn.execute(text("INSERT INTO core.product_template (key, noun_fa, noun_en, attributes, seeded) "
                          "VALUES (:k, :fa, :en, CAST(:a AS jsonb), true)"),
                     {"k": key, "fa": fa, "en": en, "a": json.dumps(attrs, ensure_ascii=False)})
    for table in TARGETS:
        op.execute(f"ALTER TABLE {table} " + ", ".join(f"ADD COLUMN {c}" for c in COLUMNS))
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table.split('.')[1]}_attributes_object "
                   "CHECK (jsonb_typeof(attributes) = 'object')")
    # an earlier downgrade archived them: put them back
    op.execute("""
        DO $$
        BEGIN
          IF to_regclass('sys.downgrade_archive') IS NOT NULL THEN
            INSERT INTO core.product_template (key, noun_fa, noun_en, attributes, status)
            SELECT a.data->>'key', a.data->>'noun_fa', a.data->>'noun_en', a.data->'attributes', a.data->>'status'
              FROM sys.downgrade_archive a
             WHERE a.migration = '0020' AND a.table_name = 'core.product_template' AND a.restored_at IS NULL
            ON CONFLICT (key) DO UPDATE SET noun_fa = EXCLUDED.noun_fa, noun_en = EXCLUDED.noun_en,
                   attributes = EXCLUDED.attributes, status = EXCLUDED.status;
            UPDATE core.product p SET template_id = (SELECT id FROM core.product_template WHERE key = a.data->>'template'),
                   attributes = a.data->'attributes', canonical_fa = a.data->>'canonical_fa',
                   canonical_en = a.data->>'canonical_en', canonical_override = (a.data->>'canonical_override')::boolean
              FROM sys.downgrade_archive a
             WHERE a.migration = '0020' AND a.table_name = 'core.product' AND a.restored_at IS NULL AND a.row_id = p.id;
            UPDATE ops.line_item p SET template_id = (SELECT id FROM core.product_template WHERE key = a.data->>'template'),
                   attributes = a.data->'attributes', canonical_fa = a.data->>'canonical_fa',
                   canonical_en = a.data->>'canonical_en', canonical_override = (a.data->>'canonical_override')::boolean
              FROM sys.downgrade_archive a
             WHERE a.migration = '0020' AND a.table_name = 'ops.line_item' AND a.restored_at IS NULL AND a.row_id = p.id;
            UPDATE sys.downgrade_archive SET restored_at = now() WHERE migration = '0020' AND restored_at IS NULL;
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
               "SELECT '0020', 'core.product_template', id, jsonb_build_object('key', key, 'noun_fa', noun_fa, "
               "'noun_en', noun_en, 'attributes', attributes, 'status', status) FROM core.product_template "
               "WHERE NOT seeded OR updated_at > created_at")
    for table in TARGETS:
        op.execute(f"INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
                   f"SELECT '0020', '{table}', t.id, jsonb_build_object('template', pt.key, 'attributes', t.attributes, "
                   f"'canonical_fa', t.canonical_fa, 'canonical_en', t.canonical_en, 'canonical_override', t.canonical_override) "
                   f"FROM {table} t LEFT JOIN core.product_template pt ON pt.id = t.template_id "
                   f"WHERE t.template_id IS NOT NULL OR t.attributes <> '{{}}' OR t.canonical_fa IS NOT NULL "
                   f"OR t.canonical_en IS NOT NULL")
        for col in ("template_id", "attributes", "canonical_fa", "canonical_en", "canonical_override"):
            op.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
    op.execute("DROP TABLE core.product_template")
