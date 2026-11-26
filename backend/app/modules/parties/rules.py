"""v0.10.1 section 0.4.3: roles and stages move automatically from what happens, with manual override.

Other modules report what happened through ``happened(db, kind, party_id, ...)`` (the parties module's public
service). The rules:

- a role is added when the party is used in it, never removed automatically;
- a stage moves forward only (by the funnel's order), never out of a terminal stage (won, lost, blacklisted) and
  never out of a stage the owner set by hand (``stage_set_by = 'manual'``);
- every automatic change is an event (``role_auto`` / ``stage_auto``) with its rule, its cause and a link, and has a
  one-click «برگرداندن» (``revert``); a reverted change counts as the owner's own choice;
- the dormant job makes a role dormant after ``parties.dormant_days`` without activity, and the next activity moves
  it back to the stage it had;
- each rule can be switched off (setting ``parties.rules.<rule>``);
- ``recompute`` proposes what the rules would have done on the existing data; nothing changes until it is confirmed.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.parties.models import FunnelStage, Party, PartyRole

SUPPLIER_SIDE = ("supplier", "manufacturer")

# kind -> (role or "supplier_side", target stage or None, rule key, add the role when missing)
KINDS: dict[str, tuple[str, str | None, str, bool]] = {
    "inquiry": ("buyer", "inquiry_received", "buyer_inquiry", True),
    "interaction_out": ("buyer", "contacted", "buyer_contacted", False),
    "interaction_in": ("buyer", "in_conversation", "buyer_in_conversation", False),
    "quote_sent": ("buyer", "quoted", "buyer_quoted", True),
    "quote_accepted": ("buyer", "won", "buyer_won", True),
    "sales_order": ("buyer", "won", "buyer_won", True),
    "rfq_recipient": ("supplier_side", None, "roles", True),
    "rfq_sent": ("supplier_side", "contacted", "supplier_contacted", True),
    "offer": ("supplier_side", "responded", "supplier_responded", True),
    "offer_selected": ("supplier_side", "in_use", "supplier_in_use", True),
    "purchase_order": ("supplier_side", "in_use", "supplier_in_use", True),
    "inspection_passed": ("supplier_side", "qualified", "supplier_qualified", False),
    "shipment_carrier": ("carrier", None, "roles", True),
    "shipment_forwarder": ("forwarder", None, "roles", True),
}
RULES = ("roles", "buyer_contacted", "buyer_in_conversation", "buyer_inquiry", "buyer_quoted", "buyer_won",
         "supplier_contacted", "supplier_responded", "supplier_in_use", "supplier_qualified", "dormant")


def enabled(db: Session, rule: str) -> bool:
    from app.modules.system import settings

    return bool(settings.get(db, f"parties.rules.{rule}"))


@dataclass
class Change:
    """One automatic change (applied, or proposed by the recompute)."""
    party_id: uuid.UUID
    role: str
    kind: str                      # "role" (added) or "stage"
    rule: str
    old_stage: str | None
    new_stage: str
    cause: dict = field(default_factory=dict)


def _stage_rows(db: Session) -> dict[str, dict[str, FunnelStage]]:
    out: dict[str, dict[str, FunnelStage]] = {}
    for s in db.scalars(select(FunnelStage).order_by(FunnelStage.role, FunnelStage.sort_order)):
        out.setdefault(s.role, {})[s.code] = s
    return out


def _first(stages: dict[str, FunnelStage]) -> str:
    return min(stages.values(), key=lambda s: s.sort_order).code


@dataclass
class _Role:
    """The rule engine's view of one party role (a real row, or one the recompute simulates)."""
    role: str
    stage: str
    set_by: str
    dormant_from: str | None = None
    row: PartyRole | None = None


def _decide(state: _Role, target: str, stages: dict[str, FunnelStage]) -> str | None:
    """The stage the rule moves to, or None. Forward only; never out of a terminal or a manual stage; a dormant role
    first goes back to the stage it had."""
    current = state.stage
    if state.set_by == "manual":
        return None
    if current == "dormant" and state.dormant_from:
        current = state.dormant_from                 # the next activity: back to where it was, then on
    now, nxt = stages.get(current), stages.get(target)
    if now is None or nxt is None:
        return None
    if now.is_terminal:
        return None
    if nxt.sort_order > now.sort_order:
        return target
    return current if current != state.stage else None


def _plan(db: Session, kind: str, roles: dict[str, _Role], stages_by_role: dict, check=enabled) -> list[Change]:
    """What one happening does to a party's roles (``roles`` is updated in place)."""
    role, target, rule, add = KINDS[kind]
    out: list[Change] = []
    names = [r for r in SUPPLIER_SIDE if r in roles] if role == "supplier_side" else [role] if role in roles else []
    if not names and add and check(db, "roles"):
        name = "supplier" if role == "supplier_side" else role
        first = _first(stages_by_role[name])
        roles[name] = _Role(name, first, "initial")
        out.append(Change(uuid.UUID(int=0), name, "role", "roles", None, first))
        names = [name]
    if target is None or not check(db, rule):
        return out
    for name in names:
        state = roles[name]
        new = _decide(state, target, stages_by_role[name])
        if new and new != state.stage:
            out.append(Change(uuid.UUID(int=0), name, "stage", rule, state.stage, new))
            state.stage, state.set_by, state.dormant_from = new, "auto", None
    return out


def happened(db: Session, kind: str, party_id, *, cause: dict, source: str, actor: str | None = None) -> list[Change]:
    """A thing happened to the party (``cause``: {"entity": "purchase_order", "id": …, "code": "PO-1405-0007"});
    the rules add the role and move the stage, and each change is an event with «برگرداندن»."""
    if party_id is None:
        return []
    party = db.get(Party, party_id)
    if party is None or party.status != "active":
        return []
    woken = wake(db, party.id, cause=cause, source=source, actor=actor) if enabled(db, "dormant") else []
    rows = {r.role: r for r in db.scalars(select(PartyRole).where(PartyRole.party_id == party.id))}
    roles = {name: _Role(name, r.stage, r.stage_set_by, r.dormant_from, r) for name, r in rows.items()}
    changes = _plan(db, kind, roles, _stage_rows(db))
    for c in changes:
        c.party_id, c.cause = party.id, {**cause, "kind": kind}
        state = roles[c.role]
        if c.kind == "role":
            state.row = PartyRole(party_id=party.id, role=c.role, stage=c.new_stage, stage_changed_at=clock.now(),
                                  stage_set_by="initial")
            db.add(state.row)
            db.flush()
            events.record(db, "party", party.id, "role_auto", {"role": c.role, "stage": c.new_stage, "rule": c.rule,
                                                                "cause": c.cause}, source, actor=actor)
        else:
            row = state.row
            row.stage, row.stage_set_by, row.dormant_from, row.stage_changed_at = c.new_stage, "auto", None, clock.now()
            db.flush()
            events.record(db, "party", party.id, "stage_auto", {"role": c.role, "old_stage": c.old_stage,
                                                                 "new_stage": c.new_stage, "rule": c.rule,
                                                                 "cause": c.cause}, source, actor=actor)
    return woken + changes


def revert(db: Session, party_id: uuid.UUID, event_id: int, source: str, actor: str | None = None) -> dict:
    """«برگرداندن» an automatic change: the stage goes back (and then counts as set by the owner, so the rule does
    not redo it), or an automatically added role is removed. Refused when the role changed again since."""
    from app.modules.parties import service

    ev = db.execute(text("SELECT id, action, data FROM core.event WHERE id = :e AND entity_type = 'party' AND entity_id = :p"),
                    {"e": event_id, "p": str(party_id)}).first()
    if ev is None or ev.action not in ("stage_auto", "role_auto"):
        raise NotFound("not_found", "Automatic change not found")
    data = ev.data
    if db.scalar(text("SELECT 1 FROM core.event WHERE entity_type = 'party' AND entity_id = :p AND action = 'auto_revert' "
                      "AND (data ->> 'event_id')::bigint = :e"), {"p": str(party_id), "e": event_id}):
        raise Conflict("already_reverted", "This change was already reverted")
    row = db.scalar(select(PartyRole).where(PartyRole.party_id == party_id, PartyRole.role == data["role"]))
    if ev.action == "role_auto":
        if row is None:
            raise Conflict("role_changed", "The role is no longer there")
        service.remove_role(db, party_id, data["role"], source, actor)
    else:
        if row is None or row.stage != data["new_stage"]:
            raise Conflict("stage_changed", "The stage changed again since", {"stage": row.stage if row else None})
        row.stage, row.stage_set_by, row.dormant_from, row.stage_changed_at = data["old_stage"], "manual", None, clock.now()
        db.flush()
    events.record(db, "party", party_id, "auto_revert", {"event_id": event_id, "role": data["role"], "action": ev.action,
                                                          "stage": data.get("old_stage")}, source, actor=actor)
    return {"reverted": event_id, "role": data["role"]}


# ---- dormant ---------------------------------------------------------------------------------------------------------

LAST_ACTIVITY_SQL = """
    SELECT p.id, greatest(p.created_at,
      (SELECT max(e.occurred_at) FROM core.event e WHERE e.entity_type = 'party' AND e.entity_id = p.id::text
         AND e.action NOT IN ('stage_auto', 'role_auto', 'auto_revert')),
      (SELECT max(i.occurred_at) FROM core.interaction i WHERE i.party_id = p.id),
      (SELECT max(rr.sent_at) FROM ops.rfq_recipient rr WHERE rr.party_id = p.id),
      (SELECT max(o.received_at) FROM ops.supplier_offer o WHERE o.party_id = p.id),
      (SELECT max(q.sent_at) FROM ops.quote q WHERE q.buyer_party_id = p.id),
      (SELECT max(po.created_at) FROM ops.purchase_order po WHERE po.supplier_party_id = p.id),
      (SELECT max(so.created_at) FROM ops.sales_order so WHERE so.customer_party_id = p.id)) AS last
    FROM core.party p WHERE p.status = 'active'
"""


def make_dormant(db: Session, source: str = "worker", now: datetime | None = None,
                 party_ids: set | None = None) -> list[Change]:
    """The nightly job: a role with no activity for ``parties.dormant_days`` becomes dormant (never a terminal or a
    manual stage); it remembers its stage, and the next activity moves it back."""
    from app.modules.system import settings

    if not enabled(db, "dormant"):
        return []
    now = now or clock.now()
    days = int(settings.get(db, "parties.dormant_days"))
    stages_by_role = _stage_rows(db)
    out = []
    for pid, last in db.execute(text(LAST_ACTIVITY_SQL)).all():
        if party_ids is not None and pid not in party_ids:      # (a check on some parties only; the nightly run has none)
            continue
        if last is None or last > now - timedelta(days=days):
            continue
        for row in db.scalars(select(PartyRole).where(PartyRole.party_id == pid)):
            stages = stages_by_role.get(row.role, {})
            if "dormant" not in stages or row.stage == "dormant" or row.stage_set_by == "manual" or stages[row.stage].is_terminal:
                continue
            old = row.stage
            row.dormant_from, row.stage, row.stage_set_by, row.stage_changed_at = old, "dormant", "auto", now
            db.flush()
            cause = {"kind": "inactivity", "days": days, "last_activity": last.isoformat()}
            events.record(db, "party", pid, "stage_auto", {"role": row.role, "old_stage": old, "new_stage": "dormant",
                                                           "rule": "dormant", "cause": cause}, source)
            out.append(Change(pid, row.role, "stage", "dormant", old, "dormant", cause))
    return out


def wake(db: Session, party_id, *, cause: dict, source: str, actor: str | None = None) -> list[Change]:
    """Any activity on a dormant (automatically) role moves it back to the stage it had."""
    out = []
    for row in db.scalars(select(PartyRole).where(PartyRole.party_id == party_id, PartyRole.stage == "dormant",
                                                  PartyRole.stage_set_by == "auto", PartyRole.dormant_from.is_not(None))):
        old_from = row.dormant_from
        row.stage, row.dormant_from, row.stage_changed_at = old_from, None, clock.now()
        db.flush()
        events.record(db, "party", party_id, "stage_auto", {"role": row.role, "old_stage": "dormant", "new_stage": old_from,
                                                             "rule": "dormant", "cause": {**cause, "kind": "activity"}}, source, actor=actor)
        out.append(Change(party_id, row.role, "stage", "dormant", "dormant", old_from, cause))
    return out


# ---- the one-time recompute ------------------------------------------------------------------------------------------

HISTORY_SQL = """
    SELECT party_id, at, kind, entity, id, code FROM (
      SELECT party_id, received_at AS at, 'inquiry' AS kind, 'inquiry' AS entity, id::text, code FROM ops.inquiry WHERE party_id IS NOT NULL
      UNION ALL SELECT party_id, occurred_at, CASE WHEN direction = 'out' THEN 'interaction_out' ELSE 'interaction_in' END,
             'interaction', id::text, NULL FROM core.interaction WHERE direction IN ('in', 'out')
      UNION ALL SELECT buyer_party_id, sent_at, 'quote_sent', 'quote', id::text, number FROM ops.quote WHERE buyer_party_id IS NOT NULL AND sent_at IS NOT NULL
      UNION ALL SELECT buyer_party_id, updated_at, 'quote_accepted', 'quote', id::text, number FROM ops.quote
             WHERE buyer_party_id IS NOT NULL AND status IN ('accepted', 'partially_accepted')
      UNION ALL SELECT customer_party_id, created_at, 'sales_order', 'sales_order', id::text, number FROM ops.sales_order
             WHERE customer_party_id IS NOT NULL AND status <> 'cancelled'
      UNION ALL SELECT rr.party_id, rr.created_at, 'rfq_recipient', 'rfq', r.id::text, r.code FROM ops.rfq_recipient rr JOIN ops.rfq r ON r.id = rr.rfq_id
      UNION ALL SELECT rr.party_id, rr.sent_at, 'rfq_sent', 'rfq', r.id::text, r.code FROM ops.rfq_recipient rr JOIN ops.rfq r ON r.id = rr.rfq_id
             WHERE rr.sent_at IS NOT NULL
      UNION ALL SELECT party_id, received_at, 'offer', 'offer', id::text, NULL FROM ops.supplier_offer WHERE received_at IS NOT NULL
      UNION ALL SELECT o.party_id, li.updated_at, 'offer_selected', 'offer', o.id::text, NULL FROM ops.line_item li
             JOIN ops.offer_item oi ON oi.id = li.selected_offer_item_id JOIN ops.supplier_offer o ON o.id = oi.offer_id
      UNION ALL SELECT supplier_party_id, coalesce(sent_at, approved_at, created_at), 'purchase_order', 'purchase_order', id::text, number
             FROM ops.purchase_order WHERE status NOT IN ('draft', 'cancelled', 'superseded')
      UNION ALL SELECT po.supplier_party_id, i.created_at, 'inspection_passed', 'inspection', i.id::text, NULL FROM ops.inspection i
             JOIN ops.purchase_order po ON po.id = i.purchase_order_id WHERE i.result = 'pass'
      UNION ALL SELECT carrier_party_id, created_at, 'shipment_carrier', 'shipment', id::text, code FROM ops.shipment WHERE carrier_party_id IS NOT NULL
      UNION ALL SELECT forwarder_party_id, created_at, 'shipment_forwarder', 'shipment', id::text, code FROM ops.shipment WHERE forwarder_party_id IS NOT NULL
    ) h WHERE at IS NOT NULL ORDER BY party_id, at
"""


def recompute(db: Session, confirm: bool = False, source: str = "api", actor: str | None = None) -> dict:
    """«بازمحاسبهٔ مراحل»: replays what happened (oldest first) through the rules for every active party and lists
    what would change. With ``confirm`` the changes are made (each one an event with «برگرداندن»); without it
    nothing changes."""
    stages_by_role = _stage_rows(db)
    history: dict[uuid.UUID, list] = {}
    for row in db.execute(text(HISTORY_SQL)).all():
        history.setdefault(row.party_id, []).append(row)
    proposed: list[dict] = []
    for pid, rows in history.items():
        party = db.get(Party, pid)
        if party is None or party.status != "active":
            continue
        real = {r.role: r for r in db.scalars(select(PartyRole).where(PartyRole.party_id == pid))}
        roles = {n: _Role(n, r.stage, r.stage_set_by, r.dormant_from, r) for n, r in real.items()}
        before = {n: r.stage for n, r in roles.items()}
        last_cause: dict[str, dict] = {}
        for h in rows:
            for c in _plan(db, h.kind, roles, stages_by_role):
                last_cause[c.role] = {"kind": h.kind, "entity": h.entity, "id": h.id, "code": h.code, "rule": c.rule}
        for name, state in roles.items():
            if before.get(name) != state.stage:
                proposed.append({"party_id": str(pid), "party_name_fa": party.name_fa, "party_name_en": party.name_en,
                                 "role": name, "from": before.get(name), "to": state.stage,
                                 "added": name not in before, "cause": last_cause.get(name)})
    applied = 0
    if confirm:
        for p in proposed:
            pid = uuid.UUID(p["party_id"])
            cause = {**{k: v for k, v in (p["cause"] or {}).items() if k != "rule"}, "recompute": True}
            kind = cause.get("kind")
            row = db.scalar(select(PartyRole).where(PartyRole.party_id == pid, PartyRole.role == p["role"]))
            if row is None:                                   # the role is added, on its first stage, then moved
                first = _first(stages_by_role[p["role"]])
                row = PartyRole(party_id=pid, role=p["role"], stage=first, stage_changed_at=clock.now(), stage_set_by="initial")
                db.add(row)
                db.flush()
                events.record(db, "party", pid, "role_auto", {"role": p["role"], "stage": first, "rule": "roles", "cause": cause},
                              source, actor=actor)
            if row.stage != p["to"]:
                old = row.stage
                row.stage, row.stage_set_by, row.dormant_from, row.stage_changed_at = p["to"], "auto", None, clock.now()
                db.flush()
                events.record(db, "party", pid, "stage_auto", {
                    "role": p["role"], "old_stage": old, "new_stage": p["to"], "rule": (p["cause"] or {}).get("rule"),
                    "cause": {**cause, "kind": kind}}, source, actor=actor)
            applied += 1
    return {"proposed": proposed, "count": len(proposed), "applied": applied, "confirmed": confirm}


def automatic_changes(db: Session, party_id: uuid.UUID, limit: int = 20) -> list[dict]:
    """The party's automatic changes, newest first, with whether «برگرداندن» is still possible."""
    reverted = {int(x) for x in db.scalars(text(
        "SELECT data ->> 'event_id' FROM core.event WHERE entity_type = 'party' AND entity_id = :p AND action = 'auto_revert'"),
        {"p": str(party_id)})}
    rows = db.execute(text("SELECT id, occurred_at, action, data FROM core.event WHERE entity_type = 'party' AND entity_id = :p "
                           "AND action IN ('stage_auto', 'role_auto') ORDER BY occurred_at DESC, id DESC LIMIT :n"),
                      {"p": str(party_id), "n": limit}).all()
    current = {r.role: r.stage for r in db.scalars(select(PartyRole).where(PartyRole.party_id == party_id))}
    out = []
    for r in rows:
        d = r.data
        can = r.id not in reverted and (d["role"] in current if r.action == "role_auto" else current.get(d["role"]) == d.get("new_stage"))
        out.append({"event_id": r.id, "at": r.occurred_at, "action": r.action, **d, "revertible": can, "reverted": r.id in reverted})
    return out


def suggest_lost(db: Session, party_id: uuid.UUID) -> dict | None:
    """«از دست رفته» stays the owner's call (with a reason); BOMS suggests it when every quote to this buyer was
    rejected or expired and the buyer is not won or lost already."""
    row = db.scalar(select(PartyRole).where(PartyRole.party_id == party_id, PartyRole.role == "buyer"))
    if row is None or row.stage in ("won", "lost"):
        return None
    counts = db.execute(text("""SELECT count(*) AS total, count(*) FILTER (WHERE status IN ('rejected', 'expired')) AS closed
                                FROM ops.quote WHERE buyer_party_id = :p AND status NOT IN ('draft', 'approved', 'withdrawn', 'superseded')"""),
                        {"p": party_id}).one()
    return {"quotes": counts.total} if counts.total and counts.total == counts.closed else None


def check_rule(rule: str) -> str:
    if rule not in RULES:
        raise AppError("invalid_rule", "Unknown rule", {"rule": rule, "valid": list(RULES)}, status=422)
    return rule
