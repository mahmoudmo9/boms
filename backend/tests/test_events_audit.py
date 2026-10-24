"""core.event / core.audit are append-only; the audit trigger records I/U/D."""

import psycopg
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from app.modules.events import service as events
from app.modules.events.models import Audit
from app.modules.system import basedata


# A harmless no-op assignment per table (identity "id" columns cannot be assigned at all).
NOOP_SET = {"core.event": "actor = actor", "core.audit": "table_name = table_name"}


@pytest.mark.parametrize("table", ["core.event", "core.audit"])
@pytest.mark.parametrize("stmt", ["UPDATE {t} SET {set}", "DELETE FROM {t}", "TRUNCATE {t}"])
def test_app_role_cannot_modify(db, table, stmt):
    events.record(db, "test", "1", "test.created", source="api")
    db.commit()
    sql = stmt.format(t=table, set=NOOP_SET[table])
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(text(sql))
    db.rollback()


@pytest.mark.parametrize("table", ["core.event", "core.audit"])
def test_trigger_rejects_even_superuser(superuser_db, table):
    """Privileges are bypassed by the superuser, but the trigger still refuses."""
    superuser_db.execute(
        "INSERT INTO core.event (actor, entity_type, entity_id, action, source) VALUES ('t','t','1','t','script')"
    )
    for stmt in (f"UPDATE {table} SET {NOOP_SET[table]}", f"DELETE FROM {table}", f"TRUNCATE {table}"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="append-only"):
            superuser_db.execute(stmt)


def test_record_event_in_same_transaction(db):
    before = db.scalar(text("SELECT count(*) FROM core.event WHERE entity_type = 'tx_test'"))
    events.record(db, "tx_test", "x", "tx_test.created", {"a": 1}, source="api")
    db.rollback()
    after = db.scalar(text("SELECT count(*) FROM core.event WHERE entity_type = 'tx_test'"))
    assert after == before


def test_audit_records_insert_update_delete(db):
    db.execute(text("INSERT INTO sys.setting (key, value) VALUES ('test.audit', '1'::jsonb)"))
    db.execute(text("UPDATE sys.setting SET value = '2'::jsonb WHERE key = 'test.audit'"))
    db.execute(text("DELETE FROM sys.setting WHERE key = 'test.audit'"))
    rows = db.scalars(
        select(Audit).where(Audit.table_name == "sys.setting", Audit.row_id == "test.audit").order_by(Audit.id)
    ).all()
    assert [r.op for r in rows] == ["I", "U", "D"]
    assert rows[0].before is None and rows[0].after["value"] == 1
    assert rows[1].before["value"] == 1 and rows[1].after["value"] == 2
    assert rows[2].before["value"] == 2 and rows[2].after is None


def test_every_mutable_table_is_audited(db):
    tables = set(db.scalars(text(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables "
        "WHERE table_schema IN ('sys','core') AND table_type = 'BASE TABLE' "
        "AND table_name NOT IN ('event', 'audit')"
    )))
    audited = set(db.scalars(text(
        "SELECT n.nspname || '.' || c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_proc p ON p.oid = t.tgfoid "
        "WHERE p.proname = 'audit_row'"
    )))
    assert tables and tables <= audited


def test_service_change_records_event_and_audit(db):
    basedata.update_item(db, "currencies", "USD", {"symbol": "US$"}, source="api")
    ev = db.execute(text(
        "SELECT action, data FROM core.event WHERE entity_type='currency' AND entity_id='USD' ORDER BY id DESC LIMIT 1"
    )).one()
    assert ev.action == "currency.updated"
    assert ev.data["symbol"] == {"from": "$", "to": "US$"}
    au = db.execute(text(
        "SELECT op, before->>'symbol' b, after->>'symbol' a FROM core.audit "
        "WHERE table_name='sys.currency' AND row_id='USD' ORDER BY id DESC LIMIT 1"
    )).one()
    assert (au.op, au.b, au.a) == ("U", "$", "US$")
    db.rollback()


def test_deactivate_records_specific_action(db):
    basedata.update_item(db, "countries", "AQ", {"active": False}, source="api")
    action = db.scalar(text("SELECT action FROM core.event WHERE entity_id='AQ' ORDER BY id DESC LIMIT 1"))
    assert action == "country.deactivated"
    db.rollback()


def test_list_events_filters_and_paging(db):
    for i in range(5):
        events.record(db, "paging_test", str(i), "paging_test.created", source="api")
    items, total = events.list_events(db, entity_type="paging_test", page=1, page_size=2)
    assert total == 5 and len(items) == 2
    assert items[0].entity_id == "4"  # newest first
    items, _ = events.list_events(db, entity_type="paging_test", page=3, page_size=2)
    assert [e.entity_id for e in items] == ["0"]
    db.rollback()
