"""Closing a deal (v0.8.0): the checklist of open obligations, the frozen deal result, read-only after close,
reopening with a reason. (The checklist and close / reopen arrive with milestone 3.)"""
import uuid

from sqlalchemy.orm import Session

from app.core.errors import Conflict


def ensure_open(db: Session, case_id: uuid.UUID) -> None:
    """Writes on a closed case are refused (409 ``case_closed``) except notes, ratings, documents and reopening."""
    from app.modules.sourcing import inquiries as sourcing

    case = sourcing.get_case(db, case_id)
    if case.status == "closed":
        raise Conflict("case_closed", "The deal is closed; reopen it (with a reason) to change it", {"status": case.status})
