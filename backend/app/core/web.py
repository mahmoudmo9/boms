"""HTTP security layer: Host check, CSRF, session cookie handling, security headers.

One middleware, applied to every request (API and static files):
1. Host header must be ``127.0.0.1:<port>`` or ``localhost:<port>`` (DNS rebinding).
2. State-changing requests need a matching CSRF double-submit token and,
   when the browser sends one, a same-origin ``Origin`` header.
3. The signed session cookie is decoded into ``request.state.session`` and
   re-issued when a handler changes it.
"""

import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_config
from app.core.errors import error_body
from app.core.security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    new_token,
    read_session,
    sign_session,
)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; object-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
        "base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def get_session(request: Request) -> dict | None:
    return getattr(request.state, "session", None)


def set_session(request: Request, payload: dict | None) -> None:
    request.state.session = payload
    request.state.session_changed = True


def request_source(request: Request) -> str:
    """Event source for a request: the UI marks its calls with ``X-BOMS-Client: ui``."""
    return "ui" if request.headers.get("x-boms-client") == "ui" else "api"


def _reject(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(error_body(code, message), status_code=status)


def install_security(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        config = get_config()
        host = request.headers.get("host", "")
        if host not in config.allowed_hosts:
            return _reject(400, "invalid_host", "Host header not allowed")

        csrf_cookie = request.cookies.get(CSRF_COOKIE)
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin and origin not in {f"http://{h}" for h in config.allowed_hosts}:
                return _reject(403, "csrf_failed", "Cross-origin request rejected")
            if request.headers.get("sec-fetch-site") == "cross-site":
                return _reject(403, "csrf_failed", "Cross-site request rejected")
            header = request.headers.get(CSRF_HEADER, "")
            if not csrf_cookie or not header or not hmac.compare_digest(csrf_cookie, header):
                return _reject(403, "csrf_failed", "Missing or invalid CSRF token")

        request.state.session = read_session(request.cookies.get(SESSION_COOKIE))
        request.state.session_changed = False

        response = await call_next(request)

        if request.state.session_changed:
            if request.state.session is None:
                response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
            else:
                response.set_cookie(
                    SESSION_COOKIE,
                    sign_session(request.state.session),
                    path="/",
                    httponly=True,
                    samesite="strict",
                )
        if not csrf_cookie:
            response.set_cookie(CSRF_COOKIE, new_token(), path="/", httponly=False, samesite="strict")
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response
