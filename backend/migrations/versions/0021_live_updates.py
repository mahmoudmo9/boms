"""Live page updates (v0.10.0 section 6): indexes for the change feed.

The change feed (``app.modules.live``) asks every second for the jobs, Setad files and agent rows changed in the last
few seconds. These indexes keep that a range scan however long the job history grows. No data changes.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-12
"""
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

INDEXES = [("sys_job_updated_at_idx", "sys.job"), ("ext_listing_file_updated_at_idx", "ext.listing_file"),
           ("ext_harvest_run_updated_at_idx", "ext.harvest_run")]


def upgrade() -> None:
    for name, table in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} (updated_at)")


def downgrade() -> None:
    for name, table in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {table.split('.')[0]}.{name}")
