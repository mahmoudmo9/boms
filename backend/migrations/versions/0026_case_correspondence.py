"""v0.10.1 section 0.4.6: correspondence has a place on the case.

- ``core.interaction.case_id``: the case an interaction concerns (null for a party-only conversation).
- ``core.interaction.ref_type`` / ``ref_id``: the record it concerns — an RFQ recipient, a quote, a purchase order,
  a shipment or an offer.
- ``core.interaction.raw_document_id``: the stored ``.eml`` an incoming e-mail was read from.
- ``ops.rfq_recipient.status`` gains ``question`` («سؤال پرسید»): a reply without a price that asks something;
  ``ops.rfq_recipient.chase_count`` / ``last_chased_at``: the chases sent to this recipient.

Backfill: an interaction created from an RFQ recipient, an offer, a quote or a purchase order gets that record's
case and the link. The downgrade drops the columns, and turns ``question`` back into ``replied``.

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-26
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

REFS = ("rfq_recipient", "quote", "purchase_order", "shipment", "offer")
OLD_STATUSES = ("draft", "sent", "replied", "declined", "no_response", "expired")


def _in(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("ALTER TABLE core.interaction ADD COLUMN IF NOT EXISTS case_id uuid REFERENCES ops.case (id) ON DELETE SET NULL")
    op.execute("ALTER TABLE core.interaction ADD COLUMN IF NOT EXISTS ref_type text")
    op.execute("ALTER TABLE core.interaction ADD COLUMN IF NOT EXISTS ref_id uuid")
    op.execute("ALTER TABLE core.interaction ADD COLUMN IF NOT EXISTS raw_document_id uuid REFERENCES core.document (id)")
    op.execute(f"ALTER TABLE core.interaction ADD CONSTRAINT interaction_ref CHECK ((ref_type IS NULL) = (ref_id IS NULL) "
               f"AND (ref_type IS NULL OR ref_type IN ({_in(REFS)})))")
    op.execute("CREATE INDEX IF NOT EXISTS interaction_case_idx ON core.interaction (case_id, occurred_at DESC) WHERE case_id IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS interaction_ref_idx ON core.interaction (ref_type, ref_id) WHERE ref_id IS NOT NULL")
    # the interactions BOMS made itself from a record know their case
    op.execute("""UPDATE core.interaction i SET case_id = r.case_id, ref_type = 'rfq_recipient', ref_id = rr.id
                  FROM ops.rfq_recipient rr JOIN ops.rfq r ON r.id = rr.rfq_id WHERE rr.interaction_id = i.id""")
    op.execute("""UPDATE core.interaction i SET case_id = o.case_id, ref_type = 'offer', ref_id = o.id
                  FROM ops.supplier_offer o WHERE o.interaction_id = i.id AND i.ref_id IS NULL""")
    op.execute("""UPDATE core.interaction i SET case_id = q.case_id, ref_type = 'quote', ref_id = q.id
                  FROM ops.quote q WHERE q.interaction_id = i.id AND i.ref_id IS NULL""")
    op.execute("""UPDATE core.interaction i SET case_id = po.case_id, ref_type = 'purchase_order', ref_id = po.id
                  FROM ops.purchase_order po WHERE po.interaction_id = i.id AND i.ref_id IS NULL""")
    op.execute("ALTER TABLE ops.rfq_recipient DROP CONSTRAINT rfq_recipient_status_check")
    op.execute(f"ALTER TABLE ops.rfq_recipient ADD CONSTRAINT rfq_recipient_status_check CHECK (status IN ({_in(OLD_STATUSES + ('question',))}))")
    op.execute("ALTER TABLE ops.rfq_recipient ADD COLUMN IF NOT EXISTS chase_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE ops.rfq_recipient ADD COLUMN IF NOT EXISTS last_chased_at timestamptz")


def downgrade() -> None:
    op.execute("UPDATE ops.rfq_recipient SET status = 'replied' WHERE status = 'question'")
    op.execute("ALTER TABLE ops.rfq_recipient DROP CONSTRAINT rfq_recipient_status_check")
    op.execute(f"ALTER TABLE ops.rfq_recipient ADD CONSTRAINT rfq_recipient_status_check CHECK (status IN ({_in(OLD_STATUSES)}))")
    op.execute("ALTER TABLE ops.rfq_recipient DROP COLUMN IF EXISTS chase_count")
    op.execute("ALTER TABLE ops.rfq_recipient DROP COLUMN IF EXISTS last_chased_at")
    op.execute("DROP INDEX IF EXISTS core.interaction_ref_idx")
    op.execute("DROP INDEX IF EXISTS core.interaction_case_idx")
    op.execute("ALTER TABLE core.interaction DROP CONSTRAINT IF EXISTS interaction_ref")
    for col in ("raw_document_id", "ref_id", "ref_type", "case_id"):
        op.execute(f"ALTER TABLE core.interaction DROP COLUMN IF EXISTS {col}")
