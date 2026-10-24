"""Password hashing, signed session cookies, CSRF tokens and login rate limiting."""

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field

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


def password_version(password_hash: str) -> str:
    """Short fingerprint of the hash: a password change invalidates old sessions."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _key() -> bytes:
    return get_secret("session_key").encode()


def sign_session(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
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
        payload = json.loads(_unb64(body))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


@dataclass
class LoginRateLimiter:
    """At most ``max_failures`` failed password checks per ``window`` seconds.

    BOMS has one user and one backend process, so an in-memory limiter is enough.
    """

    max_failures: int = 5
    window: float = 300.0
    _failures: deque = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _prune(self, now: float) -> None:
        while self._failures and now - self._failures[0] > self.window:
            self._failures.popleft()

    def retry_after(self) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._failures) < self.max_failures:
                return 0
            return max(1, int(self.window - (now - self._failures[0])) + 1)

    def failure(self) -> None:
        with self._lock:
            self._failures.append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginRateLimiter()
