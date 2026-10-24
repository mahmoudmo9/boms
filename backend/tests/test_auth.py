"""Auth and HTTP security: password, rate limit, idle lock, CSRF, Host header."""

import time

import pytest
from fastapi.testclient import TestClient

from app.core.security import CSRF_COOKIE, SESSION_COOKIE, login_limiter, sign_session
from app.main import app
from tests.helpers import PASSWORD, USERNAME, login, make_client


def test_wrong_password_rejected(user):
    client = make_client()
    r = client.post("/api/auth/login", json={"username": USERNAME, "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    assert client.get("/api/me").status_code == 401
    login_limiter.reset()


def test_login_and_access(user):
    client = login()
    r = client.get("/api/me")
    assert r.status_code == 200 and r.json()["username"] == USERNAME
    cookie = next(c for c in client.cookies.jar if c.name == SESSION_COOKIE)
    assert cookie.has_nonstandard_attr("HttpOnly")


def test_rate_limit_triggers(user):
    login_limiter.reset()
    client = make_client()
    for _ in range(login_limiter.max_failures):
        assert client.post("/api/auth/login", json={"username": USERNAME, "password": "nope-nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    login_limiter.reset()
    assert client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD}).status_code == 200


def test_idle_lock(user):
    client = login()
    client.patch("/api/me", json={"idle_lock_minutes": 1})
    stale = sign_session({"uid": str(user.id), "login": int(time.time()) - 600, "last": int(time.time()) - 120})
    client.cookies.set(SESSION_COOKIE, stale, domain="127.0.0.1")
    r = client.get("/api/me")
    assert r.status_code == 401 and r.json()["error"]["code"] == "locked"
    assert client.get("/api/auth/state").json()["state"] == "locked"
    # Unlock asks only for the password.
    assert client.post("/api/auth/unlock", json={"password": "wrong-password"}).status_code == 401
    login_limiter.reset()
    assert client.post("/api/auth/unlock", json={"password": PASSWORD}).status_code == 200
    assert client.get("/api/me").status_code == 200
    client.patch("/api/me", json={"idle_lock_minutes": 30})


def test_background_requests_do_not_extend_session(user):
    client = login()
    old = client.cookies.get(SESSION_COOKIE)
    time.sleep(1.1)
    client.get("/api/me", headers={"X-BOMS-Background": "1"})
    assert client.cookies.get(SESSION_COOKIE) == old
    client.get("/api/me")
    assert client.cookies.get(SESSION_COOKIE) != old


def test_csrf_blocks_request_without_token(user):
    client = login()
    client.headers.pop("x-csrf-token")
    r = client.patch("/api/me", json={"theme": "dark"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    r = client.patch("/api/me", json={"theme": "dark"}, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    r = client.patch("/api/me", json={"theme": "dark"},
                     headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE), "Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.patch("/api/me", json={"theme": "dark"}, headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE)})
    assert r.status_code == 200


def test_wrong_host_header_rejected(user):
    for base in ("http://evil.example:8765", "http://127.0.0.1:9999", "http://attacker.localhost:8765"):
        r = TestClient(app, base_url=base).get("/api/health")
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_host"
    for base in ("http://127.0.0.1:8765", "http://localhost:8765"):
        assert TestClient(app, base_url=base).get("/api/health").status_code == 200


@pytest.mark.parametrize("path", ["/api/me", "/api/settings", "/api/events", "/api/base/countries"])
def test_protected_routes_require_login(user, path):
    assert make_client().get(path).status_code == 401


def test_preferences_persist_and_emit_event(user, db):
    client = login()
    r = client.patch("/api/me", json={"language": "en", "calendar": "gregorian", "digits": "latin"})
    assert r.status_code == 200 and r.json()["language"] == "en"
    events = client.get("/api/events", params={"action": "user.preferences_changed"}).json()
    assert events["items"][0]["source"] == "ui"
    assert events["items"][0]["data"]["language"] == {"from": "fa", "to": "en"}
    client.patch("/api/me", json={"language": "fa", "calendar": "jalali", "digits": "fa"})
    assert client.patch("/api/me", json={"theme": "purple"}).status_code == 400


def test_change_password(user):
    client = login()
    r = client.post("/api/me/password", json={"current_password": "wrong-one", "new_password": "another-pass-1"})
    assert r.status_code == 400
    r = client.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "weak_password"
    r = client.post("/api/me/password", json={"current_password": PASSWORD, "new_password": "another-pass-1"})
    assert r.status_code == 200
    client.post("/api/me/password", json={"current_password": "another-pass-1", "new_password": PASSWORD})


def test_settings_validation(user):
    client = login()
    r = client.patch("/api/settings", json={"backup.time": "03:30", "upload.max_mb": 50})
    assert r.status_code == 200 and r.json()["values"]["backup.time"] == "03:30"
    assert client.patch("/api/settings", json={"backup.time": "25:00"}).status_code == 400
    assert client.patch("/api/settings", json={"nope": 1}).status_code == 400
    client.patch("/api/settings", json={"backup.time": "02:00", "upload.max_mb": 100})


def test_base_data_api(user):
    client = login()
    r = client.get("/api/base/currencies", params={"q": "یورو"})
    assert [c["code"] for c in r.json()["items"]] == ["EUR"]
    r = client.post("/api/base/countries", json={"iso2": "XK", "iso3": "XKX", "name_fa": "کوزوو", "name_en": "Kosovo"})
    assert r.status_code == 201
    assert client.post("/api/base/countries", json={"iso2": "XK", "iso3": "XKY", "name_fa": "x", "name_en": "x"}).status_code == 409
    r = client.patch("/api/base/countries/XK", json={"active": False})
    assert r.status_code == 200 and r.json()["active"] is False
    assert client.delete("/api/base/countries/XK").status_code == 405
