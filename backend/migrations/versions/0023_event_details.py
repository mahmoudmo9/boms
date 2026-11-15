"""v0.10.1 section 1.7: a shipment event's generated details as structured fields (dates as dates), rendered at display
time in the user's calendar and digits. ``note`` stays the owner's own text.

Additive only: the downgrade drops the column.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-14
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ops.shipment_event ADD COLUMN IF NOT EXISTS details jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE ops.shipment_event DROP COLUMN IF EXISTS details")
