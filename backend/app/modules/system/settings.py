"""Application settings stored in ``sys.setting`` (key -> jsonb value)."""

import re
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import VERSION, get_config
from app.core.db import get_db
from app.core.errors import AppError
from app.core.web import request_source
from app.modules.events import service as events
from app.modules.system.auth import CurrentUser
from app.modules.system.models import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _time(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("expected HH:MM")
    return value


def _optional_path(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("expected a folder path")
    return value.strip()


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected true/false")
    return value


def _int_range(low: int, high: int) -> Callable[[Any], int]:
    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"expected an integer {low}..{high}")
        return value

    return check


# key -> (default, validator)
DEFINITIONS: dict[str, tuple[Any, Callable[[Any], Any]]] = {
    "backup.time": ("02:00", _time),
    "backup.secondary_path": (None, _optional_path),
    "backup.archive_enabled": (False, _bool),
    "backup.archive_path": (None, _optional_path),
    "upload.max_mb": (100, _int_range(1, 2048)),
}


def get_all(db: Session) -> dict[str, Any]:
    values = {key: default for key, (default, _) in DEFINITIONS.items()}
    for row in db.scalars(select(Setting).where(Setting.key.in_(DEFINITIONS))):
        values[row.key] = row.value
    return values


def get(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    return row.value if row is not None else DEFINITIONS[key][0]


def update(db: Session, changes: dict[str, Any], source: str, actor: str | None = None) -> dict[str, Any]:
    errors = {}
    clean = {}
    for key, value in changes.items():
        if key not in DEFINITIONS:
            errors[key] = "unknown setting"
            continue
        try:
            clean[key] = DEFINITIONS[key][1](value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise AppError("invalid_settings", "Invalid settings", {"fields": errors}, status=422)

    for key, value in clean.items():
        row = db.get(Setting, key)
        old = row.value if row is not None else DEFINITIONS[key][0]
        if old == value:
            continue
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
        db.flush()
        events.record(db, "setting", key, "update", {"old": old, "new": value}, source, actor=actor)
    return get_all(db)


def _response(db: Session) -> dict[str, Any]:
    return {"values": get_all(db), "data_dir": str(get_config().data_dir), "version": VERSION}


@router.get("")
def read_settings(_: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    return _response(db)


@router.patch("")
def patch_settings(body: dict[str, Any], request: Request, user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    update(db, body, request_source(request), actor=user.username)
    db.commit()
    return _response(db)
