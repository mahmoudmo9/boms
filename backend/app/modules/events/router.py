"""HTTP routes of the events module: the Event Log timeline."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.modules.events import service
from app.modules.system.auth import current_user

router = APIRouter(prefix="/api/events", tags=["events"], dependencies=[Depends(current_user)])


@router.get("")
def list_events(
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    for value in (date_from, date_to):
        if value is not None and value.tzinfo is None:
            raise AppError("Dates must include a timezone (ISO 8601, UTC).", code="invalid_value")
    items, total = service.list_events(db, entity_type, entity_id, action, date_from, date_to, page, page_size)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": e.id,
                "occurred_at": e.occurred_at,
                "actor": e.actor,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "action": e.action,
                "data": e.data,
                "source": e.source,
            }
            for e in items
        ],
    }


@router.get("/filters")
def filters(db: Session = Depends(get_db)):
    return service.filter_options(db)
