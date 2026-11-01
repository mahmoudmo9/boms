"""The tender part of a case (v0.6.0, Phase 7b).

A tender stays an inquiry and then a case; ``ops.tender`` (1:1 with the case) holds what only tenders need. It is
created when an inquiry of kind ``tender`` becomes a case (sourcing hook), or by "Make this a tender" on any case.
A case that came from a Setad tender listing is prefilled from the listing and its detail page (number, type,
organizer, dates, document price, guarantee as a bid-bond draft, estimate); "Refresh from Setad" shows a diff and
applies only what the owner confirms. Later Setad changes to tracked dates show as a banner with per-date apply.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.events import service as events
from app.modules.listings import service as listings
from app.modules.parties import service as parties
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing.common import flush, jsonable
from app.modules.tenders import dates as tender_dates
from app.modules.tenders.common import (SETAD_DATES, SETAD_STAGES, STAGES, currency_code, get_tender, reason_required,
                                        tender_of_case)
from app.modules.tenders.models import EnvelopeItem, Guarantee, Tender

SETAD_REFRESH_REASON = "به‌روزرسانی از ستاد"
SETAD_CHANGE_REASON = "تمدید/تغییر در ستاد"
APPENDIX_FIELDS = ("renewal_appendix_count", "price_appendix_count", "cancel_appendix_count")
EDITABLE = ("tender_no", "tender_type", "stages", "stage", "participation", "participation_reason", "document_price",
            "document_price_currency", "documents_obtained_at", "estimate", "estimate_currency", "proposal_validity_days",
            "proposal_valid_until", "financial_mode", "organizer_party_id")


# ---- Setad --------------------------------------------------------------------------------------------------------

def _setad_listing(db: Session, case) -> Any | None:
    """The Setad tender listing behind the case (through its inquiry), or None."""
    if case.inquiry_id is None:
        return None
    inquiry = sourcing.get_inquiry(db, case.inquiry_id)
    if inquiry.listing_id is None:
        return None
    try:
        listing = listings.get_listing(db, inquiry.listing_id)
    except Exception:  # the listing was purged
        return None
    return listing if listing.source == "setad_tender" else None


def setad_values(listing) -> dict:
    """What a Setad tender listing says about the tender (the prefill and the "Refresh from Setad" values)."""
    raw = listing.raw or {}
    return {
        "tender_no": listing.external_no or None,
        "tender_type": listing.type_name or None,
        "stages": SETAD_STAGES.get(str(raw.get("type") or "")),
        "document_price": Decimal(listing.document_price) if listing.document_price is not None else None,
        "document_price_currency": "IRR" if listing.document_price is not None else None,
        "estimate": Decimal(listing.estimate) if listing.estimate is not None else None,
        "estimate_currency": currency_code(listing.estimate_currency) if listing.estimate is not None else None,
        "dates": {kind: getattr(listing, field) for field, kind in SETAD_DATES.items() if getattr(listing, field)},
        "guarantee": None if listing.guarantee_amount is None else {
            "amount": Decimal(listing.guarantee_amount), "currency": currency_code(listing.guarantee_currency),
            "description": listing.guarantee_description},
    }


# ---- create ---------------------------------------------------------------------------------------------------------

def create_for_case(db: Session, case_id: uuid.UUID, source: str, actor: str | None = None) -> Tender:
    """"Make this a tender" (or the automatic creation for a tender inquiry): the tender row, the envelope
    checklist from the default template, and the Setad prefill when the case comes from a Setad tender."""
    from app.modules.tenders import costs, envelopes, guarantees

    case = sourcing.get_case(db, case_id)
    if tender_of_case(db, case.id) is not None:
        raise Conflict("already_a_tender", "This case already has a tender part", {"case_id": str(case.id)})
    listing = _setad_listing(db, case)
    tender = Tender(case_id=case.id, organizer_party_id=case.party_id, stage="screening", participation="undecided",
                    financial_mode="buyer_form", appendix_seen={})
    values = setad_values(listing) if listing is not None else None
    if values:
        tender.listing_id = listing.id
        for key in ("tender_no", "tender_type", "stages", "document_price", "document_price_currency", "estimate",
                    "estimate_currency"):
            setattr(tender, key, values[key])
        tender.appendix_seen = {f: getattr(listing, f) for f in APPENDIX_FIELDS if getattr(listing, f) is not None}
        tender.setad_dates_seen = {kind: at.isoformat() for kind, at in values["dates"].items()}
    elif case.inquiry_id:
        inquiry = sourcing.get_inquiry(db, case.inquiry_id)
        tender.tender_no = inquiry.external_no
    db.add(tender)
    flush(db, "invalid_tender")
    events.record(db, "tender", tender.id, "create", jsonable({
        "case_id": case.id, "listing_id": tender.listing_id, "tender_no": tender.tender_no,
        "prefilled_from_setad": values is not None}), source, actor=actor)
    events.record(db, "case", case.id, "tender_add", jsonable({"tender_id": tender.id}), source, actor=actor)
    envelopes.copy_template(db, tender.id, None, source, actor)
    if values:
        for kind, at in values["dates"].items():
            tender_dates.add_date(db, tender.id, {"kind": kind, "at": at, "source": "setad"}, source, actor)
        if values["guarantee"]:
            guarantees.create_guarantee(db, {
                "case_id": case.id, "tender_id": tender.id, "purpose": "bid", "amount": values["guarantee"]["amount"],
                "amount_currency": values["guarantee"]["currency"], "description": values["guarantee"]["description"],
                "beneficiary_party_id": case.party_id}, source, actor)
        if values["document_price"]:
            costs.add_cost(db, tender.id, {"kind": "documents_purchase", "amount": values["document_price"],
                                           "amount_currency": values["document_price_currency"],
                                           "note": f"خرید اسناد مناقصه {tender.tender_no or ''}".strip()}, source, actor)
    return tender


def on_case_converted(db: Session, case, inquiry, source: str, actor: str | None) -> None:
    """Sourcing hook: an inquiry of kind ``tender`` becomes a case with a tender part."""
    if inquiry.kind == "tender" and tender_of_case(db, case.id) is None:
        create_for_case(db, case.id, source, actor)


# ---- update -------------------------------------------------------------------------------------------------------

def update_tender(db: Session, tender_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Tender:
    tender = get_tender(db, tender_id)
    changes = {k: v for k, v in changes.items() if k in EDITABLE}
    if "stage" in changes and changes["stage"] not in STAGES:
        raise AppError("invalid_stage", "Unknown stage", status=422)
    if changes.get("participation") == "no":
        changes["participation_reason"] = reason_required(changes.get("participation_reason", tender.participation_reason))
    if changes.get("organizer_party_id"):
        parties.get_party(db, changes["organizer_party_id"])
    for amount, currency in (("document_price", "document_price_currency"), ("estimate", "estimate_currency")):
        if changes.get(amount) is not None and not (changes.get(currency) or getattr(tender, currency)):
            changes[currency] = "IRR"
    changed = {}
    for key, value in changes.items():
        if getattr(tender, key) != value:
            changed[key] = {"old": getattr(tender, key), "new": value}
            setattr(tender, key, value)
    if changed:
        flush(db, "invalid_tender")
        events.record(db, "tender", tender.id, "update", jsonable({"changes": changed}), source, actor=actor)
        if "organizer_party_id" in changed or "stage" in changed:
            # reminders stop when the tender reaches result / closed, and follow the organizer
            tender_dates.resync_all(db, tender, source, actor, "tender stage or organizer changed")
    return tender


# ---- Setad: refresh, date banner, new addenda ------------------------------------------------------------------------

def _listing(db: Session, tender: Tender):
    if tender.listing_id is None:
        raise AppError("not_from_setad", "This tender did not come from Setad", status=422)
    return listings.get_listing(db, tender.listing_id)


def refresh_preview(db: Session, tender_id: uuid.UUID) -> list[dict]:
    """"Refresh from Setad": what differs between the tender and the listing now (nothing is applied)."""
    tender = get_tender(db, tender_id)
    values = setad_values(_listing(db, tender))
    out = []
    for key in ("tender_no", "tender_type", "stages", "document_price", "estimate"):
        if values[key] is not None and values[key] != getattr(tender, key):
            out.append({"field": key, "current": getattr(tender, key), "setad": values[key]})
    out += [{"field": f"date:{c['kind']}", "current": c["old"], "setad": c["new"]}
            for c in setad_date_changes(db, tender, since_seen=False)]
    bid = _bid_bond(db, tender)
    g = values["guarantee"]
    if g and (bid is None or bid.amount != g["amount"]):
        out.append({"field": "guarantee_amount", "current": bid.amount if bid else None, "setad": g["amount"]})
    return jsonable(out)


def refresh_apply(db: Session, tender_id: uuid.UUID, fields: list[str], source: str, actor: str | None = None) -> Tender:
    """Apply the confirmed fields of the diff (dates as changes with a reason, the bid bond amount on its draft)."""
    from app.modules.tenders import guarantees

    tender = get_tender(db, tender_id)
    values = setad_values(_listing(db, tender))
    diff = {d["field"] for d in refresh_preview(db, tender.id)}
    unknown = [f for f in fields if f not in diff]
    if unknown:
        raise AppError("nothing_to_apply", "These fields do not differ from Setad", {"fields": unknown}, status=422)
    plain = {f: values[f] for f in fields if not f.startswith("date:") and f != "guarantee_amount"}
    if "document_price" in plain:
        plain["document_price_currency"] = values["document_price_currency"]
    if "estimate" in plain:
        plain["estimate_currency"] = values["estimate_currency"]
    if plain:
        update_tender(db, tender.id, plain, source, actor)
    for f in fields:
        if f.startswith("date:"):
            apply_setad_date(db, tender.id, f.split(":", 1)[1], source, actor, reason=SETAD_REFRESH_REASON)
    if "guarantee_amount" in fields and values["guarantee"]:
        bid = _bid_bond(db, tender)
        if bid is None:
            guarantees.create_guarantee(db, {"case_id": tender.case_id, "tender_id": tender.id, "purpose": "bid",
                                             "amount": values["guarantee"]["amount"],
                                             "amount_currency": values["guarantee"]["currency"],
                                             "description": values["guarantee"]["description"],
                                             "beneficiary_party_id": tender.organizer_party_id}, source, actor)
        else:
            guarantees.update_guarantee(db, bid.id, {"amount": values["guarantee"]["amount"],
                                                     "amount_currency": values["guarantee"]["currency"]}, source, actor)
    events.record(db, "tender", tender.id, "setad_refresh", {"fields": fields}, source, actor=actor)
    return tender


def _seen_at(tender: Tender, kind: str) -> datetime | None:
    value = (tender.setad_dates_seen or {}).get(kind)
    return datetime.fromisoformat(value) if value else None


def setad_date_changes(db: Session, tender: Tender, since_seen: bool = True) -> list[dict]:
    """Tracked dates whose Setad value differs from the tender's.

    The banner ("Dates changed on Setad", ``since_seen``) lists only dates that Setad changed after the tender last
    saw them (at the prefill, an apply or a dismiss): a date the owner moved on purpose (an addendum, a manual change)
    is not offered back. "Refresh from Setad" (``since_seen=False``) lists every difference."""
    if tender.listing_id is None:
        return []
    try:
        listing = listings.get_listing(db, tender.listing_id)
    except Exception:
        return []
    out = []
    for field, kind in SETAD_DATES.items():
        new = getattr(listing, field)
        if new is None:
            continue
        if since_seen and _seen_at(tender, kind) == new:
            continue
        row = tender_dates.date_of_kind(db, tender.id, kind)
        if row is None or row.at != new:
            out.append({"kind": kind, "date_id": row.id if row else None, "old": row.at if row else None, "new": new})
    return out


def _mark_setad_dates_seen(db: Session, tender: Tender, values: dict[str, datetime]) -> None:
    seen = {**(tender.setad_dates_seen or {}), **{k: v.isoformat() for k, v in values.items()}}
    if seen != (tender.setad_dates_seen or {}):
        tender.setad_dates_seen = seen
        flush(db, "invalid_tender")


def apply_setad_date(db: Session, tender_id: uuid.UUID, kind: str, source: str, actor: str | None = None,
                     reason: str = SETAD_CHANGE_REASON):
    tender = get_tender(db, tender_id)
    change = next((c for c in setad_date_changes(db, tender, since_seen=False) if c["kind"] == kind), None)
    if change is None:
        raise Conflict("no_setad_change", "This date has not changed on Setad", {"kind": kind})
    _mark_setad_dates_seen(db, tender, {kind: change["new"]})
    if change["date_id"] is None:
        return tender_dates.add_date(db, tender.id, {"kind": kind, "at": change["new"], "source": "setad"}, source, actor)
    return tender_dates.change_date(db, change["date_id"], change["new"], reason, source, actor)


def dismiss_setad_dates(db: Session, tender_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """"Keep my dates": the Setad values shown in the banner count as seen; the tender's dates stay as they are."""
    tender = get_tender(db, tender_id)
    changes = setad_date_changes(db, tender)
    if changes:
        _mark_setad_dates_seen(db, tender, {c["kind"]: c["new"] for c in changes})
        events.record(db, "tender", tender.id, "setad_dates_kept", jsonable(changes), source, actor=actor)


def apply_all_setad_dates(db: Session, tender_id: uuid.UUID, source: str, actor: str | None = None) -> int:
    tender = get_tender(db, tender_id)
    changes = setad_date_changes(db, tender)
    for c in changes:
        apply_setad_date(db, tender.id, c["kind"], source, actor)
    return len(changes)


def new_appendices(db: Session, tender: Tender) -> dict[str, int]:
    """Setad addenda counters that grew since the owner last recorded an addendum («الحاقیهٔ جدید در ستاد»)."""
    if tender.listing_id is None:
        return {}
    try:
        listing = listings.get_listing(db, tender.listing_id)
    except Exception:
        return {}
    seen = tender.appendix_seen or {}
    return {f: getattr(listing, f) - int(seen.get(f) or 0) for f in APPENDIX_FIELDS
            if getattr(listing, f) is not None and getattr(listing, f) > int(seen.get(f) or 0)}


def acknowledge_appendices(db: Session, tender: Tender, source: str, actor: str | None) -> None:
    if tender.listing_id is None:
        return
    try:
        listing = listings.get_listing(db, tender.listing_id)
    except Exception:
        return
    current = {f: getattr(listing, f) for f in APPENDIX_FIELDS if getattr(listing, f) is not None}
    if current != (tender.appendix_seen or {}):
        tender.appendix_seen = current
        flush(db, "invalid_tender")
        events.record(db, "tender", tender.id, "appendix_seen", current, source, actor=actor)


# ---- stage hint -----------------------------------------------------------------------------------------------------

def _bid_bond(db: Session, tender: Tender) -> Guarantee | None:
    return db.scalar(select(Guarantee).where(Guarantee.tender_id == tender.id, Guarantee.purpose == "bid",
                                             Guarantee.status != "cancelled").order_by(Guarantee.created_at).limit(1))


def stage_hint(db: Session, tender: Tender) -> str:
    """The furthest sensible stage from the data (SetadSuite stage_hint), shown as a hint only."""
    from app.modules.tenders.models import TenderProposal

    if tender.result is not None:
        return "result"
    if tender.submitted_at is not None:
        return "submitted"
    items = list(db.scalars(select(EnvelopeItem.status).where(EnvelopeItem.tender_id == tender.id)))
    if items and all(s in ("ready", "submitted") for s in items):
        return "envelopes"
    bid = _bid_bond(db, tender)
    if bid is not None and bid.status not in ("to_request",):
        return "guarantee"
    if db.scalar(select(TenderProposal.id).where(TenderProposal.tender_id == tender.id).limit(1)) is not None:
        return "pricing"
    if tender.documents_obtained_at is not None:
        return "documents"
    return "screening"


def delete_snapshot(db: Session, tender: Tender) -> dict:
    return jsonable({c.name: getattr(tender, c.name) for c in Tender.__table__.columns})
