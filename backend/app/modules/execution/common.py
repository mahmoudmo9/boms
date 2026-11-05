"""Shared helpers of the execution module: lookups, today, money rounding, labels."""
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.modules.execution import models as m
from app.modules.parties import clock

ZERO = Decimal(0)
Q = Decimal("0.0001")


def today() -> date:
    return clock.today()


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Q, rounding=ROUND_HALF_UP)


def get(db: Session, model, row_id: uuid.UUID, what: str):
    row = db.get(model, row_id)
    if row is None:
        raise NotFound("not_found", f"{what} not found")
    return row


def get_sales_order(db: Session, order_id: uuid.UUID) -> m.SalesOrder:
    return get(db, m.SalesOrder, order_id, "Sales order")


def get_purchase_order(db: Session, order_id: uuid.UUID) -> m.PurchaseOrder:
    return get(db, m.PurchaseOrder, order_id, "Purchase order")


def reason_required(reason: str | None, code: str = "reason_required", message: str = "A reason is required") -> str:
    from app.core.errors import AppError

    text = (reason or "").strip()
    if not text:
        raise AppError(code, message, status=422)
    return text
