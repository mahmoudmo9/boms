"""Trading parties: parties, roles + funnel stages, contacts, contact methods, interactions, follow-ups.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

FTS_TEXT_LIMIT = 300000

# role -> [(code, label_fa, label_en, is_terminal)], in funnel order
STAGES = {
    "buyer": [
        ("new_lead", "سرنخ جدید", "New lead", False),
        ("contacted", "تماس گرفته‌شده", "Contacted", False),
        ("in_conversation", "در حال گفتگو", "In conversation", False),
        ("inquiry_received", "استعلام دریافت‌شده", "Inquiry received", False),
        ("quoted", "قیمت داده‌شده", "Quoted", False),
        ("won", "موفق", "Won", True),
        ("lost", "از دست رفته", "Lost", True),
        ("dormant", "راکد", "Dormant", False),
    ],
    "supplier": [
        ("identified", "شناسایی‌شده", "Identified", False),
        ("contacted", "تماس گرفته‌شده", "Contacted", False),
        ("responded", "پاسخ داده", "Responded", False),
        ("qualified", "تأییدشده", "Qualified", False),
        ("in_use", "در حال همکاری", "In use", False),
        ("blacklisted", "فهرست سیاه", "Blacklisted", True),
        ("dormant", "راکد", "Dormant", False),
    ],
}
OTHER_ROLES = ["forwarder", "customs_broker", "agent", "other"]
OTHER_STAGES = [("active", "فعال", "Active", False), ("dormant", "راکد", "Dormant", False)]

TS = """
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
"""

TABLES = ["funnel_stage", "party", "party_role", "contact", "contact_method", "interaction", "followup"]


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def attach_triggers(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER core_{table}_updated_at BEFORE UPDATE ON core.{table} "
        "FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()"
    )
    omit = ", 'body_norm'" if table == "interaction" else ""
    op.execute(
        f"CREATE TRIGGER core_{table}_audit AFTER INSERT OR UPDATE OR DELETE ON core.{table} "
        f"FOR EACH ROW EXECUTE FUNCTION core.audit_row('id'{omit})"
    )


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE core.funnel_stage (
          id          uuid PRIMARY KEY DEFAULT uuidv7(),
          role        text NOT NULL CHECK (role IN ('buyer', 'supplier', 'forwarder', 'customs_broker', 'agent', 'other')),
          code        text NOT NULL,
          sort_order  integer NOT NULL,
          label_fa    text NOT NULL,
          label_en    text NOT NULL,
          is_terminal boolean NOT NULL DEFAULT false,
          {TS},
          UNIQUE (role, code)
        )
        """
    )

    op.execute(
        f"""
        CREATE TABLE core.party (
          id                    uuid PRIMARY KEY DEFAULT uuidv7(),
          name_fa               text,
          name_en               text,
          name_norm             text GENERATED ALWAYS AS
                                  (core.normalize_fa(coalesce(name_fa, '') || ' ' || coalesce(name_en, ''))) STORED,
          kind                  text NOT NULL DEFAULT 'company' CHECK (kind IN ('company', 'person')),
          country_iso2          text REFERENCES sys.country (iso2),
          website               text,
          notes                 text,
          do_not_contact        boolean NOT NULL DEFAULT false,
          do_not_contact_reason text,
          status                text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          ref_company_id        uuid,
          {TS},
          CONSTRAINT party_name_required CHECK (btrim(coalesce(name_fa, '')) <> '' OR btrim(coalesce(name_en, '')) <> ''),
          CONSTRAINT party_dnc_reason CHECK (NOT do_not_contact OR btrim(coalesce(do_not_contact_reason, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX party_name_trgm_idx ON core.party USING gin (name_norm gin_trgm_ops)")
    op.execute("CREATE INDEX party_status_idx ON core.party (status, updated_at DESC)")

    op.execute(
        f"""
        CREATE TABLE core.party_role (
          id               uuid PRIMARY KEY DEFAULT uuidv7(),
          party_id         uuid NOT NULL REFERENCES core.party (id),
          role             text NOT NULL,
          stage            text NOT NULL,
          stage_changed_at timestamptz NOT NULL DEFAULT now(),
          {TS},
          UNIQUE (party_id, role),
          CONSTRAINT party_role_stage_fk FOREIGN KEY (role, stage) REFERENCES core.funnel_stage (role, code)
        )
        """
    )
    op.execute("CREATE INDEX party_role_stage_idx ON core.party_role (role, stage)")

    op.execute(
        f"""
        CREATE TABLE core.contact (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          party_id   uuid NOT NULL REFERENCES core.party (id),
          name_fa    text,
          name_en    text,
          job_title  text,
          is_primary boolean NOT NULL DEFAULT false,
          notes      text,
          status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS},
          CONSTRAINT contact_name_required CHECK (btrim(coalesce(name_fa, '')) <> '' OR btrim(coalesce(name_en, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX contact_party_idx ON core.contact (party_id)")
    op.execute(
        "CREATE INDEX contact_name_trgm_idx ON core.contact USING gin "
        "(core.normalize_fa(coalesce(name_fa, '') || ' ' || coalesce(name_en, '')) gin_trgm_ops)"
    )
    op.execute(
        "CREATE UNIQUE INDEX contact_one_primary ON core.contact (party_id) WHERE is_primary AND status = 'active'"
    )

    op.execute(
        f"""
        CREATE TABLE core.contact_method (
          id         uuid PRIMARY KEY DEFAULT uuidv7(),
          contact_id uuid NOT NULL REFERENCES core.contact (id),
          type       text NOT NULL CHECK (type IN ('whatsapp', 'phone', 'email', 'telegram', 'other')),
          value      text NOT NULL CHECK (btrim(value) <> ''),
          value_norm text NOT NULL CHECK (value_norm <> ''),
          is_primary boolean NOT NULL DEFAULT false,
          status     text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
          {TS},
          CONSTRAINT contact_method_unique UNIQUE (type, value_norm)
        )
        """
    )
    op.execute("CREATE INDEX contact_method_contact_idx ON core.contact_method (contact_id)")
    op.execute("CREATE INDEX contact_method_trgm_idx ON core.contact_method USING gin (value_norm gin_trgm_ops)")

    op.execute(
        f"""
        CREATE TABLE core.interaction (
          id                 uuid PRIMARY KEY DEFAULT uuidv7(),
          party_id           uuid NOT NULL REFERENCES core.party (id),
          contact_id         uuid REFERENCES core.contact (id),
          channel            text NOT NULL CHECK (channel IN ('whatsapp', 'call', 'email', 'tender_portal', 'in_person', 'other')),
          direction          text NOT NULL CHECK (direction IN ('in', 'out')),
          occurred_at        timestamptz NOT NULL,
          subject            text,
          body               text,
          body_norm          text GENERATED ALWAYS AS (core.normalize_fa(body)) STORED,
          no_followup_reason text CHECK (no_followup_reason IS NULL OR btrim(no_followup_reason) <> ''),
          {TS}
        )
        """
    )
    op.execute("CREATE INDEX interaction_party_idx ON core.interaction (party_id, occurred_at DESC)")
    op.execute(
        "CREATE INDEX interaction_fts_idx ON core.interaction USING gin (to_tsvector('simple', "
        f"left(coalesce(core.normalize_fa(subject), '') || ' ' || coalesce(body_norm, ''), {FTS_TEXT_LIMIT})))"
    )
    op.execute(
        "CREATE INDEX interaction_subject_trgm_idx ON core.interaction USING gin "
        "(core.normalize_fa(coalesce(subject, '')) gin_trgm_ops)"
    )

    op.execute(
        f"""
        CREATE TABLE core.followup (
          id             uuid PRIMARY KEY DEFAULT uuidv7(),
          interaction_id uuid REFERENCES core.interaction (id),
          party_id       uuid NOT NULL REFERENCES core.party (id),
          action         text NOT NULL CHECK (btrim(action) <> ''),
          due_on         date NOT NULL,
          status         text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'cancelled')),
          done_at        timestamptz,
          done_note      text,
          {TS},
          CONSTRAINT followup_done_at CHECK (status = 'open' OR done_at IS NOT NULL),
          CONSTRAINT followup_cancel_note CHECK (status <> 'cancelled' OR btrim(coalesce(done_note, '')) <> '')
        )
        """
    )
    op.execute("CREATE INDEX followup_status_due_idx ON core.followup (status, due_on)")
    op.execute("CREATE INDEX followup_party_idx ON core.followup (party_id)")
    op.execute("CREATE INDEX followup_interaction_idx ON core.followup (interaction_id)")

    # Interactions are immutable except subject/body corrections.
    op.execute(
        """
        CREATE FUNCTION core.interaction_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
    )
    op.execute(
        "CREATE TRIGGER core_interaction_guard BEFORE UPDATE ON core.interaction "
        "FOR EACH ROW EXECUTE FUNCTION core.interaction_guard()"
    )
    op.execute(
        "CREATE TRIGGER core_interaction_no_delete BEFORE DELETE ON core.interaction "
        "FOR EACH ROW EXECUTE FUNCTION core.forbid_change()"
    )

    # Next action is mandatory: at commit, a new interaction has exactly one of
    # (a follow-up created from it) or (a no_followup_reason). The service checks first; this is the backstop.
    op.execute(
        """
        CREATE FUNCTION core.interaction_next_action_check() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          has_followup boolean;
        BEGIN
          SELECT EXISTS (SELECT 1 FROM core.followup WHERE interaction_id = NEW.id) INTO has_followup;
          IF has_followup = (NEW.no_followup_reason IS NOT NULL) THEN
            RAISE EXCEPTION 'core.interaction %: needs exactly one of a follow-up or a no-follow-up reason', NEW.id
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER core_interaction_next_action AFTER INSERT ON core.interaction "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION core.interaction_next_action_check()"
    )

    for table in TABLES:
        attach_triggers(table)

    rows = []
    for role, stages in STAGES.items():
        for i, (code, fa, en, terminal) in enumerate(stages, start=1):
            rows.append(f"('{role}', '{code}', {i * 10}, {_lit(fa)}, {_lit(en)}, {str(terminal).lower()})")
    for role in OTHER_ROLES:
        for i, (code, fa, en, terminal) in enumerate(OTHER_STAGES, start=1):
            rows.append(f"('{role}', '{code}', {i * 10}, {_lit(fa)}, {_lit(en)}, {str(terminal).lower()})")
    op.execute(
        "INSERT INTO core.funnel_stage (role, code, sort_order, label_fa, label_en, is_terminal) VALUES "
        + ", ".join(rows)
    )


def downgrade() -> None:
    for table in ["followup", "interaction", "contact_method", "contact", "party_role", "party", "funnel_stage"]:
        op.execute(f"DROP TABLE core.{table}")
    op.execute("DROP FUNCTION core.interaction_next_action_check()")
    op.execute("DROP FUNCTION core.interaction_guard()")
