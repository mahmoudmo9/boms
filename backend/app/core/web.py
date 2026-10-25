"""HTTP security layer: Host check, CSRF, session cookie handling, security headers.

One middleware, applied to every request (API and static files):
1. Host header must be ``127.0.0.1:<port>`` or ``localhost:<port>`` (DNS rebinding).
2. State-changing requests need a matching CSRF double-submit token and,
   when the browser sends one, a same-origin ``Origin`` header.
3. The signed session cookie is decoded into ``request.state.session`` and
   re-issued when a handler changes it.
"""

import hmac
import json
import re

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


# C0 control characters except tab, newline and carriage return. PostgreSQL rejects NUL in text.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def has_control_characters(value: str | None) -> bool:
    return bool(value) and CONTROL_CHARS.search(value) is not None


def _json_has_control_characters(value) -> bool:
    if isinstance(value, str):
        return has_control_characters(value)
    if isinstance(value, dict):
        return any(has_control_characters(k) or _json_has_control_characters(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_json_has_control_characters(v) for v in value)
    return False


async def find_control_characters(request: Request) -> str | None:
    """Where the request carries control characters (path, query, JSON body), or None."""
    if has_control_characters(request.url.path):
        return "the path"
    if any(has_control_characters(k) or has_control_characters(v) for k, v in request.query_params.multi_items()):
        return "query parameters"
    if request.method in {"POST", "PUT", "PATCH"} and \
            request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = json.loads(await request.body() or b"null")
        except ValueError:
            return None  # malformed JSON: FastAPI answers 422 itself
        if _json_has_control_characters(body):
            return "the request body"
    return None


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
            # compare as bytes: compare_digest raises TypeError on non-ASCII str
            if not csrf_cookie or not header or not hmac.compare_digest(csrf_cookie.encode(), header.encode()):
                return _reject(403, "csrf_failed", "Missing or invalid CSRF token")

        if bad := await find_control_characters(request):
            return _reject(422, "invalid_input", f"Control characters are not allowed in {bad}")

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
