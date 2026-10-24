"""Migrations: empty database -> head, downgrade one step and back up again."""

import os

from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.cli import alembic_config
from app.core import dbadmin
from app.core.db import app_db_url
from tests.conftest import SUPERUSER, TEST_ROLE, migrate

MIG_DB = f"boms_test_mig_{os.getpid()}"


def _current(dbname: str) -> str | None:
    engine = create_engine(app_db_url(dbname))
    with engine.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    engine.dispose()
    return rev


def test_empty_to_head_and_one_step_down_and_back():
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with dbadmin.superuser_connect(SUPERUSER) as conn:
        dbadmin.drop_database(conn, MIG_DB)
        dbadmin.create_database(conn, MIG_DB, TEST_ROLE)
    try:
        migrate(MIG_DB)
        assert _current(MIG_DB) == head
        migrate(MIG_DB, "-1", downgrade=True)
        assert _current(MIG_DB) != head
        migrate(MIG_DB)
        assert _current(MIG_DB) == head
        # Full downgrade to base also works, then back to head.
        migrate(MIG_DB, "base", downgrade=True)
        migrate(MIG_DB)
        assert _current(MIG_DB) == head
    finally:
        with dbadmin.superuser_connect(SUPERUSER) as conn:
            dbadmin.drop_database(conn, MIG_DB)


def test_all_schemas_exist(db):
    names = set(db.scalars(text("SELECT nspname FROM pg_namespace")))
    assert {"sys", "ref", "core", "outreach", "tender", "ops", "fin", "compliance", "analytics"} <= names


def test_app_role_is_not_superuser_and_owns_schemas(db):
    row = db.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).one()
    assert row.rolsuper is False
    owners = set(db.scalars(text(
        "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname IN ('sys','core','ref','fin')"
    )))
    assert owners == {TEST_ROLE}


def test_uuidv7_primary_keys(db):
    db.execute(text("INSERT INTO sys.job (type) VALUES ('test.noop')"))
    job_id = db.execute(text("SELECT id FROM sys.job WHERE type = 'test.noop' LIMIT 1")).scalar()
    assert job_id.version == 7
