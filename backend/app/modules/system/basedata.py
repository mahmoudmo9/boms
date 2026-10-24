"""Countries, currencies and units: search, add, edit, activate/deactivate. No delete."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.text import normalize_fa
from app.modules.events import service as events
from app.modules.system.models import Country, Currency, Unit

UNIT_KINDS = ("count", "weight", "length", "area", "volume", "time", "other")


@dataclass(frozen=True)
class Kind:
    name: str  # entity_type for events
    model: type
    pk: str
    editable: tuple[str, ...]
    order: tuple[str, ...]


KINDS = {
    "countries": Kind("country", Country, "iso2", ("iso3", "name_fa", "name_en", "sort_order"), ("sort_order", "name_en")),
    "currencies": Kind("currency", Currency, "code", ("name_fa", "name_en", "symbol", "minor_units"), ("code",)),
    "units": Kind("unit", Unit, "code", ("name_fa", "name_en", "kind", "base_factor"), ("kind", "base_factor", "code")),
}


def get_kind(kind: str) -> Kind:
    if kind not in KINDS:
        raise NotFound(f"Unknown base data type {kind}.")
    return KINDS[kind]


def _search_text(model):
    """Same expression as the GIN indexes in migration 0002 (so they can be used)."""
    if model is Country:
        parts = [Country.iso2, Country.iso3, Country.name_fa, Country.name_en]
    else:
        parts = [model.code, model.name_fa, model.name_en]
    expr = parts[0]
    for part in parts[1:]:
        expr = expr.op("||")(literal_column("' '")).op("||")(part)
    return func.core.normalize_fa(expr)


def list_items(db: Session, kind: str, q: str | None = None, active: bool | None = None):
    k = get_kind(kind)
    query = select(k.model)
    if active is not None:
        query = query.where(k.model.active == active)
    if q and (nq := normalize_fa(q)):
        query = query.where(_search_text(k.model).contains(nq, autoescape=True))
    return list(db.scalars(query.order_by(*[getattr(k.model, c) for c in k.order])))


def _clean(k: Kind, data: dict) -> dict:
    out = {}
    for key, value in data.items():
        if key not in k.editable:
            continue
        if isinstance(value, str):
            value = value.strip()
        if key in ("name_fa", "name_en") and not value:
            raise AppError("Name is required.", code="invalid_value", field=key)
        if key == "iso3" and not (isinstance(value, str) and len(value) == 3 and value.isalpha()):
            raise AppError("ISO3 must be 3 letters.", code="invalid_value", field=key)
        if key == "iso3":
            value = value.upper()
        if key == "kind" and value not in UNIT_KINDS:
            raise AppError("Invalid unit kind.", code="invalid_value", field=key)
        if key == "minor_units" and value not in (0, 1, 2, 3, 4):
            raise AppError("Minor units must be 0-4.", code="invalid_value", field=key)
        if key == "base_factor":
            if isinstance(value, float):
                value = str(value)
            try:
                value = Decimal(value)
            except (InvalidOperation, TypeError):
                raise AppError("Invalid factor.", code="invalid_value", field=key) from None
            if value <= 0:
                raise AppError("Factor must be positive.", code="invalid_value", field=key)
        out[key] = value
    return out


def _normalize_pk(kind: str, pk: str) -> str:
    pk = (pk or "").strip()
    if kind == "countries" and (len(pk) != 2 or not pk.isalpha()):
        raise AppError("ISO2 must be 2 letters.", code="invalid_value", field="iso2")
    if kind == "currencies" and (len(pk) != 3 or not pk.isalpha()):
        raise AppError("Currency code must be 3 letters.", code="invalid_value", field="code")
    if kind == "units":
        pk = pk.lower()
        if not pk or len(pk) > 20 or not all(c.isascii() and (c.isalnum() or c == "_") for c in pk):
            raise AppError("Unit code: a-z, 0-9, _ (max 20).", code="invalid_value", field="code")
        return pk
    return pk.upper()


def _jsonable(data: dict) -> dict:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in data.items()}


def create_item(db: Session, kind: str, data: dict, source: str = "ui", actor: str = "user"):
    k = get_kind(kind)
    pk = _normalize_pk(kind, data.get(k.pk, ""))
    if db.get(k.model, pk) is not None:
        raise Conflict("This code already exists.", code="duplicate_code")
    values = _clean(k, data)
    missing = [f for f in k.editable if f not in values and f not in ("sort_order", "symbol", "minor_units")]
    if missing:
        raise AppError(f"Missing fields: {', '.join(missing)}", code="invalid_value", field=missing[0])
    item = k.model(**{k.pk: pk}, **values)
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict("Duplicate value.", code="duplicate_code") from None
    events.record(db, k.name, pk, f"{k.name}.created", _jsonable(values), source, actor)
    return item


def update_item(db: Session, kind: str, pk: str, data: dict, source: str = "ui", actor: str = "user"):
    k = get_kind(kind)
    item = db.get(k.model, pk)
    if item is None:
        raise NotFound("Not found.")
    changes = {}
    for key, value in _clean(k, data).items():
        if getattr(item, key) != value:
            changes[key] = {"from": getattr(item, key), "to": value}
            setattr(item, key, value)
    if "active" in data and isinstance(data["active"], bool) and data["active"] != item.active:
        changes["active"] = {"from": item.active, "to": data["active"]}
        item.active = data["active"]
    if changes:
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise Conflict("Duplicate value.", code="duplicate_code") from None
        action = f"{k.name}.updated"
        if list(changes) == ["active"]:
            action = f"{k.name}.{'activated' if item.active else 'deactivated'}"
        events.record(
            db, k.name, pk, action, {c: _jsonable(v) for c, v in changes.items()}, source, actor
        )
    return item


def search(db: Session, q: str, limit: int = 8) -> dict[str, list]:
    """Used by the global search provider: fuzzy match across all three tables."""
    nq = normalize_fa(q) or ""
    results = {}
    for kind, k in KINDS.items():
        doc = _search_text(k.model)
        score = func.greatest(func.word_similarity(nq, doc), func.similarity(nq, doc))
        query = (
            select(k.model, score.label("score"))
            .where(or_(doc.contains(nq, autoescape=True), func.word_similarity(nq, doc) > 0.4,
                       func.to_tsvector("simple", doc).op("@@")(func.plainto_tsquery("simple", nq))))
            .order_by(score.desc())
            .limit(limit)
        )
        results[kind] = [(row[0], float(row[1])) for row in db.execute(query)]
    return results
