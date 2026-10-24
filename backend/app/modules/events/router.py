from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.schemas import ApiModel, Page, page_params
from app.modules.events import service
from app.modules.system.auth import CurrentUser

router = APIRouter(prefix="/api/events", tags=["events"])


class EventOut(ApiModel):
    id: int
    occurred_at: datetime
    actor: str
    entity_type: str
    entity_id: str | None
    action: str
    data: dict[str, Any]
    source: str


@router.get("", response_model=Page[EventOut])
def list_events(
    _: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
    page: int = 1,
    page_size: Annotated[int, Query(le=500)] = 50,
):
    page, page_size = page_params(page, page_size)
    try:
        rows, total = service.list_events(db, entity_type=entity_type, entity_id=entity_id, action=action,
                                          date_from=date_from, date_to=date_to, page=page, page_size=page_size)
    except ValueError as exc:
        raise AppError("invalid_date", str(exc), status=422) from exc
    return Page(items=[EventOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/facets")
def facets(_: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return service.facets(db)
