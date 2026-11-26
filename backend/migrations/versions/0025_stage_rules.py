"""v0.10.1 section 0.4.3: roles and stages move automatically from what happens, with manual override.

- ``core.party_role.stage_set_by``: who set the current stage — ``initial`` (the role's first stage), ``auto`` (a
  rule) or ``manual`` (the owner, or his «برگرداندن»). A rule never moves a stage the owner set by hand.
- ``core.party_role.dormant_from``: the stage a role had before the dormant job made it dormant; the next activity
  moves it back there.

Backfill: a role still on its first stage is ``initial``; a buyer on «quoted» with the v0.4.0 automatic event
(«quote … sent») is ``auto``; any other stage was chosen by the owner and is ``manual``.
The downgrade drops the two columns.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-26
"""
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.party_role ADD COLUMN IF NOT EXISTS stage_set_by text NOT NULL DEFAULT 'initial'")
    op.execute("ALTER TABLE core.party_role ADD CONSTRAINT party_role_stage_set_by CHECK (stage_set_by IN ('initial', 'auto', 'manual'))")
    op.execute("ALTER TABLE core.party_role ADD COLUMN IF NOT EXISTS dormant_from text")
    op.execute("""
        UPDATE core.party_role r SET stage_set_by = CASE
          WHEN r.stage = (SELECT s.code FROM core.funnel_stage s WHERE s.role = r.role ORDER BY s.sort_order LIMIT 1) THEN 'initial'
          WHEN r.role = 'buyer' AND r.stage = 'quoted' AND EXISTS (
                 SELECT 1 FROM core.event e WHERE e.entity_type = 'party' AND e.entity_id = r.party_id::text
                   AND e.action = 'stage_change' AND e.data ->> 'new_stage' = 'quoted' AND e.data ->> 'reason' LIKE 'quote % sent') THEN 'auto'
          ELSE 'manual' END""")


def downgrade() -> None:
    op.execute("ALTER TABLE core.party_role DROP CONSTRAINT IF EXISTS party_role_stage_set_by")
    op.execute("ALTER TABLE core.party_role DROP COLUMN IF EXISTS stage_set_by")
    op.execute("ALTER TABLE core.party_role DROP COLUMN IF EXISTS dormant_from")
