"""Order numbers ``SO-<year>-<seq>`` and ``PO-<year>-<seq>``: one sequence per kind and year (the user's calendar),
handed out in the creating transaction under a row lock, exactly like quote numbers (no gaps, no duplicates)."""

from sqlalchemy.orm import Session

from app.modules.quotes.numbering import numbering_year

PREFIX = {"sales_order": "SO", "purchase_order": "PO"}

__all__ = ["next_number", "numbering_year"]


def next_number(db: Session, kind: str, year: int) -> str:
    """v0.9.0: through the codes service (patterns ``codes.pattern.sales_order`` / ``purchase_order``); the old
    per-kind sequences were carried over into ``core.code_sequence`` by migration 0018."""
    from app.modules.codes import service as codes

    return codes.next(db, kind, {"yyyy": year}, table=f"ops.{kind}", column="number")
