"""Seed countries, currencies and units (idempotent).

Revision ID: 0003
Revises: 0002
"""

import json

from alembic import op
from sqlalchemy import text

from app.modules.system.seed_data import seed

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    counts = seed(conn)
    conn.execute(
        text(
            "INSERT INTO core.event (actor, entity_type, entity_id, action, data, source) "
            "VALUES ('system', 'base_data', 'seed', 'base_data.seeded', CAST(:data AS jsonb), 'script')"
        ),
        {"data": json.dumps(counts)},
    )


def downgrade() -> None:
    for table in ("sys.unit", "sys.currency", "sys.country"):
        op.execute(f"DELETE FROM {table}")
