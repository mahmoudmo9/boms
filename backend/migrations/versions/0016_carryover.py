"""v0.9.0 section 0: a draft credit note created from a customer claim keeps the link to that claim
(``ops.sales_invoice.claim_id``).

Downgrade removes the column only while no invoice uses it (no silent loss of user data); otherwise it stops with a
message.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ops.sales_invoice ADD COLUMN claim_id uuid REFERENCES ops.claim (id)")
    op.execute("CREATE INDEX sales_invoice_claim_idx ON ops.sales_invoice (claim_id) WHERE claim_id IS NOT NULL")


def downgrade() -> None:
    from sqlalchemy import text

    used = op.get_bind().execute(text("SELECT count(*) FROM ops.sales_invoice WHERE claim_id IS NOT NULL")).scalar()
    if used:
        raise RuntimeError(f"Downgrade below 0016 refused: {used} credit note(s) are linked to a claim. "
                           "Restore the pre-update backup instead.")
    op.execute("ALTER TABLE ops.sales_invoice DROP COLUMN claim_id")
