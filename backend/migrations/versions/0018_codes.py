"""Record codes (v0.9.0 section 5), module ``codes`` in schema ``core``.

``core.code_sequence`` (kind, scope = the rendered prefix of the pattern, last number) serves every code; the existing
quote / sales order / PO / invoice sequences are carried over into it (no number changes). A ``code`` column (unique)
is added to inquiries, cases, RFQs, tenders, guarantees, shipments, receipts, deliveries, payment records, claims,
inspections, parties and products, and every existing row gets its code in creation order per kind and year of the
owner's calendar (party: SUP- / CUS- / BP- by the roles it had at creation and its country; product: its HS heading).
An event ``codes`` / ``backfill`` records the counts per kind. The seeded RFQ e-mail templates start their subject
with the code in brackets (``[{code}] Request for Quotation – {case_title}``, section 6.2) where the seeded text is
unchanged; the owner's own wording stays.

Downgrade keeps the codes in ``sys.downgrade_archive``; a later upgrade gives every row its archived code back before
coding the rest (no code changes on a down / up cycle).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-09
"""
import json
import re
from datetime import date

from alembic import op
from sqlalchemy import text

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
# kind -> (table, prefix); the defaults of app/modules/codes/patterns.py at the time of this migration
CODED = {"inquiry": ("ops.inquiry", "INQ"), "case": ('ops."case"', "CS"), "rfq": ("ops.rfq", "RFQ"),
         "tender": ("ops.tender", "TDR"), "guarantee": ("ops.guarantee", "GTE"), "shipment": ("ops.shipment", "SH"),
         "receipt": ("ops.receipt", "RCV"), "delivery": ("ops.delivery", "DLV"), "payment": ("ops.payment_record", "PAY"),
         "claim": ("ops.claim", "CLM"), "inspection": ("ops.inspection", "INS"), "party": ("core.party", None),
         "product": ("core.product", None)}
OLD_SEQUENCES = [("quote", "ops.quote_sequence", "PI"), ("sales_order", "ops.sales_order_sequence", "SO"),
                 ("purchase_order", "ops.purchase_order_sequence", "PO")]
INVOICE_PREFIX = {"INV": "sales_invoice", "CN": "credit_note", "DN": "debit_note"}


SUBJECTS = [("en", "Request for quotation: {case_title}", "[{code}] Request for Quotation – {case_title}"),
            ("fa", "درخواست استعلام قیمت: {case_title}", "[{code}] درخواست استعلام قیمت – {case_title}")]


def _subjects(old_index: int, new_index: int) -> None:
    conn = op.get_bind()
    for row in SUBJECTS:
        conn.execute(text("UPDATE ops.message_template SET subject_template = :new WHERE kind = 'rfq' AND language = :lang "
                          "AND channel = 'email' AND subject_template = :old"),
                     {"lang": row[0], "old": row[old_index], "new": row[new_index]})


def _jalali_year(d: date) -> int:
    from app.modules.sourcing.jalali import to_jalali

    return to_jalali(d)[0]


def _archive_exists(conn) -> bool:
    return bool(conn.execute(text("SELECT to_regclass('sys.downgrade_archive')")).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(f"""CREATE TABLE core.code_sequence (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          kind        text NOT NULL,
          scope       text NOT NULL,
          last_number integer NOT NULL CHECK (last_number >= 0),
          {TS},
          UNIQUE (kind, scope))""")
    op.execute("CREATE TRIGGER core_code_sequence_updated_at BEFORE UPDATE ON core.code_sequence "
               "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    op.execute("CREATE TRIGGER core_code_sequence_audit AFTER INSERT OR UPDATE OR DELETE ON core.code_sequence "
               "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")
    for kind, table, prefix in OLD_SEQUENCES:
        op.execute(f"INSERT INTO core.code_sequence (kind, scope, last_number) "
                   f"SELECT '{kind}', '{prefix}-' || year || '-#', last_number FROM {table}")
    for key, last in conn.execute(text("SELECT key, last_number FROM ops.invoice_sequence")).all():
        prefix = key.split("-", 1)[0]
        op.execute(text("INSERT INTO core.code_sequence (kind, scope, last_number) VALUES (:k, :s, :n)")
                   .bindparams(k=INVOICE_PREFIX.get(prefix, "sales_invoice"), s=f"{key}-#", n=last))
    for table, _p in CODED.values():
        name = table.split(".")[1].strip('"')
        op.execute(f"ALTER TABLE {table} ADD COLUMN code text")
        op.execute(f"CREATE UNIQUE INDEX {name}_code_key ON {table} (code)")

    # ---- backfill ---------------------------------------------------------------------------------------------------
    archived = {}
    if _archive_exists(conn):
        for row_id, data in conn.execute(text("SELECT row_id, data FROM sys.downgrade_archive "
                                              "WHERE migration = '0018' AND restored_at IS NULL AND data ? 'code'")).all():
            archived[str(row_id)] = data["code"]
    calendar = conn.execute(text("SELECT calendar FROM sys.app_user ORDER BY created_at LIMIT 1")).scalar() or "jalali"
    counters: dict[tuple, int] = {}
    for kind, scope, last in conn.execute(text("SELECT kind, scope, last_number FROM core.code_sequence")).all():
        counters[(kind, scope)] = last
    counts = {}
    for kind, (table, prefix) in CODED.items():
        n = 0
        if kind == "party":
            rows = conn.execute(text(
                "SELECT p.id, p.created_at, p.country_iso2, "
                "(SELECT array_agg(r.role ORDER BY r.role) FROM core.party_role r WHERE r.party_id = p.id "
                " AND r.created_at <= p.created_at + interval '5 seconds') AS roles "
                "FROM core.party p ORDER BY p.created_at, p.id")).all()
        elif kind == "product":
            rows = conn.execute(text(f"SELECT id, created_at, hs_code FROM {table} ORDER BY created_at, id")).all()
        else:
            rows = conn.execute(text(f"SELECT id, created_at FROM {table} ORDER BY created_at, id")).all()
        for row in rows:
            code = archived.get(str(row[0]))
            if code is None:
                if kind == "party":
                    roles = set(row[3] or [])
                    role = "BP" if {"buyer", "supplier"} <= roles else "SUP" if "supplier" in roles else "CUS" if "buyer" in roles else "BP"
                    scope = f"{role}-{row[2] or 'XX'}-#"
                elif kind == "product":
                    digits = re.sub(r"\D", "", row[2] or "")
                    scope = f"PRD-{digits[:4] if len(digits) >= 4 else '0000'}-#"
                else:
                    d = row[1].date()
                    year = _jalali_year(d) if calendar == "jalali" else d.year
                    scope = f"{prefix}-{year}-#"
                counters[(kind, scope)] = counters.get((kind, scope), 0) + 1
                code = scope.replace("#", str(counters[(kind, scope)]).zfill(4))
            conn.execute(text(f"UPDATE {table} SET code = :c WHERE id = :i"), {"c": code, "i": row[0]})
            n += 1
        counts[kind] = n
    # restored codes keep their sequences ahead of them
    if _archive_exists(conn):
        for kind, scope, last in conn.execute(text("SELECT data->>'kind', data->>'scope', (data->>'last_number')::int "
                                                   "FROM sys.downgrade_archive WHERE migration = '0018' AND restored_at IS NULL "
                                                   "AND data ? 'scope'")).all():
            counters[(kind, scope)] = max(counters.get((kind, scope), 0), last)
        conn.execute(text("UPDATE sys.downgrade_archive SET restored_at = now() WHERE migration = '0018' AND restored_at IS NULL"))
    for (kind, scope), last in counters.items():
        conn.execute(text("INSERT INTO core.code_sequence (kind, scope, last_number) VALUES (:k, :s, :n) "
                          "ON CONFLICT (kind, scope) DO UPDATE SET last_number = GREATEST(core.code_sequence.last_number, :n)"),
                     {"k": kind, "s": scope, "n": last})
    conn.execute(text("INSERT INTO core.event (actor, entity_type, entity_id, action, data, source) "
                      "VALUES ('migration-0018', 'codes', NULL, 'backfill', CAST(:d AS jsonb), 'script')"),
                 {"d": json.dumps(counts)})
    _subjects(1, 2)


def downgrade() -> None:
    _subjects(2, 1)
    op.execute("CREATE TABLE IF NOT EXISTS sys.downgrade_archive (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
               "migration text NOT NULL, table_name text NOT NULL, row_id uuid, data jsonb NOT NULL, "
               "archived_at timestamptz NOT NULL DEFAULT now(), restored_at timestamptz)")
    op.execute("DROP TRIGGER IF EXISTS sys_downgrade_archive_audit ON sys.downgrade_archive")
    op.execute("CREATE TRIGGER sys_downgrade_archive_audit AFTER INSERT OR UPDATE OR DELETE ON sys.downgrade_archive "
               "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")
    for _kind, (table, _p) in CODED.items():
        op.execute(f"INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
                   f"SELECT '0018', '{table}', id, jsonb_build_object('code', code) FROM {table} WHERE code IS NOT NULL")
    op.execute("INSERT INTO sys.downgrade_archive (migration, table_name, row_id, data) "
               "SELECT '0018', 'core.code_sequence', NULL, jsonb_build_object('kind', kind, 'scope', scope, 'last_number', last_number) "
               "FROM core.code_sequence")
    # the numbered documents keep counting in their own sequences again
    for kind, table, prefix in OLD_SEQUENCES:
        op.execute(f"INSERT INTO {table} (year, last_number) "
                   f"SELECT CAST(split_part(scope, '-', 2) AS integer), last_number FROM core.code_sequence "
                   f"WHERE kind = '{kind}' AND scope ~ '^{prefix}-[0-9]+-#$' "
                   f"ON CONFLICT (year) DO UPDATE SET last_number = GREATEST({table}.last_number, EXCLUDED.last_number)")
    op.execute("INSERT INTO ops.invoice_sequence (key, last_number) "
               "SELECT left(scope, length(scope) - 2), last_number FROM core.code_sequence "
               "WHERE kind IN ('sales_invoice', 'credit_note', 'debit_note') AND scope ~ '^(INV|CN|DN)-[0-9]+-#$' "
               "ON CONFLICT (key) DO UPDATE SET last_number = GREATEST(ops.invoice_sequence.last_number, EXCLUDED.last_number)")
    for _kind, (table, _p) in CODED.items():
        op.execute(f"ALTER TABLE {table} DROP COLUMN code")
    op.execute("DROP TABLE core.code_sequence")
