"""The single app user: creation, preferences, password."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.security import hash_password, verify_password
from app.modules.events import service as events
from app.modules.system.models import AppUser

MIN_PASSWORD_LENGTH = 8
PREFERENCE_FIELDS = ("username", "language", "calendar", "digits", "theme", "idle_lock_minutes")


def get_user(db: Session) -> AppUser | None:
    return db.scalars(select(AppUser).limit(1)).first()


def require_user(db: Session) -> AppUser:
    user = get_user(db)
    if user is None:
        raise NotFound("no_user", "No user has been created yet")
    return user


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AppError("password_too_short", f"Password must have at least {MIN_PASSWORD_LENGTH} characters",
                       {"min": MIN_PASSWORD_LENGTH})


def create_user(db: Session, username: str, password: str, source: str = "script", **prefs) -> AppUser:
    if db.scalar(select(func.count()).select_from(AppUser)):
        raise Conflict("user_exists", "The user already exists")
    check_password_rules(password)
    user = AppUser(username=username.strip(), password_hash=hash_password(password), **prefs)
    db.add(user)
    db.flush()
    events.record(db, "app_user", user.id, "create", {"username": user.username}, source, actor=user.username)
    return user


def update_preferences(db: Session, user: AppUser, changes: dict, source: str) -> AppUser:
    changed = {}
    for key, value in changes.items():
        if key not in PREFERENCE_FIELDS or value is None:
            continue
        if key == "username":
            value = value.strip()
        if getattr(user, key) != value:
            changed[key] = {"old": getattr(user, key), "new": value}
            setattr(user, key, value)
    if changed:
        db.flush()
        events.record(db, "app_user", user.id, "update", {"changes": changed}, source, actor=user.username)
    return user


def change_password(db: Session, user: AppUser, current: str, new: str, source: str) -> None:
    if not verify_password(user.password_hash, current):
        raise AppError("wrong_password", "Current password is wrong", status=400)
    check_password_rules(new)
    user.password_hash = hash_password(new)
    db.flush()
    events.record(db, "app_user", user.id, "password_change", {}, source, actor=user.username)


def set_password(db: Session, new: str, source: str = "script") -> None:
    """Reset the password without the old one (CLI / install repair only)."""
    user = require_user(db)
    check_password_rules(new)
    user.password_hash = hash_password(new)
    db.flush()
    events.record(db, "app_user", user.id, "password_reset", {}, source, actor=user.username)
