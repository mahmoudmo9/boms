"""Parties fixes (v0.2.1): flag-controlled interaction edits/deletes, shared contact numbers, E.164 phones.

- core.interaction_guard: party_id, contact_id, channel, direction, occurred_at may change only when the
  service sets the transaction-local flag ``boms.interaction_edit = 'on'``; no_followup_reason and
  created_at never change.
- DELETE on core.interaction is allowed only with ``boms.allow_interaction_delete = 'on'`` (test-data
  cleanup); core.forbid_change (used by core.event / core.audit) is not touched.
- core.contact_method: the global UNIQUE (type, value_norm) becomes a partial UNIQUE
  (contact_id, type, value_norm) WHERE status = 'active' plus a plain index on (type, value_norm).
- Existing phone/whatsapp value_norm (international digits) get a leading '+' (E.164); not re-parsed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

GUARD_0004 = """
CREATE OR REPLACE FUNCTION core.interaction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.party_id, NEW.contact_id, NEW.channel, NEW.direction, NEW.occurred_at, NEW.no_followup_reason,
      NEW.created_at)
     IS DISTINCT FROM
     (OLD.party_id, OLD.contact_id, OLD.channel, OLD.direction, OLD.occurred_at, OLD.no_followup_reason,
      OLD.created_at) THEN
    RAISE EXCEPTION 'core.interaction: only subject and body can be corrected'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.interaction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.no_followup_reason, NEW.created_at) IS DISTINCT FROM (OLD.no_followup_reason, OLD.created_at) THEN
            RAISE EXCEPTION 'core.interaction: no_followup_reason and created_at cannot change'
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF coalesce(current_setting('boms.interaction_edit', true), '') <> 'on'
             AND (NEW.party_id, NEW.contact_id, NEW.channel, NEW.direction, NEW.occurred_at)
                 IS DISTINCT FROM (OLD.party_id, OLD.contact_id, OLD.channel, OLD.direction, OLD.occurred_at) THEN
            RAISE EXCEPTION 'core.interaction: only subject and body can be corrected'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION core.interaction_delete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF coalesce(current_setting('boms.allow_interaction_delete', true), '') = 'on' THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'core.interaction is not deletable (DELETE rejected)' USING ERRCODE = 'restrict_violation';
        END $$
        """
    )
    op.execute("DROP TRIGGER core_interaction_no_delete ON core.interaction")
    op.execute(
        "CREATE TRIGGER core_interaction_no_delete BEFORE DELETE ON core.interaction "
        "FOR EACH ROW EXECUTE FUNCTION core.interaction_delete_guard()"
    )

    op.execute("ALTER TABLE core.contact_method DROP CONSTRAINT contact_method_unique")
    op.execute(
        "CREATE UNIQUE INDEX contact_method_active_unique ON core.contact_method (contact_id, type, value_norm) "
        "WHERE status = 'active'"
    )
    op.execute("CREATE INDEX contact_method_value_idx ON core.contact_method (type, value_norm)")
    op.execute(
        "UPDATE core.contact_method SET value_norm = '+' || value_norm "
        "WHERE type IN ('phone', 'whatsapp') AND left(value_norm, 1) <> '+'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE core.contact_method SET value_norm = substr(value_norm, 2) "
        "WHERE type IN ('phone', 'whatsapp') AND left(value_norm, 1) = '+'"
    )
    op.execute("DROP INDEX core.contact_method_value_idx")
    op.execute("DROP INDEX core.contact_method_active_unique")
    # Fails if the same number was shared by two contacts after the upgrade; remove those first.
    op.execute("ALTER TABLE core.contact_method ADD CONSTRAINT contact_method_unique UNIQUE (type, value_norm)")

    op.execute("DROP TRIGGER core_interaction_no_delete ON core.interaction")
    op.execute(
        "CREATE TRIGGER core_interaction_no_delete BEFORE DELETE ON core.interaction "
        "FOR EACH ROW EXECUTE FUNCTION core.forbid_change()"
    )
    op.execute("DROP FUNCTION core.interaction_delete_guard()")
    op.execute(GUARD_0004)
