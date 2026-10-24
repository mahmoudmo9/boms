"""The single application user: creation, authentication, preferences, password."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.security import hash_password, verify_password
from app.modules.events import service as events
from app.modules.system.models import AppUser

PREFERENCES = {
    "language": ("fa", "en"),
    "calendar": ("jalali", "gregorian"),
    "digits": ("fa", "latin"),
    "theme": ("light", "dark", "system"),
}
MIN_PASSWORD_LENGTH = 8


def get_user(db: Session) -> AppUser | None:
    return db.scalar(select(AppUser))


def require_user(db: Session) -> AppUser:
    user = get_user(db)
    if user is None:
        raise NotFound("No user has been created yet.", code="no_user")
    return user


def _check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", code="weak_password")


def create_user(db: Session, username: str, password: str, source: str = "script") -> AppUser:
    if get_user(db) is not None:
        raise Conflict("The user already exists.", code="user_exists")
    _check_password_rules(password)
    user = AppUser(username=username.strip(), password_hash=hash_password(password))
    db.add(user)
    db.flush()
    events.record(db, "app_user", user.id, "user.created", {"username": user.username}, source, actor="system")
    return user


def authenticate(db: Session, password: str, username: str | None = None) -> AppUser | None:
    """Check the password (and the username, when given). Returns the user or None."""
    user = get_user(db)
    if user is None:
        verify_password(hash_password("x"), password)  # keep timing similar
        return None
    if username is not None and username.strip().casefold() != user.username.casefold():
        verify_password(user.password_hash, password)
        return None
    return user if verify_password(user.password_hash, password) else None


def update_preferences(db: Session, changes: dict, source: str = "ui") -> AppUser:
    user = require_user(db)
    applied = {}
    for key, value in changes.items():
        if value is None:
            continue
        if key in PREFERENCES:
            if value not in PREFERENCES[key]:
                raise AppError(f"Invalid value for {key}.", code="invalid_value", field=key)
        elif key == "idle_lock_minutes":
            if not isinstance(value, int) or not 1 <= value <= 1440:
                raise AppError("Idle lock must be 1-1440 minutes.", code="invalid_value", field=key)
        else:
            raise AppError(f"Unknown preference {key}.", code="invalid_value", field=key)
        if getattr(user, key) != value:
            applied[key] = {"from": getattr(user, key), "to": value}
            setattr(user, key, value)
    if applied:
        db.flush()
        events.record(db, "app_user", user.id, "user.preferences_changed", applied, source, actor=user.username)
    return user


def change_password(db: Session, current: str, new: str, source: str = "ui") -> None:
    user = require_user(db)
    if not verify_password(user.password_hash, current):
        raise AppError("Current password is incorrect.", code="wrong_password")
    _check_password_rules(new)
    user.password_hash = hash_password(new)
    db.flush()
    events.record(db, "app_user", user.id, "user.password_changed", {}, source, actor=user.username)


def reset_password(db: Session, new: str, source: str = "script") -> None:
    """Set a new password without the old one (local CLI only)."""
    user = require_user(db)
    _check_password_rules(new)
    user.password_hash = hash_password(new)
    db.flush()
    events.record(db, "app_user", user.id, "user.password_reset", {}, source, actor="system")
