from app.modules.system import auth
from tests.conftest import TEST_PASSWORD


def test_wrong_password_rejected(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    assert anon_client.get("/api/me").status_code == 401


def test_login_and_me(client):
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["username"] == "admin"
    assert "password_hash" not in r.json()


def test_session_cookie_flags(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
    cookie = r.headers["set-cookie"]
    assert "boms_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie


def test_rate_limit_triggers(anon_client):
    for _ in range(5):
        assert anon_client.post("/api/auth/login", json={"username": "admin", "password": "nope-nope"}).status_code == 401
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
    assert r.status_code == 429
    assert r.json()["error"]["details"]["retry_after"] > 0


def test_idle_lock(client, monkeypatch):
    real_now = auth.now()
    assert client.get("/api/me").status_code == 200
    monkeypatch.setattr(auth, "now", lambda: real_now + 31 * 60)
    r = client.get("/api/me")
    assert r.status_code == 423
    assert r.json()["error"]["code"] == "locked"
    assert client.get("/api/auth/state").json()["locked"] is True
    # stays locked even if the clock goes back
    monkeypatch.setattr(auth, "now", lambda: real_now)
    assert client.get("/api/me").status_code == 423
    assert client.post("/api/auth/unlock", json={"password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/unlock", json={"password": TEST_PASSWORD}).status_code == 200
    assert client.get("/api/me").status_code == 200


def test_background_requests_do_not_extend_session(client, monkeypatch):
    start = auth.now()
    monkeypatch.setattr(auth, "now", lambda: start + 20 * 60)
    assert client.get("/api/me", headers={"X-BOMS-Background": "1"}).status_code == 200
    monkeypatch.setattr(auth, "now", lambda: start + 35 * 60)
    assert client.get("/api/me").status_code == 423


def test_manual_lock(client):
    assert client.post("/api/auth/lock").status_code == 204
    assert client.get("/api/me").status_code == 423


def test_csrf_blocks_request_without_token(client):
    r = client.patch("/api/me", json={"theme": "dark"}, headers={"X-CSRF-Token": ""})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"
    r = client.patch("/api/me", json={"theme": "dark"}, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403


def test_cross_origin_rejected(client):
    r = client.patch("/api/me", json={"theme": "dark"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_wrong_host_rejected(anon_client):
    r = anon_client.get("/api/health", headers={"Host": "evil.example:8765"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_host"
    assert anon_client.get("/api/health", headers={"Host": "localhost:8765"}).status_code == 200
    assert anon_client.get("/api/health", headers={"Host": "127.0.0.1:9999"}).status_code == 400


def test_preferences_update_and_event(client):
    r = client.patch("/api/me", json={"theme": "dark", "calendar": "gregorian"}, headers={"X-BOMS-Client": "ui"})
    assert r.status_code == 200 and r.json()["theme"] == "dark"
    events = client.get("/api/events", params={"entity_type": "app_user", "action": "update"}).json()["items"]
    assert events[0]["source"] == "ui"
    assert events[0]["data"]["changes"]["theme"]["new"] == "dark"
    assert client.patch("/api/me", json={"theme": "purple"}).status_code == 422
    client.patch("/api/me", json={"theme": "system", "calendar": "jalali"})


def test_password_change_invalidates_other_sessions(client, anon_client):
    from app.main import app
    from tests.conftest import ApiClient

    with ApiClient(app, base_url="http://127.0.0.1:8765") as other:
        assert other.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).status_code == 200
        r = client.post("/api/me/password", json={"current_password": "bad-password", "new_password": "new-password-1"})
        assert r.status_code == 400
        r = client.post("/api/me/password", json={"current_password": TEST_PASSWORD, "new_password": "short"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "password_too_short"
        r = client.post("/api/me/password", json={"current_password": TEST_PASSWORD, "new_password": "new-password-1"})
        assert r.status_code == 204
        assert client.get("/api/me").status_code == 200
        assert other.get("/api/me").status_code == 401
        r = client.post("/api/me/password", json={"current_password": "new-password-1", "new_password": TEST_PASSWORD})
        assert r.status_code == 204


def test_logout(client):
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_security_headers(anon_client):
    r = anon_client.get("/api/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
