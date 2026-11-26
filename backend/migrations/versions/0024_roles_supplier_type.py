"""v0.10.1 section 0.4.2: the roles «تولیدکننده» (manufacturer) and «حمل‌کننده» (carrier), and the supplier type.

- ``core.funnel_stage``: ``manufacturer`` uses the supplier stages; ``carrier`` (a shipping line, an airline, a road
  haulier — not a forwarder) uses active / dormant.
- ``core.party.supplier_type``: on the supplier side of a party — manufacturer, trading company, distributor, agent.

Existing parties keep their roles and codes. The downgrade keeps the data it can: a manufacturer role becomes a
supplier role (same stages) unless the party already has one, a carrier role becomes «other» (same stages) unless
the party already has one; then the stages, the check and the column go.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-26
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

OLD_ROLES = ("buyer", "supplier", "forwarder", "customs_broker", "agent", "other")
NEW_ROLES = OLD_ROLES + ("manufacturer", "carrier")
CARRIER_STAGES = [("active", "فعال", "Active", False), ("dormant", "راکد", "Dormant", False)]


def _check(roles) -> str:
    return ", ".join(f"'{r}'" for r in roles)


def upgrade() -> None:
    op.execute("ALTER TABLE core.funnel_stage DROP CONSTRAINT funnel_stage_role_check")
    op.execute(f"ALTER TABLE core.funnel_stage ADD CONSTRAINT funnel_stage_role_check CHECK (role IN ({_check(NEW_ROLES)}))")
    # a manufacturer moves through the supplier stages (copied, so each role keeps its own rows)
    op.execute("""
        INSERT INTO core.funnel_stage (role, code, sort_order, label_fa, label_en, is_terminal)
        SELECT 'manufacturer', code, sort_order, label_fa, label_en, is_terminal FROM core.funnel_stage WHERE role = 'supplier'
        ON CONFLICT (role, code) DO NOTHING""")
    for i, (code, fa, en, terminal) in enumerate(CARRIER_STAGES, 1):
        op.execute(f"INSERT INTO core.funnel_stage (role, code, sort_order, label_fa, label_en, is_terminal) "
                   f"VALUES ('carrier', '{code}', {i}, '{fa}', '{en}', {str(terminal).lower()}) ON CONFLICT (role, code) DO NOTHING")
    op.execute("ALTER TABLE core.party ADD COLUMN IF NOT EXISTS supplier_type text")
    op.execute("ALTER TABLE core.party ADD CONSTRAINT party_supplier_type CHECK "
               "(supplier_type IS NULL OR supplier_type IN ('manufacturer', 'trading', 'distributor', 'agent'))")


def downgrade() -> None:
    for new, old in (("manufacturer", "supplier"), ("carrier", "other")):
        op.execute(f"""
            UPDATE core.party_role r SET role = '{old}'
            WHERE r.role = '{new}' AND NOT EXISTS (SELECT 1 FROM core.party_role x WHERE x.party_id = r.party_id AND x.role = '{old}')""")
        op.execute(f"DELETE FROM core.party_role WHERE role = '{new}'")
        op.execute(f"DELETE FROM core.funnel_stage WHERE role = '{new}'")
    op.execute("ALTER TABLE core.funnel_stage DROP CONSTRAINT funnel_stage_role_check")
    op.execute(f"ALTER TABLE core.funnel_stage ADD CONSTRAINT funnel_stage_role_check CHECK (role IN ({_check(OLD_ROLES)}))")
    op.execute("ALTER TABLE core.party DROP CONSTRAINT IF EXISTS party_supplier_type")
    op.execute("ALTER TABLE core.party DROP COLUMN IF EXISTS supplier_type")
