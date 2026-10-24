"""Base data: countries, currencies, units. Search, add, edit, (de)activate; no delete."""

from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import Conflict, NotFound
from app.core.schemas import ApiModel, Page, page_params
from app.core.text import normalize_fa
from app.core.web import request_source
from app.modules.events import service as events
from app.modules.system.auth import CurrentUser
from app.modules.system.models import Country, Currency, Unit

router = APIRouter(prefix="/api/basedata", tags=["basedata"])

Name = Annotated[str, Field(min_length=1, max_length=200)]
UnitKind = Literal["count", "weight", "length", "area", "volume", "time", "other"]


# ---- schemas ---------------------------------------------------------------

class CountryOut(ApiModel):
    iso2: str
    iso3: str
    name_fa: str
    name_en: str
    active: bool
    sort_order: int


class CountryIn(BaseModel):
    iso2: str = Field(pattern=r"^[A-Za-z]{2}$")
    iso3: str = Field(pattern=r"^[A-Za-z]{3}$")
    name_fa: Name
    name_en: Name
    active: bool = True
    sort_order: int = Field(default=100, ge=0, le=100000)

    @field_validator("iso2", "iso3")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class CountryPatch(BaseModel):
    iso3: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    name_fa: Name | None = None
    name_en: Name | None = None
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100000)

    @field_validator("iso3")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class CurrencyOut(ApiModel):
    code: str
    name_fa: str
    name_en: str
    symbol: str | None
    minor_units: int | None
    active: bool


class CurrencyIn(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z]{3}$")
    name_fa: Name
    name_en: Name
    symbol: str | None = Field(default=None, max_length=10)
    minor_units: int | None = Field(default=2, ge=0, le=6)
    active: bool = True

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()


class CurrencyPatch(BaseModel):
    name_fa: Name | None = None
    name_en: Name | None = None
    symbol: str | None = Field(default=None, max_length=10)
    minor_units: int | None = Field(default=None, ge=0, le=6)
    active: bool | None = None


class UnitOut(ApiModel):
    code: str
    name_fa: str
    name_en: str
    kind: str
    base_factor: Decimal
    active: bool


class UnitIn(BaseModel):
    code: str = Field(pattern=r"^[a-z0-9_]{1,16}$")
    name_fa: Name
    name_en: Name
    kind: UnitKind
    base_factor: Decimal = Field(gt=0, max_digits=30, decimal_places=12)
    active: bool = True


class UnitPatch(BaseModel):
    name_fa: Name | None = None
    name_en: Name | None = None
    kind: UnitKind | None = None
    base_factor: Decimal | None = Field(default=None, gt=0, max_digits=30, decimal_places=12)
    active: bool | None = None


# kind -> (model, primary key attribute, search columns, default order, entity type)
KINDS = {
    "countries": (Country, "iso2", ("iso2", "iso3", "name_fa", "name_en"), ("sort_order", "name_en"), "country"),
    "currencies": (Currency, "code", ("code", "name_fa", "name_en"), ("code",), "currency"),
    "units": (Unit, "code", ("code", "name_fa", "name_en"), ("kind", "code"), "unit"),
}


# ---- service -----------------------------------------------------------------

def list_items(db: Session, kind: str, q: str | None, active: bool | None, page: int, page_size: int):
    model, _, search_cols, order, _ = KINDS[kind]
    query = select(model)
    if active is not None:
        query = query.where(model.active == active)
    needle = normalize_fa(q or "")
    if needle:
        pattern = f"%{needle.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')}%"
        query = query.where(or_(*(func.core.normalize_fa(getattr(model, c)).like(pattern) for c in search_cols)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(*(getattr(model, c) for c in order)).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return list(rows), total


def get_item(db: Session, kind: str, key: str):
    model = KINDS[kind][0]
    item = db.get(model, key)
    if item is None:
        raise NotFound("not_found", f"{KINDS[kind][4]} {key} not found")
    return item


def create_item(db: Session, kind: str, data: dict, source: str, actor: str | None = None):
    model, pk, _, _, entity = KINDS[kind]
    if db.get(model, data[pk]) is not None:
        raise Conflict("duplicate_code", f"{entity} {data[pk]} already exists", {"code": data[pk]})
    if kind == "countries" and db.scalar(select(Country).where(Country.iso3 == data["iso3"])) is not None:
        raise Conflict("duplicate_code", f"iso3 {data['iso3']} already exists", {"code": data["iso3"]})
    item = model(**data)
    db.add(item)
    db.flush()
    events.record(db, entity, data[pk], "create", {"values": _jsonable(data)}, source, actor=actor)
    return item


def update_item(db: Session, kind: str, key: str, changes: dict, source: str, actor: str | None = None):
    model, _, _, _, entity = KINDS[kind]
    item = get_item(db, kind, key)
    if kind == "countries" and changes.get("iso3") and changes["iso3"] != item.iso3:
        if db.scalar(select(Country).where(Country.iso3 == changes["iso3"])) is not None:
            raise Conflict("duplicate_code", f"iso3 {changes['iso3']} already exists", {"code": changes["iso3"]})
    diff = {}
    for field, value in changes.items():
        if getattr(item, field) != value:
            diff[field] = {"old": getattr(item, field), "new": value}
            setattr(item, field, value)
    if diff:
        db.flush()
        if set(diff) == {"active"}:
            action = "activate" if item.active else "deactivate"
        else:
            action = "update"
        events.record(db, entity, key, action, {"changes": _jsonable(diff)}, source, actor=actor)
    return item


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, Decimal):
        return str(value)
    return value


# ---- routes ------------------------------------------------------------------

Db = Annotated[Session, Depends(get_db)]
Kind = Literal["countries", "currencies", "units"]
OUT = {"countries": CountryOut, "currencies": CurrencyOut, "units": UnitOut}
IN = {"countries": CountryIn, "currencies": CurrencyIn, "units": UnitIn}
PATCH = {"countries": CountryPatch, "currencies": CurrencyPatch, "units": UnitPatch}


@router.get("/{kind}")
def list_route(kind: Kind, _: CurrentUser, db: Db, q: str | None = None, active: bool | None = None,
               page: int = 1, page_size: Annotated[int, Query(le=500)] = 50):
    page, page_size = page_params(page, page_size)
    rows, total = list_items(db, kind, q, active, page, page_size)
    out = OUT[kind]
    return Page(items=[out.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.post("/{kind}", status_code=201)
def create_route(kind: Kind, body: dict, request: Request, user: CurrentUser, db: Db):
    data = IN[kind].model_validate(body).model_dump()
    item = create_item(db, kind, data, request_source(request), actor=user.username)
    db.commit()
    return OUT[kind].model_validate(item)


@router.patch("/{kind}/{key}")
def update_route(kind: Kind, key: str, body: dict, request: Request, user: CurrentUser, db: Db):
    changes = PATCH[kind].model_validate(body).model_dump(exclude_unset=True)
    changes = {k: v for k, v in changes.items() if v is not None or k == "symbol"}
    item = update_item(db, kind, key, changes, request_source(request), actor=user.username)
    db.commit()
    return OUT[kind].model_validate(item)
