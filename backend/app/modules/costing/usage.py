"""Who uses a cost sheet: later modules (quotes) register a counter so costing does not import them."""

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

_counters: list[Callable[[Session, uuid.UUID], int]] = []


def register_sheet_usage(fn: Callable[[Session, uuid.UUID], int]) -> None:
    if fn not in _counters:
        _counters.append(fn)


def quotes_using_sheet(db: Session, sheet_id: uuid.UUID) -> int:
    return sum(fn(db, sheet_id) for fn in _counters)
