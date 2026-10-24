"""Public service of the events module.

record() must be called by every state-changing service function, with the same
Session, so the event is committed (or rolled back) together with the change.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import require_aware
from app.modules.events.models import Event

SOURCES = ("ui", "api", "worker", "script")


def record(
    db: Session,
    entity_type: str,
    entity_id: Any,
    action: str,
    data: dict | None = None,
    source: str = "ui",
    actor: str = "user",
) -> Event:
    if source not in SOURCES:
        raise ValueError(f"invalid event source: {source}")
    event = Event(
        actor=actor,
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        data=data or {},
        source=source,
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Event], int]:
    query = select(Event)
    if entity_type:
        query = query.where(Event.entity_type == entity_type)
    if entity_id:
        query = query.where(Event.entity_id == entity_id)
    if action:
        query = query.where(Event.action == action)
    if date_from:
        query = query.where(Event.occurred_at >= require_aware(date_from))
    if date_to:
        query = query.where(Event.occurred_at < require_aware(date_to))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(Event.occurred_at.desc(), Event.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return list(rows), total


def filter_options(db: Session) -> dict[str, list[str]]:
    return {
        "entity_types": list(db.scalars(select(Event.entity_type).distinct().order_by(Event.entity_type))),
        "actions": list(db.scalars(select(Event.action).distinct().order_by(Event.action))),
    }
