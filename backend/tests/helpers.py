from fastapi.testclient import TestClient

from app.core.security import CSRF_COOKIE
from app.main import app

USERNAME = "owner"
PASSWORD = "correct-horse-1"
BASE_URL = "http://127.0.0.1:8765"


def make_client() -> TestClient:
    """A client that behaves like the bundled UI: fetches the CSRF cookie and echoes it in a header."""
    client = TestClient(app, base_url=BASE_URL)
    client.get("/api/auth/state")
    client.headers["X-CSRF-Token"] = client.cookies.get(CSRF_COOKIE)
    client.headers["X-BOMS-Client"] = "ui"
    return client


def login() -> TestClient:
    client = make_client()
    r = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return client
