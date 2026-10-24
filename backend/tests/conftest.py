"""Test setup: a fresh ``boms_test`` database owned by role ``boms_test_app``.

Superuser connection for creating it comes from BOMS_TEST_PG_SUPERUSER /
BOMS_TEST_PG_SUPERUSER_PASSWORD / BOMS_TEST_PG_HOST / BOMS_TEST_PG_PORT
(defaults: postgres / postgres / 127.0.0.1 / 5432).
"""

import os
import secrets
import tempfile
from pathlib import Path

import pytest

TEST_DB = "boms_test"
TEST_ROLE = "boms_test_app"
TEST_PASSWORD = "correct-horse-battery"
DATA_DIR = Path(tempfile.mkdtemp(prefix="boms_test_data_"))

os.environ.update(
    BOMS_DB_NAME=TEST_DB,
    BOMS_DB_USER=TEST_ROLE,
    BOMS_DB_HOST=os.environ.get("BOMS_TEST_PG_HOST", "127.0.0.1"),
    BOMS_DB_PORT=os.environ.get("BOMS_TEST_PG_PORT", "5432"),
    BOMS_DB_PASSWORD=secrets.token_urlsafe(16),
    BOMS_SESSION_KEY=secrets.token_urlsafe(32),
    BOMS_DATA_DIR=str(DATA_DIR),
    BOMS_HTTP_PORT="8765",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.core import dbadmin  # noqa: E402
from app.core.db import new_session, reset_engine  # noqa: E402
from app.core.security import CSRF_COOKIE, login_limiter  # noqa: E402


def superuser_conninfo() -> dict:
    return {
        "host": os.environ["BOMS_DB_HOST"],
        "port": int(os.environ["BOMS_DB_PORT"]),
        "user": os.environ.get("BOMS_TEST_PG_SUPERUSER", "postgres"),
        "password": os.environ.get("BOMS_TEST_PG_SUPERUSER_PASSWORD", "postgres"),
    }


def create_empty_database(name: str) -> None:
    conninfo = superuser_conninfo()
    dbadmin.drop_database(conninfo, name)
    dbadmin.ensure_role(conninfo, TEST_ROLE, os.environ["BOMS_DB_PASSWORD"])
    dbadmin.create_database(conninfo, name, TEST_ROLE)


@pytest.fixture(scope="session", autouse=True)
def database():
    from alembic import command

    from app.cli import alembic_config
    from app.modules.system import users
    from app.modules.system.seed import seed_base_data

    reset_engine()
    create_empty_database(TEST_DB)
    command.upgrade(alembic_config(), "head")
    with new_session() as db:
        seed_base_data(db)
        users.create_user(db, "admin", TEST_PASSWORD, language="en")
        db.commit()
    yield
    reset_engine()


@pytest.fixture
def db():
    with new_session() as session:
        yield session
        session.rollback()


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    login_limiter.reset()
    yield
    login_limiter.reset()


class ApiClient(TestClient):
    """TestClient that sends the CSRF double-submit header automatically."""

    def request(self, method, url, **kwargs):
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            token = self.cookies.get(CSRF_COOKIE)
            if token is None:
                super().request("GET", "/api/health")
                token = self.cookies.get(CSRF_COOKIE)
            headers = dict(kwargs.pop("headers", None) or {})
            headers.setdefault("X-CSRF-Token", token)
            kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


@pytest.fixture
def anon_client():
    from app.main import app

    with ApiClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


@pytest.fixture
def client(anon_client):
    response = anon_client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return anon_client
