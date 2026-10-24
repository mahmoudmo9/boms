"""Time helpers. All datetimes in BOMS are timezone-aware; storage is UTC."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    """Reject naive datetimes instead of guessing their zone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("naive datetime is not allowed")
    return value.astimezone(UTC)


def local_now() -> datetime:
    """Current time in the machine's local zone (used only for scheduling)."""
    return datetime.now().astimezone()
