import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import dbadmin
from app.modules.events import service as events
from tests.conftest import TEST_DB, superuser_conninfo

COLUMN = {"core.event": "action", "core.audit": "op"}


def _insert_event(db) -> int:
    event = events.record(db, "test", "1", "probe", {"x": 1}, "script")
    db.commit()
    return event.id


@pytest.mark.parametrize("table", ["core.event", "core.audit"])
@pytest.mark.parametrize("statement", ["UPDATE {t} SET {c} = {c} WHERE id = (SELECT max(id) FROM {t})",
                                       "DELETE FROM {t} WHERE id = (SELECT max(id) FROM {t})",
                                       "TRUNCATE {t}"])
def test_app_role_cannot_change_append_only_tables(db, table, statement):
    _insert_event(db)
    with pytest.raises(DBAPIError) as info:
        db.execute(text(statement.format(t=table, c=COLUMN[table])))
    assert isinstance(info.value.orig, psycopg.errors.InsufficientPrivilege)
    db.rollback()


@pytest.mark.parametrize("table", ["core.event", "core.audit"])
@pytest.mark.parametrize("statement", ["UPDATE {t} SET {c} = {c} WHERE id = (SELECT max(id) FROM {t})",
                                       "DELETE FROM {t} WHERE id = (SELECT max(id) FROM {t})",
                                       "TRUNCATE {t}"])
def test_trigger_rejects_change_even_for_superuser(db, table, statement):
    _insert_event(db)
    with dbadmin.superuser_conn(superuser_conninfo(), TEST_DB) as conn:
        with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
            conn.execute(statement.format(t=table, c=COLUMN[table]))


def test_app_role_has_no_update_delete_privilege(db):
    for table in ("core.event", "core.audit"):
        for priv in ("UPDATE", "DELETE", "TRUNCATE"):
            assert db.execute(text("SELECT has_table_privilege(:t, :p)"), {"t": table, "p": priv}).scalar() is False
        assert db.execute(text("SELECT has_table_privilege(:t, 'INSERT')"), {"t": table}).scalar() is True


def test_event_is_part_of_the_callers_transaction(db):
    before = db.execute(text("SELECT count(*) FROM core.event")).scalar()
    events.record(db, "test", "rollback", "probe", {}, "script")
    db.rollback()
    assert db.execute(text("SELECT count(*) FROM core.event")).scalar() == before


def test_invalid_source_rejected(db):
    with pytest.raises(ValueError):
        events.record(db, "test", "1", "probe", {}, "nope")


def test_audit_records_insert_update_delete(db):
    db.execute(text("INSERT INTO sys.setting (key, value) VALUES ('test.audit', '1')"))
    db.execute(text("UPDATE sys.setting SET value = '2' WHERE key = 'test.audit'"))
    db.execute(text("DELETE FROM sys.setting WHERE key = 'test.audit'"))
    db.commit()
    rows = db.execute(text(
        "SELECT op, before->'value', after->'value' FROM core.audit "
        "WHERE table_name = 'sys.setting' AND row_id = 'test.audit' ORDER BY id DESC LIMIT 3"
    )).all()
    assert [tuple(r) for r in reversed(rows)] == [("I", None, 1), ("U", 1, 2), ("D", 2, None)]


def test_audit_omits_password_hash(db):
    rows = db.execute(text(
        "SELECT after FROM core.audit WHERE table_name = 'sys.app_user' AND op = 'I'"
    )).scalars().all()
    assert rows and all("password_hash" not in r for r in rows)
    assert all("username" in r for r in rows)


def test_audit_trigger_on_every_mutable_sys_and_core_table(db):
    tables = set(db.execute(text(
        "SELECT schemaname || '.' || tablename FROM pg_tables "
        "WHERE schemaname IN ('sys', 'core') AND tablename NOT IN ('event', 'audit')"
    )).scalars())
    audited = set(db.execute(text(
        "SELECT c.relnamespace::regnamespace || '.' || c.relname FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid WHERE t.tgfoid = 'core.audit_row()'::regprocedure"
    )).scalars())
    assert tables and tables <= audited


def test_single_user_enforced(db):
    with pytest.raises(DBAPIError):
        db.execute(text("INSERT INTO sys.app_user (username, password_hash) VALUES ('second', 'x')"))
    db.rollback()


def test_updated_at_maintained(db):
    db.execute(text("INSERT INTO sys.setting (key, value, updated_at) VALUES ('test.ts', '1', '2000-01-01Z')"))
    db.commit()
    db.execute(text("UPDATE sys.setting SET value = '2' WHERE key = 'test.ts'"))
    db.commit()
    year = db.execute(text("SELECT extract(year FROM updated_at) FROM sys.setting WHERE key = 'test.ts'")).scalar()
    assert year > 2000
    db.execute(text("DELETE FROM sys.setting WHERE key = 'test.ts'"))
    db.commit()


def test_uuid_primary_keys_are_v7(db):
    value = db.execute(text("SELECT id FROM sys.app_user")).scalar()
    assert value.version == 7


def test_event_log_api(client):
    response = client.get("/api/events", params={"entity_type": "app_user", "action": "login"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1 and body["items"][0]["action"] == "login"
    facets = client.get("/api/events/facets").json()
    assert "app_user" in facets["entity_types"]
    assert client.get("/api/events", params={"from": "2000-01-01T00:00:00"}).status_code == 422
    ranged = client.get("/api/events", params={"from": "2000-01-01T00:00:00Z", "to": "2000-01-02T00:00:00Z"})
    assert ranged.json()["total"] == 0
