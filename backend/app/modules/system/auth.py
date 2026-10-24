"""Login, idle lock and the `current_user` dependency used by every protected route."""

import time

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, Unauthorized
from app.core.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    login_limiter,
    new_csrf_token,
    read_session,
    sign_session,
)
from app.core.web import request_source
from app.modules.events import service as events
from app.modules.system import users
from app.modules.system.models import AppUser

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Requests sent with this header (status polling) do not count as user activity.
BACKGROUND_HEADER = "x-boms-background"


def _set_session(response: Response, user: AppUser, login_at: float | None = None) -> None:
    now = int(time.time())
    token = sign_session({"uid": str(user.id), "login": int(login_at or now), "last": now})
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict", path="/")


def _ensure_csrf_cookie(request: Request, response: Response) -> None:
    if not request.cookies.get(CSRF_COOKIE):
        response.set_cookie(CSRF_COOKIE, new_csrf_token(), httponly=False, samesite="strict", path="/")


def current_user(request: Request, response: Response, db: Session = Depends(get_db)) -> AppUser:
    payload = read_session(request.cookies.get(SESSION_COOKIE))
    user = users.get_user(db)
    if not payload or user is None or payload.get("uid") != str(user.id):
        raise Unauthorized("Please sign in.", code="unauthenticated")
    if time.time() - payload.get("last", 0) > user.idle_lock_minutes * 60:
        raise Unauthorized("Session locked after inactivity.", code="locked")
    if request.headers.get(BACKGROUND_HEADER) != "1":
        _set_session(response, user, payload.get("login"))
    return user


def _check_rate_limit() -> None:
    wait = login_limiter.retry_after()
    if wait:
        raise AppError("Too many failed attempts. Try again later.", code="rate_limited", status=429, retry_after=wait)


class LoginIn(BaseModel):
    username: str
    password: str


class UnlockIn(BaseModel):
    password: str


def user_out(user: AppUser) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "language": user.language,
        "calendar": user.calendar,
        "digits": user.digits,
        "theme": user.theme,
        "idle_lock_minutes": user.idle_lock_minutes,
    }


@router.get("/state")
def auth_state(request: Request, response: Response, db: Session = Depends(get_db)):
    """Public: tells the UI whether to show login, lock screen or the app. Issues the CSRF cookie."""
    _ensure_csrf_cookie(request, response)
    user = users.get_user(db)
    payload = read_session(request.cookies.get(SESSION_COOKIE))
    state = "login"
    if user and payload and payload.get("uid") == str(user.id):
        state = "locked" if time.time() - payload.get("last", 0) > user.idle_lock_minutes * 60 else "ok"
    return {
        "state": state,
        "user_exists": user is not None,
        # Preferences are needed to render login/lock screens in the right language/theme.
        "preferences": {k: getattr(user, k) for k in ("language", "calendar", "digits", "theme")} if user else None,
        "user": user_out(user) if user and state == "ok" else None,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    _check_rate_limit()
    user = users.authenticate(db, body.password, body.username)
    if user is None:
        login_limiter.failed()
        events.record(db, "auth", "login", "auth.login_failed", {}, request_source(request), actor="anonymous")
        db.commit()
        raise Unauthorized("Wrong username or password.", code="bad_credentials")
    login_limiter.reset()
    events.record(db, "app_user", user.id, "auth.login", {}, request_source(request), actor=user.username)
    db.commit()
    _set_session(response, user)
    return {"user": user_out(user)}


@router.post("/unlock")
def unlock(body: UnlockIn, request: Request, response: Response, db: Session = Depends(get_db)):
    payload = read_session(request.cookies.get(SESSION_COOKIE))
    if not payload:
        raise Unauthorized("Please sign in.", code="unauthenticated")
    _check_rate_limit()
    user = users.authenticate(db, body.password)
    if user is None or payload.get("uid") != str(user.id):
        login_limiter.failed()
        events.record(db, "auth", "unlock", "auth.unlock_failed", {}, request_source(request), actor="anonymous")
        db.commit()
        raise Unauthorized("Wrong password.", code="bad_credentials")
    login_limiter.reset()
    events.record(db, "app_user", user.id, "auth.unlock", {}, request_source(request), actor=user.username)
    db.commit()
    _set_session(response, user, payload.get("login"))
    return {"user": user_out(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    payload = read_session(request.cookies.get(SESSION_COOKIE))
    if payload:
        events.record(db, "app_user", payload.get("uid", ""), "auth.logout", {}, request_source(request))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}
