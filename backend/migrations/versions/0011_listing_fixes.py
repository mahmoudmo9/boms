"""v0.6.0 section 0: the guarantee and estimate of a Setad tender as the site gives them (currency, description);
the agent's per-listing progress (which listing, attachment n of m) for the screening workspace.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

COLUMNS = ("guarantee_currency", "guarantee_description", "estimate_currency")


AGENT_COLUMNS = ("listing_id uuid", "files_done integer", "files_total integer")


def upgrade() -> None:
    for column in COLUMNS:
        op.execute(f"ALTER TABLE ext.listing ADD COLUMN {column} text")
    for column in AGENT_COLUMNS:
        op.execute(f"ALTER TABLE ext.agent_status ADD COLUMN {column}")


def downgrade() -> None:
    for column in AGENT_COLUMNS:
        op.execute(f"ALTER TABLE ext.agent_status DROP COLUMN {column.split()[0]}")
    for column in COLUMNS:
        op.execute(f"ALTER TABLE ext.listing DROP COLUMN {column}")
