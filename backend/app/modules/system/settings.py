"""Application settings stored in ``sys.setting`` (key -> jsonb value)."""

import re
import sys
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import VERSION, get_config
from app.core.db import get_db
from app.core.schemas import InputModel
from app.core.errors import AppError
from app.core.secrets import get_secret, set_secret
from app.core.web import request_source
from app.modules.events import service as events
from app.modules.system.auth import CurrentUser
from app.modules.system.models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _time(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("expected HH:MM")
    return value


def _optional_path(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("expected a folder path")
    return value.strip()


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected true/false")
    return value


def _int_range(low: int, high: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"expected an integer {low}..{high}")
        return value

    return check


def _day_offsets(value: Any) -> list[int]:
    """Days before a date, e.g. [3, 1] (v0.6.0 tender reminders): distinct integers 0..365, largest first."""
    if not isinstance(value, list) or len(value) > 10 or any(
            isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 365 for v in value):
        raise ValueError("expected a list of whole days 0..365 (at most 10)")
    return sorted(set(value), reverse=True)


def _percent(value: Any) -> float:
    """A percentage 0..100 (v0.7.0 PO price tolerance), whole or decimal."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        raise ValueError("expected a percentage 0..100")
    return value


def _short_text(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError("expected text (up to 300 characters)")
    return value.strip()


def _signature(value: Any) -> dict[str, str]:
    """Multi-line signature per language code, e.g. {"fa": "...", "en": "..."}."""
    if not isinstance(value, dict) or len(value) > 10:
        raise ValueError("expected {language: text}")
    clean = {}
    for lang, text in value.items():
        if not isinstance(lang, str) or not re.fullmatch(r"[a-z]{2,3}", lang):
            raise ValueError("language codes are 2-3 lowercase letters")
        if not isinstance(text, str) or len(text) > 2000:
            raise ValueError("expected text (up to 2000 characters)")
        clean[lang] = text.rstrip()
    return clean


def _choice(*options: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if value not in options:
            raise ValueError(f"expected one of {', '.join(options)}")
        return value

    return check


def _optional_uuid(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
        raise ValueError("expected a document id")
    return value.lower()


def _vat_decision(value: Any) -> dict | None:
    """v0.9.0: the owner's VAT decision for domestic invoices: unset, {"mode": "apply"} or {"mode": "zero", "reason"}."""
    if value is None or value == "":
        return None
    if not isinstance(value, dict) or value.get("mode") not in ("apply", "zero"):
        raise ValueError('expected {"mode": "apply"} or {"mode": "zero", "reason": "..."}')
    if value["mode"] == "zero":
        reason = value.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 300:
            raise ValueError("a zero rate needs a reason (up to 300 characters)")
        return {"mode": "zero", "reason": reason.strip()}
    return {"mode": "apply"}


def _text_list(value: Any) -> list[str]:
    """A list of short texts (warn keywords, dismiss reasons, checklist questions); empty entries are dropped."""
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError("expected a list of texts")
    out = []
    for item in value:
        if not isinstance(item, str) or len(item) > 300:
            raise ValueError("expected a list of texts")
        if item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


# Setad screening defaults from SetadSuite v0.9.23 (inquiries/pipeline.py DEFAULT_SETTINGS)
SETAD_DISMISS_REASONS = ["خارج از حوزه کاری", "مهلت کافی نیست", "الزامات خریدار قابل تأمین نیست", "تأمین‌کننده پیدا نشد",
                         "قیمت تأمین‌کننده بالا است", "شرایط پرداخت نامناسب", "سایر"]
SETAD_CHECKLIST = ["کالا/خدمت در حوزه کاری ما است", "شرایط و الزامات خریدار قابل تأمین است",
                   "محل تحویل و هزینه ارسال قابل قبول است", "شرایط پرداخت قابل قبول است",
                   "مهلت برای گرفتن قیمت از تأمین‌کننده کافی است"]

# key -> (default, validator)
DEFINITIONS: dict[str, tuple[Any, Callable[[Any], Any]]] = {
    "backup.time": ("02:00", _time),
    "backup.secondary_path": (None, _optional_path),
    "backup.archive_enabled": (False, _bool),
    "backup.archive_path": (None, _optional_path),
    "upload.max_mb": (100, _int_range(1, 2048)),
    "parties.stale_lead_days": (14, _int_range(1, 365)),
    "company.name": ("", _short_text),
    "company.signature": ({"fa": "", "en": ""}, _signature),
    "costing.fx_max_age_days": (3, _int_range(0, 365)),
    "costing.default_pricing_method": ("margin", _choice("margin", "markup")),
    "quotes.default_validity_days": (7, _int_range(1, 365)),
    # letterhead of quotes / proforma invoices (v0.4.0); {fa, en} values are multi-line texts per language
    "company.name_fa": ("", _short_text),
    "company.name_en": ("", _short_text),
    "company.address": ({"fa": "", "en": ""}, _signature),
    "company.phone": ("", _short_text),
    "company.email": ("", _short_text),
    "company.website": ("", _short_text),
    "company.registration": ({"fa": "", "en": ""}, _signature),
    "company.logo_document_id": (None, _optional_uuid),
    "company.footer": ({"fa": "", "en": ""}, _signature),
    "company.bank_details": ({"fa": "", "en": ""}, _signature),
    "pdf.browser_path": (None, _optional_path),
    # Setad connector and screening (v0.5.0)
    "setad.files_dir": (None, _optional_path),          # None = <data folder>/setad-files (not backed up)
    "setad.agent_idle_minutes": (60, _int_range(5, 1440)),
    "setad.retention_days": (180, _int_range(30, 3650)),
    "setad.warn_keywords": ([], _text_list),
    "setad.dismiss_reasons": (SETAD_DISMISS_REASONS, _text_list),
    "setad.checklist": (SETAD_CHECKLIST, _text_list),
    # Setad proforma letterhead (v0.5.0)
    "company.national_id": ("", _short_text),
    "company.economic_code": ("", _short_text),
    "company.signer_name": ({"fa": "", "en": ""}, _signature),
    "company.signer_title": ({"fa": "", "en": ""}, _signature),
    # Tender workflow (v0.6.0)
    "tenders.reminder_days": ([3, 1], _day_offsets),             # reminders before each tender date
    "tenders.guarantee_reminder_days": ([30, 7], _day_offsets),  # before a guarantee's valid_until
    "tenders.release_followup_days": (7, _int_range(0, 365)),    # bid bond release follow-up after the result
    # Execution and shipping (v0.7.0)
    "execution.po_price_tolerance_percent": (0, _percent),       # PO price above the cost sheet's purchase price
    "execution.po_confirm_days": (3, _int_range(0, 90)),         # «پیگیری تأیید سفارش» after a PO is sent
    "execution.ready_followup_days_before": (2, _int_range(0, 90)),  # «پیگیری آماده شدن» before the ready date
    "execution.step_reminder_days": ([3, 1], _day_offsets),      # reminders before a process step's due date
    "execution.delay_warning_days": (3, _int_range(0, 365)),     # ETA later than the first ETA by more than this
    "execution.claim_followup_days": (7, _int_range(1, 90)),     # «پیگیری ادعا» while a claim is open
    "execution.invoice_followup_days": (3, _int_range(0, 90)),   # «صدور فاکتور و پیگیری تسویه» after delivery
    "execution.warranty_remind_days": (30, _int_range(0, 365)),  # a task this many days before the warranty end
    # Deal finance (v0.8.0)
    "finance.base_currency": ("IRR", _short_text),                # rial amounts of payments and costs
    "finance.payment_days": (30, _int_range(0, 365)),             # invoice due date after the issue date
    "finance.supplier_payment_days": (30, _int_range(0, 365)),    # supplier invoice due date when not typed
    "finance.vat_default_domestic": (None, _vat_decision),        # v0.9.0: decided on the first domestic invoice
}


def get_all(db: Session) -> dict[str, Any]:
    values = {key: default for key, (default, _) in DEFINITIONS.items()}
    for row in db.scalars(select(Setting).where(Setting.key.in_(DEFINITIONS))):
        values[row.key] = row.value
    return values


def get(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else DEFINITIONS[key][0]


def update(db: Session, changes: dict[str, Any], source: str, actor: str | None = None) -> dict[str, Any]:
    errors = {}
    clean = {}
    for key, value in changes.items():
        if key not in DEFINITIONS:
            errors[key] = "unknown setting"
            continue
        try:
            clean[key] = DEFINITIONS[key][1](value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise AppError("invalid_settings", "Invalid settings", {"fields": errors}, status=422)

    for key, value in clean.items():
        row = db.get(Setting, key)
        old = row.value if row is not None else DEFINITIONS[key][0]
        if old == value:
            continue
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
        db.flush()
        events.record(db, "setting", key, "update", {"old": old, "new": value}, source, actor=actor)
    return get_all(db)


def get_internal(db: Session, key: str) -> Any:
    """Internal state (e.g. scheduler bookkeeping) that is not a user setting."""
    row = db.get(Setting, key)
    return row.value if row is not None else None


def set_internal(db: Session, key: str, value: Any) -> None:
    if key in DEFINITIONS:
        raise ValueError(f"{key} is a user setting; use update()")
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value
    db.flush()


def _response(db: Session) -> dict[str, Any]:
    return {
        "values": get_all(db),
        "data_dir": str(get_config().data_dir),
        "version": VERSION,
        "archive_password_set": bool(get_secret("archive_password", required=False)),
        "can_store_secrets": sys.platform == "win32",
    }


@router.get("")
def read_settings(_: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return _response(db)


@router.patch("")
def patch_settings(body: dict[str, Any], request: Request, user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    update(db, body, request_source(request), actor=user.username)
    db.commit()
    return _response(db)


class ArchivePasswordIn(InputModel):
    password: str = Field(min_length=12, max_length=256)


@router.post("/archive-password", status_code=204)
def set_archive_password(body: ArchivePasswordIn, request: Request, user: CurrentUser,
                         db: Annotated[Session, Depends(get_db)]):
    """Store the encrypted-archive password in Windows Credential Manager."""
    if sys.platform != "win32":
        raise AppError("not_supported", "Credential Manager is only available on Windows; "
                       "set BOMS_ARCHIVE_PASSWORD instead", status=400)
    set_secret("archive_password", body.password)
    events.record(db, "setting", "archive_password", "update", {}, request_source(request), actor=user.username)
    db.commit()
