"""Command center section "Tenders" (v0.6.0)."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.parties import clock
from app.modules.sourcing.common import jsonable
from app.modules.sourcing.models import Case
from app.modules.tenders import envelopes, guarantees, library, reminders, service
from app.modules.tenders.common import date_label
from app.modules.tenders.models import Guarantee, Tender, TenderDate

SOON_DAYS = 3
GUARANTEE_DAYS = 30


def summary(db: Session, today: date) -> dict:
    now = clock.now()
    active = list(db.execute(select(Tender, Case.title).join(Case, Case.id == Tender.case_id)
                             .where(Tender.result.is_(None), Tender.stage != "closed", Case.status == "open")).all())
    by_id = {t.id: (t, title) for t, title in active}
    soon = list(db.scalars(select(TenderDate).where(TenderDate.tender_id.in_(list(by_id)), TenderDate.at >= now,
                                                    TenderDate.at <= now + timedelta(days=SOON_DAYS))
                           .order_by(TenderDate.at))) if by_id else []
    dates_soon = [{"tender_id": d.tender_id, "case_id": by_id[d.tender_id][0].case_id, "case_title": by_id[d.tender_id][1],
                   "tender_no": by_id[d.tender_id][0].tender_no, "kind": d.kind, "label": date_label(d.kind, d.label), "at": d.at}
                  for d in soon]
    incomplete = []
    for d in soon:
        if d.kind != "proposal_deadline":
            continue
        tender, title = by_id[d.tender_id]
        prog = envelopes.progress(envelopes.items_of(db, tender.id))["all"]
        if prog[1] and prog[0] < prog[1]:
            incomplete.append({"tender_id": tender.id, "case_id": tender.case_id, "case_title": title,
                               "tender_no": tender.tender_no, "at": d.at, "done": prog[0], "total": prog[1]})
    g_rows = db.execute(select(Guarantee, Case.title).join(Case, Case.id == Guarantee.case_id)
                        .where(Guarantee.status.not_in(guarantees.CLOSED))).all()
    expiring, awaiting = [], []
    for g, title in g_rows:
        row = {"guarantee_id": g.id, "case_id": g.case_id, "case_title": title, "purpose": g.purpose, "number": g.number,
               "valid_until": g.valid_until, "status": g.status, "amount": g.amount, "currency": g.amount_currency}
        if g.valid_until and g.valid_until <= today + timedelta(days=GUARANTEE_DAYS):
            expiring.append(row)
        if reminders.links(db, purpose=guarantees.RELEASE_PURPOSE, ref_id=g.id):
            awaiting.append(row)
    setad = []
    for t, title in db.execute(select(Tender, Case.title).join(Case, Case.id == Tender.case_id)
                               .where(Tender.listing_id.is_not(None), Tender.stage != "closed")).all():
        changes = service.setad_date_changes(db, t)
        appendices = service.new_appendices(db, t)
        if changes or appendices:
            setad.append({"tender_id": t.id, "case_id": t.case_id, "case_title": title, "tender_no": t.tender_no,
                          "date_changes": len(changes), "new_appendices": appendices})
    waiting = []
    for t, title in db.execute(select(Tender, Case.title).join(Case, Case.id == Tender.case_id)
                               .where(Tender.submitted_at.is_not(None), Tender.result.is_(None))).all():
        opening = db.scalar(select(TenderDate).where(TenderDate.tender_id == t.id, TenderDate.kind == "opening"))
        if opening is not None and opening.at < now:
            waiting.append({"tender_id": t.id, "case_id": t.case_id, "case_title": title, "tender_no": t.tender_no,
                            "opening": opening.at})
    return jsonable({
        "dates_soon": dates_soon, "envelopes_incomplete": incomplete, "guarantees_expiring": expiring,
        "guarantees_release": awaiting, "documents_expiring": library.expiring(db), "setad_changes": setad,
        "waiting_result": waiting,
    })
