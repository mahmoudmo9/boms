"""Internal tasks (v0.8.0 section 0.1): reminders that are the owner's own work, not follow-ups with a party.

Schema ``core`` (module ``tasks``): ``task`` (title, due date and optional time, status, priority, the case / party it
is about as context only, the module and record it comes from, the date it reminds about, the remind offset).

One-time data move: every follow-up created by BOMS for an internal reminder becomes a task with the same due date,
status, done note and links, and the follow-up is deleted (the audit trigger keeps the record):
- ``ops.tender_followup`` purposes date_reminder -> tender_date, guarantee_expiry, opening, contract;
- ``ops.execution_followup`` purposes step_reminder -> process_step, warranty_end, invoice -> invoice_issue.
Counterparty follow-ups (RFQ chases, PO confirmation / readiness, claims, the guarantee release chase, manual ones)
stay follow-ups. An event ``reminders_moved`` records the counts per kind.

Downgrade drops the tasks: moved reminders are not turned back into follow-ups (restore the pre-update backup instead).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-07
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""
KINDS = ("('tender_date', 'process_step', 'guarantee_expiry', 'warranty_end', 'warranty_remind', 'opening', 'contract', "
         "'invoice_issue', 'manual')")

MOVE = """
WITH moved AS (
  SELECT f.id AS followup_id, f.action, f.due_on, f.status, f.done_at, f.done_note, f.party_id, f.created_at,
         'tenders' AS source,
         CASE l.purpose WHEN 'date_reminder' THEN 'tender_date' ELSE l.purpose END AS source_kind,
         l.ref_id AS source_id, l.days_before,
         coalesce(t.case_id, g.case_id) AS case_id,
         CASE WHEN l.purpose IN ('date_reminder', 'opening') THEN d.at END AS due_at,
         CASE WHEN l.purpose IN ('date_reminder', 'opening') THEN (d.at AT TIME ZONE 'Asia/Tehran')::date
              WHEN l.purpose = 'guarantee_expiry' THEN g.valid_until ELSE f.due_on END AS remind_of_due
  FROM ops.tender_followup l
  JOIN core.followup f ON f.id = l.followup_id
  LEFT JOIN ops.tender t ON t.id = l.tender_id
  LEFT JOIN ops.tender_date d ON d.id = l.ref_id AND l.purpose IN ('date_reminder', 'opening')
  LEFT JOIN ops.guarantee g ON g.id = l.ref_id AND l.purpose = 'guarantee_expiry'
  WHERE l.purpose IN ('date_reminder', 'guarantee_expiry', 'opening', 'contract')
  UNION ALL
  SELECT f.id, f.action, f.due_on, f.status, f.done_at, f.done_note, f.party_id, f.created_at,
         'execution',
         CASE l.purpose WHEN 'step_reminder' THEN 'process_step' WHEN 'invoice' THEN 'invoice_issue' ELSE l.purpose END,
         l.ref_id, l.days_before, l.case_id, NULL::timestamptz,
         CASE WHEN l.purpose = 'step_reminder' THEN s.due_on ELSE f.due_on END
  FROM ops.execution_followup l
  JOIN core.followup f ON f.id = l.followup_id
  LEFT JOIN ops.process_step s ON s.id = l.ref_id AND l.purpose = 'step_reminder'
  WHERE l.purpose IN ('step_reminder', 'warranty_end', 'invoice')
)
INSERT INTO core.task (title, due_on, due_at, status, done_at, done_note, priority, case_id, party_id, source, source_kind,
                       source_id, remind_of_due, remind_days_before, followup_id, created_at)
SELECT action, due_on, due_at, status, done_at, done_note, 'normal', case_id, party_id, source, source_kind, source_id,
       coalesce(remind_of_due, due_on), days_before, followup_id, created_at
FROM moved
"""


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE core.task (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          title              text NOT NULL CHECK (btrim(title) <> ''),
          due_on             date NOT NULL,
          due_at             timestamptz,
          status             text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'cancelled')),
          done_at            timestamptz,
          done_note          text,
          priority           text NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high')),
          case_id            uuid REFERENCES ops."case" (id),
          party_id           uuid REFERENCES core.party (id),
          source             text NOT NULL DEFAULT 'manual',
          source_kind        text NOT NULL DEFAULT 'manual' CHECK (source_kind IN {KINDS}),
          source_id          uuid,
          remind_of_due      date,
          remind_days_before integer,
          followup_id        uuid,
          notes              text,
          {TS},
          CONSTRAINT task_done_at CHECK (status = 'open' OR done_at IS NOT NULL),
          CONSTRAINT task_cancel_note CHECK (status <> 'cancelled' OR btrim(coalesce(done_note, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX task_status_due_idx ON core.task (status, due_on)")
    op.execute("CREATE INDEX task_case_idx ON core.task (case_id) WHERE case_id IS NOT NULL")
    op.execute("CREATE INDEX task_source_idx ON core.task (source, source_kind, source_id)")
    op.execute("CREATE TRIGGER core_task_updated_at BEFORE UPDATE ON core.task FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()")
    op.execute("CREATE TRIGGER core_task_audit AFTER INSERT OR UPDATE OR DELETE ON core.task "
               "FOR EACH ROW EXECUTE FUNCTION core.audit_row('id')")

    # ---- the one-time move of internal reminders ----------------------------------------------------------------
    move_reminders(op.execute)


MOVE_STATEMENTS = (
    MOVE,
    "INSERT INTO core.event (actor, entity_type, entity_id, action, data, source) "
    "SELECT 'migration-0014', 'task', NULL, 'reminders_moved', "
    "coalesce(jsonb_object_agg(source_kind, n), '{}'::jsonb), 'script' "
    "FROM (SELECT source_kind, count(*) AS n FROM core.task t WHERE followup_id IS NOT NULL "
    "      AND EXISTS (SELECT 1 FROM core.followup f WHERE f.id = t.followup_id) GROUP BY source_kind) c",
    "DELETE FROM ops.tender_followup WHERE followup_id IN (SELECT followup_id FROM core.task WHERE followup_id IS NOT NULL)",
    "DELETE FROM ops.execution_followup WHERE followup_id IN (SELECT followup_id FROM core.task WHERE followup_id IS NOT NULL)",
    "DELETE FROM core.followup WHERE id IN (SELECT followup_id FROM core.task WHERE followup_id IS NOT NULL)",
)


def move_reminders(execute) -> None:
    """Internal-reminder follow-ups -> tasks, then the follow-ups and their links are deleted (also used by the test
    on Phase 7b / 8 data)."""
    for statement in MOVE_STATEMENTS:
        execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE core.task")
