"""Submission (with the blockers checklist) and the result of a tender.

Blockers (all reported together, SetadSuite ``blockers`` extended): participation is yes; every envelope item is
ready or submitted; the bid bond is issued and covers the validity; the financial proposal (summary or quote) is
approved; the proposal deadline has not passed; no expired library document is linked. "Mark submitted" with
blockers left needs a typed reason (event).

Result: won / lost (reason required) / cancelled / no_result, with the winner and our rank when known. Won: the
case's items become ``sold`` (sourcing status function, like an accepted quote) and the case ``won``; a follow-up
"Contract / performance guarantee" 3 days later. Otherwise: open reminders cancelled and the bid-bond release
follow-up. A revised result keeps its history as events and clears ``sold`` correctly.
"""
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing.common import flush, jsonable
from app.modules.tenders import dates as tender_dates
from app.modules.tenders import envelopes, guarantees, reminders
from app.modules.tenders.common import get_tender, tehran_day, today
from app.modules.tenders.models import EnvelopeItem, Guarantee, Tender, TenderProposal, TenderResultReason

RESULTS = ("won", "lost", "cancelled", "no_result")
OPEN_REMINDERS = ("date_reminder", "opening")
APPROVED_QUOTE = ("approved", "sent", "accepted", "partially_accepted", "rejected", "expired")


def bid_bond(db: Session, tender: Tender) -> Guarantee | None:
    return db.scalar(select(Guarantee).where(Guarantee.tender_id == tender.id, Guarantee.purpose == "bid",
                                             Guarantee.status != "cancelled").order_by(Guarantee.created_at).limit(1))


def proposal_approved(db: Session, tender: Tender) -> bool:
    if tender.financial_mode == "buyer_form":
        return db.scalar(select(TenderProposal.id).where(TenderProposal.tender_id == tender.id,
                                                         TenderProposal.status == "approved").limit(1)) is not None
    from app.modules.quotes import service as quotes

    return any(q.status in APPROVED_QUOTE for q in quotes.list_quotes(db, case_id=tender.case_id))


def blockers(db: Session, tender: Tender) -> list[dict]:
    out = []
    if tender.participation != "yes":
        out.append({"code": "participation", "participation": tender.participation})
    items = envelopes.items_of(db, tender.id)
    if not items:
        out.append({"code": "envelopes_empty"})
    left = {e: [i.title for i in items if i.envelope == e and i.status not in envelopes.DONE] for e in envelopes.ENVELOPES}
    if any(left.values()):
        out.append({"code": "envelopes_incomplete", "envelopes": {e: len(v) for e, v in left.items() if v},
                    "titles": [t for v in left.values() for t in v][:5]})
    bid = bid_bond(db, tender)
    if bid is None or bid.status not in guarantees.ISSUED_OR_LATER:
        out.append({"code": "bid_bond_not_issued", "status": bid.status if bid else None})
    short = guarantees.coverage_problem(db, tender, bid)
    if short:
        out.append(short)
    if not proposal_approved(db, tender):
        out.append({"code": "proposal_not_approved", "mode": tender.financial_mode})
    deadline = tender_dates.date_of_kind(db, tender.id, "proposal_deadline")
    if deadline is not None and deadline.at < clock.now():
        out.append({"code": "deadline_passed", "at": deadline.at.isoformat()})
    expired = envelopes.expired_documents(db, tender.id)
    if expired:
        out.append({"code": "company_document_expired", "documents": expired})
    return out


def mark_submitted(db: Session, tender_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> Tender:
    tender = get_tender(db, tender_id)
    if tender.result is not None:
        raise Conflict("tender_has_result", "The tender already has a result", {"result": tender.result})
    found = blockers(db, tender)
    reason = (data.get("override_reason") or "").strip()
    if found and not reason:
        raise AppError("blockers_remain", "The tender is not ready to submit; give a reason to submit anyway",
                       {"blockers": found}, status=422)
    at = data.get("submitted_at") or clock.now()
    tender.submitted_at, tender.submit_channel = at, data.get("channel") or "setad"
    tender.submit_note = data.get("note")
    tender.submit_override_reason = reason or None
    tender.stage = "submitted"
    for item in envelopes.items_of(db, tender.id):
        if item.status != "submitted":
            item.status = "submitted"
    flush(db, "invalid_tender")
    events.record(db, "tender", tender.id, "submitted", jsonable({
        "at": at, "channel": tender.submit_channel, "note": tender.submit_note, "override_reason": reason or None,
        "blockers": found}), source, actor=actor)
    opening = tender_dates.date_of_kind(db, tender.id, "opening")
    if opening is not None and tender.organizer_party_id and tehran_day(opening.at) >= today():
        if not reminders.links(db, tender_id=tender.id, purpose="opening"):
            reminders.create(db, tender_id=tender.id, purpose="opening", ref_id=opening.id, party_id=tender.organizer_party_id,
                             action=f"بازگشایی پاکت‌ها و پیگیری نتیجه {tender.tender_no or ''}".strip(),
                             due_on=tehran_day(opening.at), days_before=0, source=source, actor=actor)
    return tender


def result_reasons(db: Session, include_inactive: bool = False) -> list[TenderResultReason]:
    query = select(TenderResultReason)
    if not include_inactive:
        query = query.where(TenderResultReason.active)
    return list(db.scalars(query.order_by(TenderResultReason.sort_order)))


def set_result(db: Session, tender_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> Tender:
    """Record or revise the result (the previous one stays in the events)."""
    tender = get_tender(db, tender_id)
    result = data["result"]
    if result not in RESULTS:
        raise AppError("invalid_result", "Unknown result", status=422)
    reason = data.get("result_reason")
    if result == "lost" and not reason:
        raise AppError("reason_required", "A lost tender needs a reason", status=422)
    if reason and db.get(TenderResultReason, reason) is None:
        raise AppError("invalid_reason", "Unknown result reason", status=422)
    if data.get("winner_price") is not None and not data.get("winner_price_currency"):
        data["winner_price_currency"] = "IRR"
    old = {k: getattr(tender, k) for k in ("result", "result_reason", "winner_name", "winner_price", "our_rank", "result_on")}
    tender.result, tender.result_reason = result, reason
    for key in ("result_note", "winner_name", "winner_price", "winner_price_currency", "our_rank"):
        setattr(tender, key, data.get(key))
    tender.result_on = data.get("result_on") or today()
    tender.stage = "result"
    flush(db, "invalid_tender")
    events.record(db, "tender", tender.id, "result" if old["result"] is None else "result_revised",
                  jsonable({"old": old, "new": {k: getattr(tender, k) for k in old}, "note": tender.result_note}),
                  source, actor=actor)
    # items: sold while the tender is won (the sourcing status function decides through the registered check)
    item_ids = [i.id for i in sourcing_items.items_of(db, case_id=tender.case_id)]
    sourcing_items.recompute_items(db, item_ids, source, actor, cause="tender_won" if result == "won" else "tender_result")
    case_status = data.get("case_status") or {"won": "won", "lost": "lost", "cancelled": "cancelled", "no_result": "lost"}[result]
    if case_status not in ("won", "lost", "cancelled", "open"):
        raise AppError("invalid_case_status", "The case becomes won, lost, cancelled or stays open", status=422)
    if result == "won":
        case_status = "won"
    sourcing.update_case(db, tender.case_id, {"status": case_status}, source, actor)
    tender_dates.resync_all(db, tender, source, actor, f"tender result: {result}")
    reminders.cancel(db, f"tender result: {result}", source, actor, tender_id=tender.id, purposes=OPEN_REMINDERS)
    bid = bid_bond(db, tender)
    if result == "won":
        reminders.cancel(db, "tender result revised", source, actor, tender_id=tender.id, purposes=("guarantee_release",))
        if tender.organizer_party_id and not reminders.links(db, tender_id=tender.id, purpose="contract"):
            reminders.create(db, tender_id=tender.id, purpose="contract", ref_id=tender.id, party_id=tender.organizer_party_id,
                             action=f"قرارداد / تضمین انجام تعهدات {tender.tender_no or ''}".strip(),
                             due_on=today() + timedelta(days=3), days_before=None, source=source, actor=actor)
    else:
        reminders.cancel(db, "tender result revised", source, actor, tender_id=tender.id, purposes=("contract",))
        if bid is not None:
            guarantees.schedule_release(db, bid, None, source, actor)
    return tender


def on_performance_submitted(db: Session, performance: Guarantee, source: str, actor: str | None) -> None:
    """Won tender: once the performance guarantee is submitted, the bid bond can be released."""
    tender = db.get(Tender, performance.tender_id)
    if tender is None or tender.result != "won":
        return
    bid = bid_bond(db, tender)
    if bid is not None:
        guarantees.schedule_release(db, bid, None, source, actor)


def is_sold(db: Session, line_item_id: uuid.UUID) -> bool:
    """Registered with the sourcing status function: an item of a case whose tender is won (priced as a whole)."""
    from app.modules.sourcing.models import LineItem

    return db.scalar(select(Tender.id).join(LineItem, LineItem.case_id == Tender.case_id)
                     .where(LineItem.id == line_item_id, Tender.result == "won").limit(1)) is not None
