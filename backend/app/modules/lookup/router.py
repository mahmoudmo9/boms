"""Smart-field API (v0.9.0 section 8): lookup, suggestions with sources, validation and calculation in place."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.modules.lookup import calc, service, suggest, validators
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api", tags=["lookup"])


@router.get("/lookup")
def lookup(_: CurrentUser, db: Db, kind: str, q: str | None = None, function: str | None = None,
           country: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    if kind not in service.KINDS:
        raise AppError("unknown_lookup_kind", "Unknown lookup kind", {"kinds": list(service.KINDS)}, status=422)
    return service.lookup(db, kind, q, limit=limit, function=function, country=country)


@router.get("/suggest")
def suggest_values(_: CurrentUser, db: Db, context: Literal["party", "product", "case"], id: uuid.UUID,
                   role: Literal["buyer", "supplier"] = "buyer", party_id: uuid.UUID | None = None):
    if context == "party":
        return suggest.party(db, id, role)
    if context == "product":
        return suggest.product(db, id, party_id)
    return suggest.case(db, id)


@router.get("/validate")
def validate(_: CurrentUser, kind: str, value: Annotated[str, Query(max_length=200)], region: str | None = None):
    fn = validators.VALIDATORS.get(kind)
    if fn is None:
        raise AppError("unknown_validator", "Unknown validator", {"kinds": list(validators.VALIDATORS)}, status=422)
    return fn(value, region) if kind == "phone" else fn(value)


@router.get("/calc/words")
def words(_: CurrentUser, amount: Decimal, currency: Annotated[str, Query(pattern=r"^[A-Z]{3}$")],
          lang: Literal["fa", "en"] = "fa"):
    return {"words": calc.amount_in_words(amount, currency, lang)}


@router.get("/calc/line")
def line(_: CurrentUser, quantity: Decimal, unit_price: Decimal, discount: Decimal = Decimal(0),
         vat_rate: Decimal = Decimal(0)):
    return calc.line(quantity, unit_price, discount, vat_rate)


@router.get("/calc/margin")
def margin(_: CurrentUser, price: Decimal, cost: Decimal):
    return calc.margin_markup(price, cost)


@router.get("/calc/convert")
def convert(_: CurrentUser, db: Db, case_id: uuid.UUID, amount: Decimal,
            from_currency: Annotated[str, Query(alias="from", pattern=r"^[A-Z]{3}$")],
            to_currency: Annotated[str, Query(alias="to", pattern=r"^[A-Z]{3}$")]):
    return calc.convert(db, case_id, amount, from_currency, to_currency)


@router.get("/calc/time-left")
def time_left(_: CurrentUser, deadline: datetime):
    return calc.time_left(deadline)


ROUTERS = [router]
