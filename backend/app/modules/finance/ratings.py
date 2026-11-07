"""Supplier and customer ratings (v0.8.0), per closed case: 1-5 for quality, timeliness, communication and price (the
customer gets payment behavior instead of price), and an optional one-line note. One rating per party, role and case
(a second save replaces it). Shown on the party page (average per criterion, count, the last 5) and next to each
supplier in the Phase 5 suggestions (read-only; the ranking does not change)."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.finance.models import PartyRating
from app.modules.sourcing.common import flush, jsonable, row_snapshot

CRITERIA = {"supplier": ("quality", "timeliness", "communication", "price"),
            "customer": ("quality", "timeliness", "communication", "payment_behavior")}
ALL = ("quality", "timeliness", "communication", "price", "payment_behavior")


def rateable(db: Session, case_id: uuid.UUID) -> list[dict]:
    """The case's customer (sales order) and every supplier with a PO."""
    from app.modules.execution.models import PurchaseOrder, SalesOrder

    out, seen = [], set()
    for so in db.scalars(select(SalesOrder).where(SalesOrder.case_id == case_id, SalesOrder.status != "cancelled")):
        if (so.customer_party_id, "customer") not in seen:
            seen.add((so.customer_party_id, "customer"))
            out.append({"party_id": so.customer_party_id, "role": "customer"})
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.case_id == case_id,
                                                     PurchaseOrder.status.not_in(("draft", "cancelled", "superseded")))):
        if (po.supplier_party_id, "supplier") not in seen:
            seen.add((po.supplier_party_id, "supplier"))
            out.append({"party_id": po.supplier_party_id, "role": "supplier"})
    return out


def save(db: Session, case_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PartyRating:
    from app.modules.sourcing import inquiries as sourcing

    case = sourcing.get_case(db, case_id)
    if case.status != "closed":
        raise Conflict("case_not_closed", "Ratings are given when the deal is closed", {"status": case.status})
    role, party_id = data["role"], data["party_id"]
    if {"party_id": party_id, "role": role} not in rateable(db, case_id):
        raise AppError("not_a_party_of_the_deal", f"The party is not a {role} of this deal", status=422)
    wrong = [k for k in ALL if k not in CRITERIA[role] and data.get(k) is not None]
    if wrong:
        raise AppError("criterion_not_for_role", f"Not rated for a {role}", {"criteria": wrong}, status=422)
    if not any(data.get(k) is not None for k in CRITERIA[role]):
        raise AppError("score_required", "Give at least one score", status=422)
    row = db.scalar(select(PartyRating).where(PartyRating.case_id == case_id, PartyRating.party_id == party_id,
                                             PartyRating.role == role))
    action = "update" if row else "create"
    if row is None:
        row = PartyRating(case_id=case_id, party_id=party_id, role=role)
        db.add(row)
    for k in CRITERIA[role]:
        setattr(row, k, data.get(k))
    row.note = (data.get("note") or "").strip() or None
    flush(db, "invalid_rating")
    events.record(db, "party_rating", row.id, action, jsonable(row_snapshot(row)), source, actor=actor)
    return row


def ratings_of_case(db: Session, case_id: uuid.UUID) -> list[dict]:
    return [row_snapshot(r) for r in db.scalars(select(PartyRating).where(PartyRating.case_id == case_id))]


def summary(db: Session, party_id: uuid.UUID) -> dict:
    """Average per criterion, count and the last 5 ratings (with the case) of a party."""
    from app.modules.sourcing.models import Case

    avgs = db.execute(select(*[func.avg(getattr(PartyRating, k)) for k in ALL], func.count())
                      .where(PartyRating.party_id == party_id)).one()
    last = db.execute(select(PartyRating, Case.title).join(Case, Case.id == PartyRating.case_id)
                      .where(PartyRating.party_id == party_id).order_by(PartyRating.created_at.desc()).limit(5)).all()
    return jsonable({"count": avgs[-1], "average": {k: (round(float(v), 2) if v is not None else None) for k, v in zip(ALL, avgs[:-1])},
                     "last": [{**row_snapshot(r), "case_title": title} for r, title in last]})


def supplier_averages(db: Session, party_ids) -> dict:
    """{party_id: {"average": overall average of the supplier criteria, "count": n}} for the suggestions."""
    ids = list(party_ids)
    if not ids:
        return {}
    cols = [getattr(PartyRating, k) for k in CRITERIA["supplier"]]
    rows = db.execute(select(PartyRating.party_id, *[func.avg(c) for c in cols], func.count())
                      .where(PartyRating.party_id.in_(ids), PartyRating.role == "supplier")
                      .group_by(PartyRating.party_id)).all()
    out = {}
    for row in rows:
        values = [float(v) for v in row[1:-1] if v is not None]
        out[str(row[0])] = {"average": round(sum(values) / len(values), 2) if values else None, "count": row[-1]}
    return out
