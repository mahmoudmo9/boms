"""Quote numbers ``PI-<year>-<seq>``: a sequence per year (the user's calendar), handed out in the creating
transaction. ``INSERT .. ON CONFLICT DO UPDATE .. RETURNING`` locks the year's row until commit, so concurrent
creations wait for each other and a rolled-back creation gives its number back: no gaps, no duplicates."""

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.sourcing.jalali import to_jalali


def numbering_year(on: date, calendar: str) -> int:
    return to_jalali(on)[0] if calendar == "jalali" else on.year


def next_number(db: Session, year: int) -> str:
    seq = db.execute(text(
        "INSERT INTO ops.quote_sequence (year, last_number) VALUES (:y, 1) "
        "ON CONFLICT (year) DO UPDATE SET last_number = ops.quote_sequence.last_number + 1 RETURNING last_number"
    ), {"y": year}).scalar_one()
    return f"PI-{year}-{seq:04d}"
