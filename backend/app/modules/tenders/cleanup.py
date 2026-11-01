"""Case cascade delete (test-data cleanup): the tender with its dates, date changes, addenda, envelopes, guarantees
(with their events), proposals and costs; the follow-ups BOMS created for them are cancelled. Files stay."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.tenders import guarantees, reminders
from app.modules.tenders.common import tender_of_case
from app.modules.tenders.models import (EnvelopeItem, Guarantee, Tender, TenderAddendum, TenderCost, TenderDate,
                                        TenderDateChange, TenderFollowup, TenderProposal, TenderProposalLine)


def cleanup_case(db: Session, case_id: uuid.UUID, note: str, source: str, actor: str | None) -> dict:
    tender = tender_of_case(db, case_id)
    case_guarantees = guarantees.guarantees_of(db, case_id=case_id)
    if tender is None and not case_guarantees:
        return {"counts": {}}
    cancelled = []
    snapshot: dict = {}
    counts: dict[str, int] = {}
    if tender is not None:
        cancelled += reminders.cancel(db, note, source, actor, tender_id=tender.id)
    for g in case_guarantees:
        cancelled += reminders.cancel(db, note, source, actor, ref_id=g.id)
    for g in case_guarantees:
        for item in db.scalars(select(EnvelopeItem).where(EnvelopeItem.guarantee_id == g.id)):
            item.guarantee_id = None
    db.flush()
    if tender is not None:
        groups = [
            ("tender_followups", select(TenderFollowup).where(TenderFollowup.tender_id == tender.id)),
            ("proposal_lines", select(TenderProposalLine).join(TenderProposal, TenderProposal.id == TenderProposalLine.proposal_id)
             .where(TenderProposal.tender_id == tender.id)),
            ("proposals", select(TenderProposal).where(TenderProposal.tender_id == tender.id)
             .order_by(TenderProposal.version.desc())),
            ("envelope_items", select(EnvelopeItem).where(EnvelopeItem.tender_id == tender.id)),
            ("date_changes", select(TenderDateChange).where(TenderDateChange.tender_id == tender.id)),
            ("dates", select(TenderDate).where(TenderDate.tender_id == tender.id)),
            ("addenda", select(TenderAddendum).where(TenderAddendum.tender_id == tender.id)),
            ("costs", select(TenderCost).where(TenderCost.tender_id == tender.id)),
        ]
        for name, query in groups:
            rows = list(db.scalars(query))
            snapshot[name] = [row_snapshot(r) for r in rows]
            counts[f"tender_{name}"] = len(rows)
            if name == "proposals":
                for r in rows:
                    r.supersedes_id = None
                db.flush()
            for r in rows:
                db.delete(r)
            flush(db, "in_use")
    for g in case_guarantees:
        guarantees._delete(db, g, source, actor, note)
    db.execute(TenderFollowup.__table__.delete().where(TenderFollowup.ref_id.in_([g.id for g in case_guarantees])))
    counts["guarantees"] = len(case_guarantees)
    if tender is not None:
        snapshot["tender"] = row_snapshot(tender)
        db.delete(tender)
        flush(db, "in_use")
        counts["tenders"] = 1
    return {"counts": counts, "tender": jsonable(snapshot), "cancelled_followups": [str(i) for i in cancelled]}
