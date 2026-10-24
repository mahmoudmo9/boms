"""Public service of the events module.

``record`` is the only way to write an event. Call it inside the same session
(transaction) as the change it describes; the caller commits.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.time import ensure_aware
from app.modules.events.models import Event

SOURCES = {"ui", "api", "worker", "script"}


def record(
    db: Session,
    entity_type: str,
    entity_id: Any,
    action: str,
    data: dict | None = None,
    source: str = "api",
    actor: str | None = None,
) -> Event:
    if source not in SOURCES:
        raise ValueError(f"invalid event source: {source}")
    event = Event(
        actor=actor or ("worker" if source == "worker" else "system"),
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        action=action,
        data=data or {},
        source=source,
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session,
    *,
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
        query = query.where(Event.occurred_at >= ensure_aware(date_from))
    if date_to:
        query = query.where(Event.occurred_at < ensure_aware(date_to))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(Event.occurred_at.desc(), Event.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return list(rows), total


def facets(db: Session) -> dict[str, list[str]]:
    """Distinct entity types and actions, for the Event Log filters."""
    entity_types = db.scalars(select(Event.entity_type).distinct().order_by(Event.entity_type)).all()
    actions = db.scalars(select(Event.action).distinct().order_by(Event.action)).all()
    return {"entity_types": list(entity_types), "actions": list(actions)}
