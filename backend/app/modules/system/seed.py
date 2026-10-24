"""Idempotent base-data seed. Existing rows are left untouched (user edits win)."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.events import service as events
from app.modules.system.models import Country, Currency, Unit
from app.modules.system.seed_data import COUNTRIES, CURRENCIES, SORT_FIRST, UNITS


def _insert_missing(db: Session, model, rows: list[dict]) -> int:
    result = db.execute(insert(model).values(rows).on_conflict_do_nothing().returning(model.__table__.primary_key.columns[0]))
    return len(result.all())


def seed_base_data(db: Session, source: str = "script") -> dict[str, int]:
    counts = {
        "countries": _insert_missing(db, Country, [
            {"iso2": a2, "iso3": a3, "name_fa": fa, "name_en": en, "sort_order": SORT_FIRST.get(a2, 100)}
            for a2, a3, fa, en in COUNTRIES
        ]),
        "currencies": _insert_missing(db, Currency, [
            {"code": c, "name_fa": fa, "name_en": en, "symbol": sym, "minor_units": mu, "active": active}
            for c, fa, en, sym, mu, active in CURRENCIES
        ]),
        "units": _insert_missing(db, Unit, [
            {"code": c, "name_fa": fa, "name_en": en, "kind": kind, "base_factor": factor}
            for c, fa, en, kind, factor in UNITS
        ]),
    }
    if any(counts.values()):
        events.record(db, "basedata", None, "seed", {"inserted": counts}, source)
    return counts
