"""Application settings stored in sys.setting (key -> jsonb). Unknown keys are rejected."""

import re
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.events import service as events
from app.modules.system.models import Setting


def _time_hhmm(v) -> bool:
    return isinstance(v, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) is not None


def _opt_path(v) -> bool:
    return v is None or (isinstance(v, str) and len(v) <= 500)


# key -> (default, validator)
DEFINITIONS: dict[str, tuple[object, Callable[[object], bool]]] = {
    "backup.time": ("02:00", _time_hhmm),
    "backup.secondary_path": (None, _opt_path),
    "backup.archive_enabled": (False, lambda v: isinstance(v, bool)),
    "backup.archive_path": (None, _opt_path),
    "upload.max_mb": (100, lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 2048),
}

# Internal bookkeeping keys (written by the worker, not editable from the UI).
INTERNAL_PREFIX = "state."


def get_all(db: Session) -> dict[str, object]:
    stored = {s.key: s.value for s in db.scalars(select(Setting).where(Setting.key.in_(DEFINITIONS)))}
    return {key: stored.get(key, default) for key, (default, _) in DEFINITIONS.items()}


def get(db: Session, key: str):
    row = db.get(Setting, key)
    if row is not None:
        return row.value
    if key in DEFINITIONS:
        return DEFINITIONS[key][0]
    return None


def update(db: Session, changes: dict[str, object], source: str = "ui", actor: str = "user") -> dict[str, object]:
    for key, value in changes.items():
        if key not in DEFINITIONS:
            raise AppError(f"Unknown setting {key}.", code="invalid_value", field=key)
        if not DEFINITIONS[key][1](value):
            raise AppError(f"Invalid value for {key}.", code="invalid_value", field=key)
    applied = {}
    for key, value in changes.items():
        old = get(db, key)
        if old != value:
            _put(db, key, value)
            applied[key] = {"from": old, "to": value}
    if applied:
        db.flush()
        events.record(db, "setting", "app", "settings.changed", applied, source, actor=actor)
    return get_all(db)


def _put(db: Session, key: str, value) -> None:
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def set_state(db: Session, key: str, value) -> None:
    """Internal state used by the scheduler (e.g. last run dates). No event: it is bookkeeping."""
    _put(db, INTERNAL_PREFIX + key, value)
    db.flush()


def get_state(db: Session, key: str):
    row = db.get(Setting, INTERNAL_PREFIX + key)
    return row.value if row else None
