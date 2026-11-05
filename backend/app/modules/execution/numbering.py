"""Order numbers ``SO-<year>-<seq>`` and ``PO-<year>-<seq>``: one sequence per kind and year (the user's calendar),
handed out in the creating transaction under a row lock, exactly like quote numbers (no gaps, no duplicates)."""

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.quotes.numbering import numbering_year

PREFIX = {"sales_order": "SO", "purchase_order": "PO"}

__all__ = ["next_number", "numbering_year"]


def next_number(db: Session, kind: str, year: int) -> str:
    table = f"ops.{kind}_sequence"
    seq = db.execute(text(
        f"INSERT INTO {table} (year, last_number) VALUES (:y, 1) "
        f"ON CONFLICT (year) DO UPDATE SET last_number = {table}.last_number + 1 RETURNING last_number"
    ), {"y": year}).scalar_one()
    return f"{PREFIX[kind]}-{year}-{seq:04d}"
