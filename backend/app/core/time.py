"""Time helpers. All datetimes are timezone-aware; storage and transport are UTC."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime is not allowed")
    return value.astimezone(UTC)


def local_now() -> datetime:
    """Current time in the PC's local timezone (used only for scheduling)."""
    return datetime.now().astimezone()
