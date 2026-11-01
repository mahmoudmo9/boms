"""Guarantees of every kind (bid bond, performance, advance payment, retention, other) with their history.

Status flow (SetadSuite statuses plus extended / claimed / cancelled): to_request -> requested -> issued ->
ready_to_upload -> submitted -> (extended) -> released; claimed and cancelled end it. Every change writes a
``guarantee_event``. Reminders (follow-ups on the reminder party: the bank or beneficiary chosen by the owner,
the organizer by default) 30 and 7 days before ``valid_until`` while the guarantee is not released. A guarantee that
is issued or later is never deleted (cancel it instead).
"""
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.parties import service as parties
from app.modules.sourcing import inquiries as sourcing
from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.system import settings
from app.modules.tenders import reminders
from app.modules.tenders.common import tehran_day, today
from app.modules.tenders.models import Guarantee, GuaranteeEvent, Tender

STATUSES = ("to_request", "requested", "issued", "ready_to_upload", "submitted", "extended", "released", "claimed",
            "cancelled")
CLOSED = ("released", "claimed", "cancelled")
ISSUED_OR_LATER = ("issued", "ready_to_upload", "submitted", "extended")
DELETABLE = ("to_request", "requested")
EVENT_KIND = {"requested": "requested", "issued": "issued", "extended": "extended", "released": "released",
              "claimed": "claimed", "cancelled": "cancelled"}
FIELDS = ("purpose", "form", "beneficiary_party_id", "reminder_party_id", "amount", "amount_currency", "bank_name",
          "branch", "number", "issued_on", "valid_until", "claim_period_until", "fee", "fee_currency", "blocked_deposit",
          "blocked_deposit_currency", "document_id", "description", "note")
PURPOSE_FA = {"bid": "تضمین شرکت در مناقصه", "performance": "تضمین انجام تعهدات", "advance_payment": "تضمین پیش‌پرداخت",
              "retention": "تضمین حسن انجام کار", "other": "تضمین"}
EXPIRY_PURPOSE = "guarantee_expiry"
RELEASE_PURPOSE = "guarantee_release"


def get_guarantee(db: Session, guarantee_id: uuid.UUID) -> Guarantee:
    row = db.get(Guarantee, guarantee_id)
    if row is None:
        raise NotFound("not_found", "Guarantee not found")
    return row


def history(db: Session, guarantee_id: uuid.UUID) -> list[GuaranteeEvent]:
    return list(db.scalars(select(GuaranteeEvent).where(GuaranteeEvent.guarantee_id == guarantee_id)
                           .order_by(GuaranteeEvent.created_at)))


def guarantees_of(db: Session, *, case_id: uuid.UUID | None = None, tender_id: uuid.UUID | None = None) -> list[Guarantee]:
    query = select(Guarantee)
    if case_id:
        query = query.where(Guarantee.case_id == case_id)
    if tender_id:
        query = query.where(Guarantee.tender_id == tender_id)
    return list(db.scalars(query.order_by(Guarantee.created_at)))


def _tender(db: Session, row: Guarantee) -> Tender | None:
    return db.get(Tender, row.tender_id) if row.tender_id else None


def reminder_party(db: Session, row: Guarantee) -> uuid.UUID | None:
    if row.reminder_party_id or row.beneficiary_party_id:
        return row.reminder_party_id or row.beneficiary_party_id
    tender = _tender(db, row)
    if tender and tender.organizer_party_id:
        return tender.organizer_party_id
    return sourcing.get_case(db, row.case_id).party_id


def _label(db: Session, row: Guarantee) -> str:
    tender = _tender(db, row)
    return f"{PURPOSE_FA.get(row.purpose, 'تضمین')} {row.number or ''} {tender.tender_no if tender and tender.tender_no else ''}".split()


def sync_expiry_reminders(db: Session, row: Guarantee, source: str, actor: str | None) -> dict:
    offsets = settings.get(db, "tenders.guarantee_reminder_days")
    active = row.status not in CLOSED and row.valid_until is not None
    action = "پایان اعتبار " + " ".join(_label(db, row))
    return reminders.sync(db, tender_id=row.tender_id, purpose=EXPIRY_PURPOSE, ref_id=row.id,
                          party_id=reminder_party(db, row) if active else None, action=action,
                          target=row.valid_until if active else None, offsets=offsets,
                          note="guarantee validity changed", source=source, actor=actor)


def schedule_release(db: Session, row: Guarantee, days: int | None, source: str, actor: str | None) -> uuid.UUID | None:
    """The follow-up «پیگیری آزادسازی تضمین» (once; none for a closed guarantee)."""
    if row.status in CLOSED:
        return None
    if reminders.links(db, purpose=RELEASE_PURPOSE, ref_id=row.id):
        return None
    party = reminder_party(db, row)
    if party is None:
        return None
    if days is None:
        days = settings.get(db, "tenders.release_followup_days")
    followup = reminders.create(db, tender_id=row.tender_id, purpose=RELEASE_PURPOSE, ref_id=row.id, party_id=party,
                                action="پیگیری آزادسازی تضمین " + " ".join(_label(db, row)),
                                due_on=today() + timedelta(days=days), days_before=None, source=source, actor=actor)
    return followup.id


def _check_refs(db: Session, data: dict) -> None:
    for key in ("beneficiary_party_id", "reminder_party_id"):
        if data.get(key):
            parties.get_party(db, data[key])
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    for amount in ("amount", "fee", "blocked_deposit"):
        if data.get(amount) is not None and not data.get(f"{amount}_currency"):
            data[f"{amount}_currency"] = "IRR"


def create_guarantee(db: Session, data: dict, source: str, actor: str | None = None) -> Guarantee:
    from app.modules.tenders import envelopes

    sourcing.get_case(db, data["case_id"])
    if data.get("tender_id"):
        tender = db.get(Tender, data["tender_id"])
        if tender is None or tender.case_id != data["case_id"]:
            raise AppError("tender_not_of_case", "The tender belongs to another case", status=422)
    _check_refs(db, data)
    row = Guarantee(case_id=data["case_id"], tender_id=data.get("tender_id"), status=data.get("status") or "to_request",
                    **{k: data.get(k) for k in FIELDS if data.get(k) is not None})
    db.add(row)
    flush(db, "invalid_guarantee")
    db.add(GuaranteeEvent(guarantee_id=row.id, kind="status", on_date=today(), new_status=row.status,
                          reason="created", valid_until=row.valid_until))
    db.flush()
    events.record(db, "guarantee", row.id, "create", jsonable(row_snapshot(row)), source, actor=actor)
    envelopes.follow_guarantee(db, row, source, actor)
    sync_expiry_reminders(db, row, source, actor)
    return row


def update_guarantee(db: Session, guarantee_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Guarantee:
    row = get_guarantee(db, guarantee_id)
    changes = {k: v for k, v in changes.items() if k in FIELDS}
    for amount in ("amount", "fee", "blocked_deposit"):
        if changes.get(amount) is not None and not (changes.get(f"{amount}_currency") or getattr(row, f"{amount}_currency")):
            changes[f"{amount}_currency"] = "IRR"
    _check_refs(db, {**changes})
    changed = {}
    for key, value in changes.items():
        if getattr(row, key) != value:
            changed[key] = {"old": getattr(row, key), "new": value}
            setattr(row, key, value)
    if changed:
        flush(db, "invalid_guarantee")
        events.record(db, "guarantee", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
        if set(changed) & {"valid_until", "reminder_party_id", "beneficiary_party_id"}:
            sync_expiry_reminders(db, row, source, actor)
    return row


def set_status(db: Session, guarantee_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> Guarantee:
    """A step of the flow with its date (and the new validity for an extension, the reason for a claim or a
    cancellation, a document per step when relevant)."""
    from app.modules.tenders import envelopes

    row = get_guarantee(db, guarantee_id)
    status = data["status"]
    if status not in STATUSES:
        raise AppError("invalid_status", "Unknown guarantee status", status=422)
    if row.status in CLOSED:
        raise Conflict("guarantee_closed", "The guarantee is already closed", {"status": row.status})
    if status == row.status and status != "extended":
        return row
    on_date = data.get("on_date") or today()
    if status == "extended":
        if not data.get("valid_until"):
            raise AppError("valid_until_required", "An extension needs the new validity date", status=422)
        if row.valid_until and data["valid_until"] <= row.valid_until:
            raise AppError("extension_not_later", "The new validity must be later than the current one", status=422)
    if status in ("claimed", "cancelled") and not (data.get("reason") or "").strip():
        raise AppError("reason_required", "A reason is required", status=422)
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    old = row.status
    row.status = status
    if status == "issued" and not row.issued_on:
        row.issued_on = on_date
    if data.get("valid_until"):
        row.valid_until = data["valid_until"]
    if data.get("document_id") and status in ("issued", "ready_to_upload"):
        row.document_id = row.document_id or data["document_id"]
    flush(db, "invalid_guarantee")
    db.add(GuaranteeEvent(guarantee_id=row.id, kind=EVENT_KIND.get(status, "status"), on_date=on_date, old_status=old,
                          new_status=status, valid_until=data.get("valid_until"), reason=(data.get("reason") or None),
                          document_id=data.get("document_id")))
    db.flush()
    events.record(db, "guarantee", row.id, "status", jsonable({"old_status": old, "new_status": status, "on_date": on_date,
                                                               "valid_until": data.get("valid_until"),
                                                               "reason": data.get("reason")}), source, actor=actor)
    if status in CLOSED:
        reminders.cancel(db, f"guarantee {status}", source, actor, purposes=(EXPIRY_PURPOSE, RELEASE_PURPOSE), ref_id=row.id)
    else:
        sync_expiry_reminders(db, row, source, actor)
    envelopes.follow_guarantee(db, row, source, actor)
    if status == "submitted" and row.purpose == "performance" and row.tender_id:
        from app.modules.tenders import results

        results.on_performance_submitted(db, row, source, actor)
    return row


def delete_guarantee(db: Session, guarantee_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_guarantee(db, guarantee_id)
    if row.status not in DELETABLE:
        raise Conflict("guarantee_issued", "An issued guarantee cannot be deleted; cancel it instead",
                       {"status": row.status})
    _delete(db, row, source, actor, note="guarantee deleted")


def _delete(db: Session, row: Guarantee, source: str, actor: str | None, note: str) -> dict:
    from app.modules.tenders.models import EnvelopeItem

    reminders.cancel(db, note, source, actor, purposes=(EXPIRY_PURPOSE, RELEASE_PURPOSE), ref_id=row.id)
    for item in db.scalars(select(EnvelopeItem).where(EnvelopeItem.guarantee_id == row.id)):
        item.guarantee_id = None
    snapshot = {**row_snapshot(row), "history": [row_snapshot(e) for e in history(db, row.id)]}
    for e in history(db, row.id):
        db.delete(e)
    db.flush()
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "guarantee", row.id, "delete", jsonable({"deleted": snapshot}), source, actor=actor)
    return snapshot


# ---- rules -----------------------------------------------------------------------------------------------------------

def needed_until(db: Session, tender: Tender) -> date | None:
    """A guarantee must cover the proposal deadline plus the proposal validity, when both are known."""
    from app.modules.tenders import dates as tender_dates

    if tender.proposal_valid_until:
        return tender.proposal_valid_until
    deadline = tender_dates.date_of_kind(db, tender.id, "proposal_deadline")
    if deadline is None or not tender.proposal_validity_days:
        return None
    return tehran_day(deadline.at) + timedelta(days=tender.proposal_validity_days)


def coverage_problem(db: Session, tender: Tender, row: Guarantee | None) -> dict | None:
    need = needed_until(db, tender)
    if row is None or need is None or row.valid_until is None or row.valid_until >= need:
        return None
    return {"code": "guarantee_validity_short", "valid_until": row.valid_until.isoformat(), "needed_until": need.isoformat(),
            "message": "اعتبار تضمین قبل از پایان اعتبار پیشنهاد تمام می‌شود"}


def tied_up(db: Session, case_id: uuid.UUID) -> dict[str, dict[str, str]]:
    """Cash tied up by the case's open guarantees (blocked deposits and fees), per currency. Shown next to the
    computed exposure; the cost-sheet formula is not changed."""
    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"blocked_deposit": Decimal(0), "fee": Decimal(0)})
    for row in guarantees_of(db, case_id=case_id):
        if row.status in ("released", "cancelled"):
            continue
        if row.blocked_deposit is not None:
            out[row.blocked_deposit_currency]["blocked_deposit"] += row.blocked_deposit
        if row.fee is not None:
            out[row.fee_currency]["fee"] += row.fee
    return {cur: {k: str(v) for k, v in vals.items()} | {"total": str(vals["blocked_deposit"] + vals["fee"])}
            for cur, vals in out.items()}


def list_all(db: Session, *, status: str | None = None, purpose: str | None = None,
             expiring_within: int | None = None) -> list[dict]:
    """Every guarantee across cases (the Guarantees list page)."""
    from app.modules.sourcing.models import Case

    query = select(Guarantee, Case.title, Tender.tender_no).join(Case, Case.id == Guarantee.case_id) \
        .outerjoin(Tender, Tender.id == Guarantee.tender_id)
    if status:
        query = query.where(Guarantee.status == status)
    if purpose:
        query = query.where(Guarantee.purpose == purpose)
    if expiring_within is not None:
        query = query.where(Guarantee.valid_until.is_not(None), Guarantee.valid_until <= today() + timedelta(days=expiring_within),
                            Guarantee.status.not_in(CLOSED))
    rows = db.execute(query.order_by(Guarantee.valid_until.asc().nulls_last(), Guarantee.created_at)).all()
    names = {}
    out = []
    for g, case_title, tender_no in rows:
        if g.beneficiary_party_id and g.beneficiary_party_id not in names:
            p = parties.get_party(db, g.beneficiary_party_id)
            names[g.beneficiary_party_id] = p.name_fa or p.name_en
        out.append(jsonable({**row_snapshot(g), "case_title": case_title, "tender_no": tender_no,
                             "beneficiary_name": names.get(g.beneficiary_party_id)}))
    return out
