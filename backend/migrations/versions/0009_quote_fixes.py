"""Quote fixes (v0.5.0, section 0): revision numbers and hand-edited terms.

- ``ops.quote.number`` also accepts a version suffix: a revision keeps the base number and adds ``-v<n>``
  (``PI-1405-0001``, ``PI-1405-0001-v2``, ...). The gap-free base sequence counts first versions only.
- ``ops.quote.terms_manual``: true once the owner edited the terms text by hand; the automatic rebuild of the
  terms (draft quotes) then leaves the text alone and the UI offers "rebuild from template" instead.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ops.quote DROP CONSTRAINT quote_number_check")
    op.execute("ALTER TABLE ops.quote ADD CONSTRAINT quote_number_check "
               "CHECK (number ~ '^PI-[0-9]{4}-[0-9]+(-v[0-9]+)?$')")
    op.execute("ALTER TABLE ops.quote ADD COLUMN terms_manual boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE ops.quote DROP COLUMN terms_manual")
    op.execute("ALTER TABLE ops.quote DROP CONSTRAINT quote_number_check")
    # rows with a version suffix (made by 0.5.0) are not rejected retroactively
    op.execute("ALTER TABLE ops.quote ADD CONSTRAINT quote_number_check "
               "CHECK (number ~ '^PI-[0-9]{4}-[0-9]+$') NOT VALID")
