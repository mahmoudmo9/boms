"""Shared helpers of the finance module: lookups, today, rounding by the currency's decimals, the base currency."""
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.parties import clock

ZERO = Decimal(0)
Q4 = Decimal("0.0001")


def today() -> date:
    return clock.today()


def money(value) -> Decimal:
    return Decimal(value).quantize(Q4, rounding=ROUND_HALF_UP)


def decimals(db: Session, currency: str) -> int:
    from app.modules.costing import service as costing

    return costing.currency_decimals(db, currency)


def round_to(db: Session, value, currency: str) -> Decimal:
    """Round by the currency's decimals (IRR 0), kept at 4 places in the database."""
    exp = Decimal(1).scaleb(-decimals(db, currency))
    return money(Decimal(value).quantize(exp, rounding=ROUND_HALF_UP))


def base_currency(db: Session) -> str:
    from app.modules.system import settings

    return settings.get(db, "finance.base_currency") or "IRR"


def get(db: Session, model, row_id: uuid.UUID, what: str):
    row = db.get(model, row_id)
    if row is None:
        raise NotFound("not_found", f"{what} not found")
    return row


def reason_required(reason: str | None, code: str = "reason_required", message: str = "A reason is required") -> str:
    from app.core.errors import AppError

    text = (reason or "").strip()
    if not text:
        raise AppError(code, message, status=422)
    return text
