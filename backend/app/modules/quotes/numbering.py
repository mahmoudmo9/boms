"""Quote numbers ``PI-<year>-<seq>``: a sequence per year (the user's calendar), handed out in the creating
transaction. ``INSERT .. ON CONFLICT DO UPDATE .. RETURNING`` locks the year's row until commit, so concurrent
creations wait for each other and a rolled-back creation gives its number back: no gaps, no duplicates."""

from datetime import date

from sqlalchemy.orm import Session

from app.modules.sourcing.jalali import to_jalali


def numbering_year(on: date, calendar: str) -> int:
    return to_jalali(on)[0] if calendar == "jalali" else on.year


def next_number(db: Session, year: int) -> str:
    """v0.9.0: the number comes from the codes service (pattern ``codes.pattern.quote``, default PI-{yyyy}-{0000});
    the old ``ops.quote_sequence`` was carried over into ``core.code_sequence`` by migration 0018."""
    from app.modules.codes import service as codes

    return codes.next(db, "quote", {"yyyy": year}, table="ops.quote", column="number")
