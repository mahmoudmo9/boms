"""Login, idle lock, logout, and the ``current_user`` dependency.

The session is a signed cookie: ``{"uid", "pv", "t", "lk"}`` = user id,
password fingerprint, last user activity (epoch seconds) and the locked flag.
Requests sent with ``X-BOMS-Background: 1`` (UI polling) do not count as activity.
"""

import time
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, Unauthorized
from app.core.schemas import ApiModel
from app.core.security import login_limiter, password_version, verify_password
from app.core.web import get_session, request_source, set_session
from app.modules.events import service as events
from app.modules.system import users
from app.modules.system.models import AppUser

router = APIRouter(prefix="/api", tags=["auth"])


def now() -> float:
    """Wall clock, as a function so tests can move time forward."""
    return time.time()


class Locked(AppError):
    status = 423

    def __init__(self):
        super().__init__("locked", "Session is locked")


def current_user(request: Request, db: Annotated[Session, Depends(get_db)]) -> AppUser:
    session = get_session(request)
    if not session:
        raise Unauthorized("not_authenticated", "Login required")
    try:
        user = db.get(AppUser, uuid.UUID(session.get("uid", "")))
    except ValueError:
        user = None
    if user is None or session.get("pv") != password_version(user.password_hash):
        set_session(request, None)
        raise Unauthorized("not_authenticated", "Login required")

    current = now()
    if session.get("lk") or current - session.get("t", 0) > user.idle_lock_minutes * 60:
        if not session.get("lk"):
            set_session(request, {**session, "lk": True})
        raise Locked()
    if request.headers.get("x-boms-background") != "1":
        set_session(request, {**session, "t": int(current)})
    request.state.user = user
    return user


CurrentUser = Annotated[AppUser, Depends(current_user)]
Db = Annotated[Session, Depends(get_db)]


class UserOut(ApiModel):
    id: uuid.UUID
    username: str
    language: str
    calendar: str
    digits: str
    theme: str
    idle_lock_minutes: int


class AuthState(BaseModel):
    user_exists: bool
    authenticated: bool
    locked: bool
    username: str | None = None
    language: str | None = None
    theme: str | None = None
    user: UserOut | None = None


class LoginIn(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


class UnlockIn(BaseModel):
    password: str = Field(max_length=1024)


class PreferencesIn(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    language: Literal["fa", "en"] | None = None
    calendar: Literal["jalali", "gregorian"] | None = None
    digits: Literal["fa", "latin"] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    idle_lock_minutes: int | None = Field(default=None, ge=1, le=1440)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)


def _check_rate_limit() -> None:
    wait = login_limiter.retry_after()
    if wait:
        raise AppError("rate_limited", "Too many failed attempts", {"retry_after": wait}, status=429)


def _password_failed(db: Session, user: AppUser | None, action: str, request: Request) -> None:
    login_limiter.failure()
    events.record(db, "app_user", user.id if user else None, action, {}, request_source(request),
                  actor=user.username if user else "anonymous")
    db.commit()


def _start_session(request: Request, user: AppUser) -> None:
    set_session(request, {"uid": str(user.id), "pv": password_version(user.password_hash),
                          "t": int(now()), "lk": False})


@router.get("/auth/state", response_model=AuthState)
def auth_state(request: Request, db: Db):
    user = users.get_user(db)
    if user is None:
        return AuthState(user_exists=False, authenticated=False, locked=False)
    state = AuthState(user_exists=True, authenticated=False, locked=False,
                      username=user.username, language=user.language, theme=user.theme)
    try:
        current_user(request, db)
    except Locked:
        state.authenticated = True
        state.locked = True
    except Unauthorized:
        pass
    else:
        state.authenticated = True
        state.user = UserOut.model_validate(user)
    return state


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginIn, request: Request, db: Db):
    _check_rate_limit()
    user = users.get_user(db)
    ok = user is not None and body.username.strip() == user.username and verify_password(user.password_hash, body.password)
    if not ok:
        _password_failed(db, user, "login_failed", request)
        raise Unauthorized("invalid_credentials", "Wrong username or password")
    login_limiter.reset()
    _start_session(request, user)
    events.record(db, "app_user", user.id, "login", {}, request_source(request), actor=user.username)
    db.commit()
    return user


@router.post("/auth/unlock", response_model=UserOut)
def unlock(body: UnlockIn, request: Request, db: Db):
    session = get_session(request)
    if not session:
        raise Unauthorized("not_authenticated", "Login required")
    _check_rate_limit()
    user = users.get_user(db)
    if user is None or str(user.id) != session.get("uid") or not verify_password(user.password_hash, body.password):
        _password_failed(db, user, "unlock_failed", request)
        raise Unauthorized("invalid_credentials", "Wrong password")
    login_limiter.reset()
    _start_session(request, user)
    events.record(db, "app_user", user.id, "unlock", {}, request_source(request), actor=user.username)
    db.commit()
    return user


@router.post("/auth/lock", status_code=204)
def lock(request: Request, db: Db):
    session = get_session(request)
    if session and not session.get("lk"):
        set_session(request, {**session, "lk": True})
        user = users.get_user(db)
        if user is not None:
            events.record(db, "app_user", user.id, "lock", {}, request_source(request), actor=user.username)
            db.commit()


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db: Db):
    session = get_session(request)
    set_session(request, None)
    user = users.get_user(db)
    if session and user is not None:
        events.record(db, "app_user", user.id, "logout", {}, request_source(request), actor=user.username)
        db.commit()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(body: PreferencesIn, request: Request, user: CurrentUser, db: Db):
    users.update_preferences(db, user, body.model_dump(exclude_none=True), request_source(request))
    db.commit()
    return user


@router.post("/me/password", status_code=204)
def change_password(body: PasswordIn, request: Request, user: CurrentUser, db: Db):
    _check_rate_limit()
    try:
        users.change_password(db, user, body.current_password, body.new_password, request_source(request))
    except AppError as exc:
        if exc.code == "wrong_password":
            db.rollback()
            _password_failed(db, user, "password_change_failed", request)
        raise
    db.commit()
    _start_session(request, user)
