"""The daily command center: follow-ups by due date, stale leads, funnel counts.

"Today" is the PC's local date (``clock.today()``), never the UTC date.
"""

from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.modules.parties import clock, service
from app.modules.parties.models import Followup, FunnelStage, Party, PartyRole
from app.modules.system import settings

STALE_STAGES = {
    "buyer": ("new_lead", "contacted", "in_conversation", "quoted"),
    "supplier": ("identified", "contacted", "responded"),
}
UPCOMING_DAYS = 7


def _followup_rows(db: Session, condition) -> list[dict]:
    rows = db.execute(
        select(Followup, Party)
        .join(Party, Party.id == Followup.party_id)
        .where(Followup.status == "open", condition)
        .order_by(Followup.due_on, Followup.created_at)
    ).all()
    return [{"id": f.id, "party_id": p.id, "party_name_fa": p.name_fa, "party_name_en": p.name_en,
             "do_not_contact": p.do_not_contact, "action": f.action, "due_on": f.due_on,
             "interaction_id": f.interaction_id} for f, p in rows]


def stale_leads(db: Session, days: int) -> list[dict]:
    cutoff = clock.now() - timedelta(days=days)
    clauses = " OR ".join(
        f"(r.role = '{role}' AND r.stage IN ({', '.join(repr(s) for s in stages)}))"
        for role, stages in STALE_STAGES.items()
    )
    rows = db.execute(text(
        f"""
        SELECT p.id, p.name_fa, p.name_en, p.do_not_contact, r.role, r.stage, last.at AS last_interaction_at
        FROM core.party_role r
        JOIN core.party p ON p.id = r.party_id
        LEFT JOIN LATERAL (SELECT max(occurred_at) AS at FROM core.interaction i WHERE i.party_id = p.id) last ON true
        WHERE p.status = 'active' AND ({clauses})
          AND coalesce(last.at, r.stage_changed_at) < :cutoff
        ORDER BY coalesce(last.at, r.stage_changed_at), p.id
        """
    ), {"cutoff": cutoff}).all()
    return [{"party_id": r.id, "party_name_fa": r.name_fa, "party_name_en": r.name_en,
             "do_not_contact": r.do_not_contact, "role": r.role, "stage": r.stage,
             "last_interaction_at": r.last_interaction_at} for r in rows]


def funnel_counts(db: Session) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for stage in db.scalars(select(FunnelStage).order_by(FunnelStage.role, FunnelStage.sort_order)):
        counts.setdefault(stage.role, {})[stage.code] = 0
    rows = db.execute(
        select(PartyRole.role, PartyRole.stage, func.count())
        .join(Party, Party.id == PartyRole.party_id)
        .where(Party.status == "active")
        .group_by(PartyRole.role, PartyRole.stage)
    )
    for role, stage, n in rows:
        counts.setdefault(role, {})[stage] = n
    return counts


def summary(db: Session) -> dict:
    today = clock.today()
    days = int(settings.get(db, "parties.stale_lead_days"))
    overdue = _followup_rows(db, Followup.due_on < today)
    return {
        "today_date": today,
        "overdue": overdue,
        "overdue_count": len(overdue),
        "today": _followup_rows(db, Followup.due_on == today),
        "upcoming_7_days": _followup_rows(db, (Followup.due_on > today)
                                          & (Followup.due_on <= today + timedelta(days=UPCOMING_DAYS))),
        "stale_leads": stale_leads(db, days),
        "stale_lead_days": days,
        "funnel_counts": funnel_counts(db),
    }


def funnel_board(db: Session, role: str) -> dict:
    """Stages of one role with their active parties (cards)."""
    stage_rows = service.stages(db, role)
    parties = db.execute(
        select(PartyRole, Party).join(Party, Party.id == PartyRole.party_id)
        .where(PartyRole.role == role, Party.status == "active")
        .order_by(PartyRole.stage_changed_at.desc())
    ).all()
    activity = service.activity_for(db, [p.id for _, p in parties])
    columns = {s.code: [] for s in stage_rows}
    for role_row, party in parties:
        columns.setdefault(role_row.stage, []).append({
            "party_id": party.id, "name_fa": party.name_fa, "name_en": party.name_en,
            "do_not_contact": party.do_not_contact, "stage_changed_at": role_row.stage_changed_at,
            **activity[party.id]})
    return {"role": role, "stages": [{"code": s.code, "label_fa": s.label_fa, "label_en": s.label_en,
                                      "is_terminal": s.is_terminal, "cards": columns.get(s.code, [])}
                                     for s in stage_rows]}
