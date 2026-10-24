"""HTTP-level protections: Host header check (DNS rebinding) and CSRF.

Both are plain ASGI middlewares so they also cover streaming responses.
CSRF uses the double-submit pattern: state-changing /api requests must send
header X-CSRF-Token equal to the boms_csrf cookie, and any Origin header must
be the app's own origin.
"""

import hmac
import json
from http.cookies import SimpleCookie

from fastapi import Request

from app.core.config import get_config
from app.core.errors import error_body
from app.core.security import CSRF_COOKIE, CSRF_HEADER

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def _send_json(send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


class HostCheckMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = _headers(scope).get("host", "").lower()
            if host not in get_config().allowed_hosts:
                await _send_json(send, 400, error_body("bad_host", "Invalid Host header."))
                return
        await self.app(scope, receive, send)


class CSRFMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS and scope["path"].startswith("/api/"):
            headers = _headers(scope)
            origin = headers.get("origin")
            if origin is not None and origin not in get_config().allowed_origins:
                await _send_json(send, 403, error_body("csrf", "Cross-origin request rejected."))
                return
            cookie = SimpleCookie()
            cookie.load(headers.get("cookie", ""))
            expected = cookie[CSRF_COOKIE].value if CSRF_COOKIE in cookie else ""
            sent = headers.get(CSRF_HEADER, "")
            if not expected or not hmac.compare_digest(expected, sent):
                await _send_json(send, 403, error_body("csrf", "Missing or invalid CSRF token."))
                return
        await self.app(scope, receive, send)


def request_source(request: Request) -> str:
    """Events from the bundled UI are tagged 'ui'; other HTTP clients 'api'."""
    return "ui" if request.headers.get("x-boms-client") == "ui" else "api"
