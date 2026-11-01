"""Shared helpers of the tenders module: lookups, Tehran days, currency codes from Setad text, labels."""
import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.parties import clock
from app.modules.tenders.models import Tender

TEHRAN = ZoneInfo("Asia/Tehran")

STAGES = ("screening", "documents", "pricing", "guarantee", "envelopes", "submitted", "opening", "result", "closed")
DATE_LABELS = {
    "documents_deadline": ("مهلت دریافت اسناد", "Documents deadline"),
    "briefing": ("جلسهٔ توجیهی", "Briefing"),
    "site_visit": ("بازدید از محل", "Site visit"),
    "questions_deadline": ("مهلت پرسش", "Questions deadline"),
    "proposal_deadline": ("مهلت ارسال پیشنهاد", "Proposal deadline"),
    "opening": ("بازگشایی پاکت‌ها", "Opening"),
    "quality_docs_deadline": ("مهلت ارزیابی کیفی", "Quality evaluation deadline"),
    "offer_valid_until": ("پایان اعتبار پیشنهاد", "Offer valid until"),
}
# Setad listing date field -> tender date kind (prefill, "Refresh from Setad" and the date-change banner)
SETAD_DATES = {"documents_deadline": "documents_deadline", "proposal_deadline": "proposal_deadline",
               "opening_at": "opening", "inquiry_deadline": "quality_docs_deadline"}
# Setad's tender type codes -> stages
SETAD_STAGES = {"ONE_STAGE_TENDER": "one_stage", "TWO_STAGE_TENDER": "two_stage",
                "QUALITY_EVALUATION_TENDER": "quality_evaluation", "SHORT_LIST_QUALITY_EVALUATION": "quality_evaluation"}


def get_tender(db: Session, tender_id: uuid.UUID) -> Tender:
    row = db.get(Tender, tender_id)
    if row is None:
        raise NotFound("not_found", "Tender not found")
    return row


def tender_of_case(db: Session, case_id: uuid.UUID) -> Tender | None:
    return db.scalar(select(Tender).where(Tender.case_id == case_id))


def require_open(tender: Tender) -> None:
    if tender.stage == "closed":
        raise Conflict("tender_closed", "The tender is closed", {"stage": tender.stage})


def today() -> date:
    return clock.today()


def tehran_day(value: datetime) -> date:
    return value.astimezone(TEHRAN).date()


def at_of(day: date, all_day: bool = True) -> datetime:
    """A date entered without a time: end of the day in Tehran (a deadline)."""
    return datetime.combine(day, time(23, 59) if all_day else time(0, 0), TEHRAN)


def currency_code(text: str | None, default: str = "IRR") -> str:
    """Setad writes the currency as text («ریال», "IRR"); BOMS stores ISO codes."""
    t = (text or "").strip()
    if not t or t in ("ریال", "ريال", "rial", "Rial", "RIAL"):
        return default
    if len(t) == 3 and t.isalpha() and t.upper() == t:
        return t
    return default


def date_label(kind: str, label: str | None, language: str = "fa") -> str:
    if kind == "other":
        return label or ("سایر" if language == "fa" else "Other")
    fa, en = DATE_LABELS[kind]
    return fa if language == "fa" else en


def reason_required(reason: str | None, code: str = "reason_required") -> str:
    reason = (reason or "").strip()
    if not reason:
        raise AppError(code, "A reason is required", status=422)
    return reason
