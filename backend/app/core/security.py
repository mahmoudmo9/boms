"""Password hashing, signed session cookies, CSRF tokens and login rate limiting.

Session cookie: base64url(JSON payload) + "." + HMAC-SHA256 signature, keyed by
the session_key secret. The payload holds the user id, the login time and the
last-activity time; the server enforces the idle lock from "last".
"""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.secrets import get_secret

SESSION_COOKIE = "boms_session"
CSRF_COOKIE = "boms_csrf"
CSRF_HEADER = "x-csrf-token"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _key() -> bytes:
    return get_secret("session_key").encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_session(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_session(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        return json.loads(_unb64(body))
    except ValueError:
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class LoginRateLimiter:
    """At most `max_failures` failed logins within `window` seconds (process-local, single user)."""

    def __init__(self, max_failures: int = 5, window: float = 300.0):
        self.max_failures = max_failures
        self.window = window
        self._failures: deque[float] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        while self._failures and now - self._failures[0] > self.window:
            self._failures.popleft()

    def retry_after(self) -> int:
        """Seconds until another attempt is allowed; 0 if allowed now."""
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if len(self._failures) < self.max_failures:
                return 0
            return max(1, int(self.window - (now - self._failures[0])) + 1)

    def failed(self) -> None:
        with self._lock:
            self._failures.append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginRateLimiter()
