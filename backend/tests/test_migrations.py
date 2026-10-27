import os

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.cli import alembic_config
from app.core.config import get_config
from tests.conftest import create_empty_database, superuser_conninfo

MIGRATION_DB = "boms_test_migrations"


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_schema IN ('sys', 'core', 'ops', 'ref')"
        )).scalars().all()
    engine.dispose()
    return set(rows)


def _schema(url: str) -> set[str]:
    """Tables plus indexes and constraints: a migration that only changes those (0005) still differs."""
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT schemaname || '.' || indexname FROM pg_indexes WHERE schemaname IN ('sys', 'core', 'ops', 'ref') "
            "UNION SELECT 'constraint ' || conname FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
            "WHERE n.nspname IN ('sys', 'core', 'ops', 'ref')"
        )).scalars().all()
    engine.dispose()
    return _tables(url) | set(rows)


def test_upgrade_from_empty_then_downgrade_one_and_back():
    from app.core import dbadmin

    create_empty_database(MIGRATION_DB)
    url = get_config().db_url(MIGRATION_DB)
    cfg = alembic_config(url)
    try:
        command.upgrade(cfg, "head")
        at_head = _tables(url)
        schema_at_head = _schema(url)
        assert {"core.event", "core.audit", "sys.app_user", "sys.setting", "sys.country",
                "sys.currency", "sys.unit", "sys.job", "sys.backup_run"} <= at_head

        engine = create_engine(url)
        with engine.connect() as conn:
            schemas = set(conn.execute(text("SELECT nspname FROM pg_namespace")).scalars())
        engine.dispose()
        assert {"sys", "ref", "core", "outreach", "tender", "ops", "fin", "compliance", "analytics"} <= schemas

        script = ScriptDirectory.from_config(cfg)
        head = script.get_current_head()
        command.downgrade(cfg, "-1")
        assert _schema(url) != schema_at_head
        command.upgrade(cfg, "head")
        assert _tables(url) == at_head
        assert _schema(url) == schema_at_head

        engine = create_engine(url)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == head
        engine.dispose()
    finally:
        dbadmin.drop_database(superuser_conninfo(), MIGRATION_DB)


def test_app_role_is_not_superuser():
    from app.core import dbadmin

    with dbadmin.superuser_conn(superuser_conninfo()) as conn:
        row = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (os.environ["BOMS_DB_USER"],)).fetchone()
    assert row == (False,)


def test_launcher_applies_install_config(tmp_path, monkeypatch):
    import json

    from app import launch

    for env in launch.CONFIG_KEYS.values():
        monkeypatch.delenv(env, raising=False)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"data_dir": "D:\\BOMS-Data", "db_name": "boms", "http_port": 8765, "pg_bin": ""}),
                    encoding="utf-8-sig")
    launch.apply_config(path)
    assert os.environ["BOMS_DATA_DIR"] == "D:\\BOMS-Data" and os.environ["BOMS_HTTP_PORT"] == "8765"
    assert "BOMS_PG_BIN" not in os.environ
