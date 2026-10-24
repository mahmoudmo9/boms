"""Test fixtures: a throw-away database boms_test_<pid> owned by role boms_test_app.

The superuser connection uses libpq's normal password sources (PGPASSWORD or
pgpass.conf); set BOMS_PG_SUPERUSER to use a superuser other than "postgres".
Secrets for the test role are random per run and live only in os.environ.
"""

import os
import secrets
import shutil
import tempfile
from pathlib import Path

import pytest

TEST_DB = f"boms_test_{os.getpid()}"
TEST_ROLE = "boms_test_app"
SUPERUSER = os.environ.get("BOMS_PG_SUPERUSER", "postgres")

_data_dir = Path(tempfile.mkdtemp(prefix="boms_test_data_"))
os.environ.update(
    {
        "BOMS_DB_NAME": TEST_DB,
        "BOMS_DB_USER": TEST_ROLE,
        "BOMS_DB_PASSWORD": secrets.token_urlsafe(24),
        "BOMS_SESSION_KEY": secrets.token_urlsafe(32),
        "BOMS_DATA_DIR": str(_data_dir),
        "BOMS_CONFIG": str(_data_dir / "none.toml"),
    }
)

from app.core import dbadmin  # noqa: E402
from app.core.config import get_config  # noqa: E402


def migrate(dbname: str, revision: str = "head", downgrade: bool = False) -> None:
    from alembic import command
    from sqlalchemy import create_engine

    from app.cli import alembic_config
    from app.core.db import app_db_url

    engine = create_engine(app_db_url(dbname))
    with engine.begin() as conn:
        cfg = alembic_config()
        cfg.attributes["connection"] = conn
        (command.downgrade if downgrade else command.upgrade)(cfg, revision)
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database():
    cfg = get_config()
    with dbadmin.superuser_connect(SUPERUSER) as conn:
        dbadmin.drop_database(conn, TEST_DB)
        dbadmin.ensure_role(conn, TEST_ROLE, os.environ["BOMS_DB_PASSWORD"])
        dbadmin.create_database(conn, TEST_DB, TEST_ROLE)
    migrate(cfg.db_name)
    yield cfg
    from app.core.db import get_engine

    get_engine().dispose()
    with dbadmin.superuser_connect(SUPERUSER) as conn:
        dbadmin.drop_database(conn, TEST_DB)
    shutil.rmtree(_data_dir, ignore_errors=True)


@pytest.fixture
def db():
    from app.core.db import new_session

    with new_session() as session:
        yield session
        session.rollback()


@pytest.fixture
def superuser_db():
    """psycopg connection to the test DB as superuser (bypasses privileges, not triggers)."""
    with dbadmin.superuser_connect(SUPERUSER, dbname=TEST_DB) as conn:
        yield conn


@pytest.fixture(scope="session")
def user(test_database):
    """The single app user (created once; the table allows only one row)."""
    from app.core.db import new_session
    from app.modules.system import users
    from tests.helpers import PASSWORD, USERNAME

    with new_session() as session:
        existing = users.get_user(session)
        if existing is None:
            existing = users.create_user(session, USERNAME, PASSWORD, source="script")
            session.commit()
        return existing
