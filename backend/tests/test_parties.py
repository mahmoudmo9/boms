"""Phase 3: trading parties, contacts, interactions, follow-ups, command center."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from alembic import command
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

from app.cli import alembic_config
from app.core import dbadmin
from app.core.config import get_config
from app.modules.parties import clock
from app.modules.parties.models import Contact, ContactMethod, Party
from app.modules.parties.normalize import normalize_method
from tests.conftest import TEST_DB, create_empty_database, superuser_conninfo, unique_bytes, upload

TEHRAN = ZoneInfo("Asia/Tehran")


def tag() -> str:
    return os.urandom(3).hex()


def make_party(client, name_fa=None, name_en=None, roles=(), confirm=True, **extra):
    body = {"name_fa": name_fa, "name_en": name_en or f"Party {tag()}", "roles": list(roles),
            "confirm_duplicate": confirm, **extra}
    r = client.post("/api/parties", json=body)
    assert r.status_code == 201, r.text
    return r.json()["party"]


def log(client, party_id, **kwargs):
    body = {"party_id": party_id, "channel": "whatsapp", "direction": "in", **kwargs}
    return client.post("/api/interactions", json=body)


def tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


# ---- migration ------------------------------------------------------------------------

def test_migration_0004_up_down_up():
    db_name = "boms_test_parties_migration"
    create_empty_database(db_name)
    url = get_config().db_url(db_name)
    cfg = alembic_config(url)

    def tables():
        engine = create_engine(url)
        with engine.connect() as conn:
            names = set(conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'core'")).scalars())
            stages = conn.execute(text(
                "SELECT count(*) FROM core.funnel_stage")).scalar() if "funnel_stage" in names else None
        engine.dispose()
        return names, stages

    new = {"party", "party_role", "funnel_stage", "contact", "contact_method", "interaction", "followup"}
    try:
        command.upgrade(cfg, "head")
        names, stages = tables()
        assert new <= names and stages == 8 + 7 + 4 * 2
        command.downgrade(cfg, "0003")
        names, _ = tables()
        assert not (new & names) and "document" in names
        command.upgrade(cfg, "head")
        names, stages = tables()
        assert new <= names and stages == 23
    finally:
        dbadmin.drop_database(superuser_conninfo(), db_name)


# ---- parties, roles, stages --------------------------------------------------------------

def test_create_party_with_roles_and_default_stages(client):
    party = make_party(client, name_fa="شرکت آزمایش", roles=["buyer", "supplier", "forwarder"])
    stages = {r["role"]: r["stage"] for r in party["roles"]}
    assert stages == {"buyer": "new_lead", "supplier": "identified", "forwarder": "active"}


def test_stage_vocabulary_enforced(client, db):
    party = make_party(client, roles=["buyer"])
    r = client.post(f"/api/parties/{party['id']}/roles/buyer/stage", json={"stage": "identified"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_stage"
    r = client.post(f"/api/parties/{party['id']}/roles", json={"role": "forwarder", "stage": "quoted"})
    assert r.status_code == 422
    with pytest.raises(DBAPIError) as info:
        db.execute(text("UPDATE core.party_role SET stage = 'blacklisted' WHERE party_id = :p AND role = 'buyer'"),
                   {"p": party["id"]})
    assert isinstance(info.value.orig, psycopg.errors.ForeignKeyViolation)
    db.rollback()


def test_unique_role_per_party(client, db):
    party = make_party(client, roles=["buyer"])
    r = client.post(f"/api/parties/{party['id']}/roles", json={"role": "buyer"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_role"
    with pytest.raises(DBAPIError):
        db.execute(text("INSERT INTO core.party_role (party_id, role, stage) VALUES (:p, 'buyer', 'won')"),
                   {"p": party["id"]})
    db.rollback()
    assert client.post(f"/api/parties/{party['id']}/roles", json={"role": "agent"}).status_code == 201
    assert client.delete(f"/api/parties/{party['id']}/roles/agent").status_code == 204


def test_stage_change_event_has_old_and_new(client):
    party = make_party(client, roles=["supplier"])
    r = client.post(f"/api/parties/{party['id']}/roles/supplier/stage",
                    json={"stage": "qualified", "reason": "samples ok"})
    assert r.status_code == 200 and r.json()["stage"] == "qualified"
    events = client.get("/api/events", params={"entity_type": "party", "entity_id": party["id"],
                                               "action": "stage_change"}).json()["items"]
    assert events[0]["data"] == {"role": "supplier", "old_stage": "identified", "new_stage": "qualified",
                                 "reason": "samples ok"}


def test_name_required(client):
    r = client.post("/api/parties", json={"name_fa": "  ", "name_en": ""})
    assert r.status_code == 422


def test_do_not_contact_requires_reason(client, db):
    party = make_party(client)
    r = client.patch(f"/api/parties/{party['id']}", json={"do_not_contact": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "dnc_reason_required"
    r = client.patch(f"/api/parties/{party['id']}", json={"do_not_contact": True, "do_not_contact_reason": "asked"})
    assert r.status_code == 200 and r.json()["do_not_contact"] is True
    with pytest.raises(DBAPIError) as info:
        db.execute(text("UPDATE core.party SET do_not_contact_reason = NULL WHERE id = :p"), {"p": party["id"]})
    assert isinstance(info.value.orig, psycopg.errors.CheckViolation)
    db.rollback()
    r = client.patch(f"/api/parties/{party['id']}", json={"do_not_contact": False})
    assert r.json()["do_not_contact"] is False and r.json()["do_not_contact_reason"] is None


def test_archive_and_unarchive(client):
    party = make_party(client)
    assert client.post(f"/api/parties/{party['id']}/archive").json()["status"] == "archived"
    active_ids = [p["id"] for p in client.get("/api/parties", params={"page_size": 200}).json()["items"]]
    assert party["id"] not in active_ids
    assert client.post(f"/api/parties/{party['id']}/unarchive").json()["status"] == "active"
    assert client.delete(f"/api/parties/{party['id']}").status_code == 405


def test_duplicate_party_warning_and_confirm(client, db):
    name = f"Pars Hydraulic Pumps {tag()}"
    first = make_party(client, name_en=name)
    before = db.scalar(select(func.count()).select_from(Party))
    r = client.post("/api/parties", json={"name_en": name.replace("Pumps", "Pump")})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is False
    assert first["id"] in [d["id"] for d in body["possible_duplicates"]]
    assert db.scalar(select(func.count()).select_from(Party)) == before  # nothing persisted
    r = client.post("/api/parties", json={"name_en": name.replace("Pumps", "Pump"), "confirm_duplicate": True})
    assert r.status_code == 201 and r.json()["created"] is True
    live = client.get("/api/parties/duplicates", params={"name_en": name}).json()["possible_duplicates"]
    assert len(live) >= 2


# ---- contacts and methods ----------------------------------------------------------------

@pytest.mark.parametrize("variant", ["+98 912 {x}", "0098-912-{x}", "۰۹۱۲{xf}", "(0912) {x}"])
def test_identical_phone_collides_in_all_formats(client, db, variant):
    x = f"{uuid.uuid4().int % 10**7:07d}"
    party = make_party(client)
    r = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "Ali",
                                           "methods": [{"type": "phone", "value": f"0912{x}"}]})
    assert r.status_code == 201, r.text
    other = make_party(client)
    contacts_before = db.scalar(select(func.count()).select_from(Contact))
    xf = x.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    r = client.post("/api/contacts", json={"party_id": other["id"], "name_en": "Reza",
                                           "methods": [{"type": "phone", "value": variant.format(x=x, xf=xf)}]})
    assert r.status_code == 409, r.text
    error = r.json()["error"]
    assert error["code"] == "duplicate_contact_method" and error["details"]["party_id"] == party["id"]
    assert db.scalar(select(func.count()).select_from(Contact)) == contacts_before  # contact not persisted


def test_phone_normalization():
    assert {normalize_method("phone", v) for v in
            ["09123456789", "+98 912 345 6789", "0098 912 345 6789", "۰۹۱۲۳۴۵۶۷۸۹", "٠٩١٢٣٤٥٦٧٨٩"]} == {"989123456789"}
    assert normalize_method("whatsapp", "+971 50 123 4567") == "971501234567"
    assert normalize_method("email", " Ali@Example.COM ") == "ali@example.com"
    assert normalize_method("telegram", "@Some_User") == "some_user"


def test_email_duplicate_on_method_add_and_update(client, db):
    email = f"sales{tag()}@example.com"
    party = make_party(client)
    c1 = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "A",
                                            "methods": [{"type": "email", "value": email}]}).json()
    c2 = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "B"}).json()
    before = db.scalar(select(func.count()).select_from(ContactMethod))
    r = client.post(f"/api/contacts/{c2['id']}/methods", json={"type": "email", "value": email.upper()})
    assert r.status_code == 409
    assert db.scalar(select(func.count()).select_from(ContactMethod)) == before
    m2 = client.post(f"/api/contacts/{c2['id']}/methods", json={"type": "email", "value": f"x{email}"}).json()
    r = client.patch(f"/api/contacts/methods/{m2['id']}", json={"value": email})
    assert r.status_code == 409
    # the same number as phone and as whatsapp is allowed (different type)
    number = f"+44 7{uuid.uuid4().int % 10**9:09d}"
    assert client.post(f"/api/contacts/{c1['id']}/methods", json={"type": "phone", "value": number}).status_code == 201
    r = client.post(f"/api/contacts/{c1['id']}/methods", json={"type": "whatsapp", "value": number})
    assert r.status_code == 201


def test_contact_archive_and_primary(client):
    party = make_party(client)
    a = client.post("/api/contacts", json={"party_id": party["id"], "name_fa": "علی", "is_primary": True}).json()
    b = client.post("/api/contacts", json={"party_id": party["id"], "name_fa": "رضا", "is_primary": True}).json()
    contacts = {c["id"]: c for c in client.get("/api/contacts", params={"party_id": party["id"]}).json()}
    assert contacts[b["id"]]["is_primary"] and not contacts[a["id"]]["is_primary"]
    assert client.post(f"/api/contacts/{b['id']}/archive").json()["status"] == "archived"
    m = client.post(f"/api/contacts/{a['id']}/methods", json={"type": "telegram", "value": f"@u{tag()}"}).json()
    assert client.post(f"/api/contacts/methods/{m['id']}/archive").json()["status"] == "archived"
    assert client.delete(f"/api/contacts/{a['id']}").status_code == 405


# ---- interactions and the mandatory next action -------------------------------------------

def test_interaction_next_action_rule(client, db):
    party = make_party(client, roles=["buyer"])
    count = lambda: db.execute(text("SELECT count(*) FROM core.interaction WHERE party_id = :p"),  # noqa: E731
                               {"p": party["id"]}).scalar()
    r = log(client, party["id"], body="سلام")
    assert r.status_code == 422 and r.json()["error"]["code"] == "next_action_required"
    r = log(client, party["id"], body="x", followup={"action": "call", "due_on": tomorrow()},
            no_followup_reason="none")
    assert r.status_code == 422 and r.json()["error"]["code"] == "next_action_conflict"
    assert count() == 0
    r = log(client, party["id"], body="only reason", no_followup_reason="just a thank-you note")
    assert r.status_code == 201 and r.json()["followups"] == []
    r = log(client, party["id"], body="with follow-up", followup={"action": "Send price list", "due_on": tomorrow()})
    assert r.status_code == 201 and r.json()["followups"][0]["action"] == "Send price list"
    assert count() == 2


def test_next_action_rule_backstop_in_database(client):
    """A direct insert without follow-up or reason is rejected at commit by the deferred trigger."""
    party = make_party(client)
    with dbadmin.superuser_conn(superuser_conninfo(), TEST_DB) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("INSERT INTO core.interaction (party_id, channel, direction, occurred_at) "
                             "VALUES (%s, 'call', 'out', now())", (party["id"],))


def test_interaction_is_immutable_except_subject_and_body(client, db):
    party = make_party(client)
    row = log(client, party["id"], subject="Price", body="original text",
              no_followup_reason="info only").json()
    r = client.patch(f"/api/interactions/{row['id']}", json={"body": "corrected text"})
    assert r.status_code == 200 and r.json()["body"] == "corrected text"
    ev = client.get("/api/events", params={"entity_type": "interaction", "entity_id": row["id"],
                                           "action": "correct"}).json()["items"][0]
    assert ev["data"] == {"before": {"body": "original text"}, "after": {"body": "corrected text"}}
    assert client.patch(f"/api/interactions/{row['id']}", json={"channel": "call"}).status_code == 422
    with pytest.raises(DBAPIError) as info:
        db.execute(text("UPDATE core.interaction SET channel = 'call' WHERE id = :i"), {"i": row["id"]})
    assert isinstance(info.value.orig, psycopg.errors.RestrictViolation)
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM core.interaction WHERE id = :i"), {"i": row["id"]})
    db.rollback()


def test_interaction_can_move_stage_in_same_transaction(client):
    party = make_party(client, roles=["buyer"])
    r = log(client, party["id"], body="they asked for a quote", no_followup_reason="quote follows",
            move_stage={"role": "buyer", "stage": "inquiry_received"})
    assert r.status_code == 201
    roles = client.get(f"/api/parties/{party['id']}").json()["roles"]
    assert roles[0]["stage"] == "inquiry_received"
    # invalid move rolls back the whole interaction
    r = log(client, party["id"], body="bad", no_followup_reason="x", move_stage={"role": "buyer", "stage": "nope"})
    assert r.status_code == 422
    assert len(client.get("/api/interactions", params={"party_id": party["id"]}).json()["items"]) == 1


def test_contact_must_belong_to_party(client):
    p1, p2 = make_party(client), make_party(client)
    c = client.post("/api/contacts", json={"party_id": p1["id"], "name_en": "X"}).json()
    r = log(client, p2["id"], contact_id=c["id"], no_followup_reason="x")
    assert r.status_code == 422 and r.json()["error"]["code"] == "contact_not_of_party"


def test_attachments_link_and_unlink_through_document_link(client, db):
    party = make_party(client)
    doc = upload(client, "invoice.txt", unique_bytes("attach")).json()
    row = log(client, party["id"], body="see attached", no_followup_reason="fyi", document_ids=[doc["id"]]).json()
    assert row["documents"][0]["document_id"] == doc["id"]
    link_row = db.execute(text("SELECT entity_type, entity_id FROM core.document_link WHERE document_id = :d"),
                          {"d": doc["id"]}).one()
    assert tuple(link_row) == ("interaction", row["id"])
    party_docs = client.get(f"/api/parties/{party['id']}/documents").json()
    assert [d["document_id"] for d in party_docs] == [doc["id"]]
    link_id = row["documents"][0]["link_id"]
    assert client.delete(f"/api/interactions/{row['id']}/documents/{link_id}").status_code == 204
    assert client.get(f"/api/interactions/{row['id']}").json()["documents"] == []
    assert client.post(f"/api/interactions/{row['id']}/documents", json={"document_id": doc["id"]}).status_code == 201
    doc2 = upload(client, "party.txt", unique_bytes("party doc")).json()
    r = client.post(f"/api/parties/{party['id']}/documents", json={"document_id": doc2["id"]})
    assert r.status_code == 201
    assert len(client.get(f"/api/parties/{party['id']}/documents").json()) == 2


# ---- follow-ups ----------------------------------------------------------------------------

def test_followup_done_with_next_reschedule_and_cancel(client):
    party = make_party(client)
    f = client.post("/api/followups", json={"party_id": party["id"], "action": "Call back",
                                            "due_on": tomorrow()}).json()
    later = (date.today() + timedelta(days=5)).isoformat()
    r = client.post(f"/api/followups/{f['id']}/reschedule", json={"due_on": later})
    assert r.status_code == 200 and r.json()["due_on"] == later
    ev = client.get("/api/events", params={"entity_type": "followup", "entity_id": f["id"],
                                           "action": "reschedule"}).json()["items"][0]
    assert ev["data"]["old_due_on"] == tomorrow() and ev["data"]["new_due_on"] == later
    r = client.post(f"/api/followups/{f['id']}/done",
                    json={"note": "talked", "next": {"action": "Send offer", "due_on": later}})
    body = r.json()
    assert r.status_code == 200 and body["followup"]["status"] == "done" and body["next"]["action"] == "Send offer"
    assert client.post(f"/api/followups/{f['id']}/done", json={}).status_code == 409
    assert client.post(f"/api/followups/{body['next']['id']}/cancel", json={"note": ""}).status_code == 422
    r = client.post(f"/api/followups/{body['next']['id']}/cancel", json={"note": "deal off"})
    assert r.json()["status"] == "cancelled" and r.json()["done_note"] == "deal off"


# ---- command center ----------------------------------------------------------------------

def _pin_clock(monkeypatch, utc: datetime):
    monkeypatch.setattr(clock, "now", lambda: utc)
    monkeypatch.setattr(clock, "local_tz", lambda: TEHRAN)


def test_command_center_buckets_around_local_midnight(client, monkeypatch):
    party = make_party(client)
    ids = {}
    for name, due in {"yesterday": "2026-10-24", "today": "2026-10-25", "tomorrow": "2026-10-26",
                      "week": "2026-11-01", "later": "2026-11-02"}.items():
        ids[name] = client.post("/api/followups", json={"party_id": party["id"], "action": name,
                                                        "due_on": due}).json()["id"]

    def buckets():
        cc = client.get("/api/command-center").json()
        return {b: [f["action"] for f in cc[b] if f["party_id"] == party["id"]]
                for b in ("overdue", "today", "upcoming_7_days")}, cc

    # 23:59 on 25 Oct in Tehran is still 20:29 UTC on 25 Oct
    _pin_clock(monkeypatch, datetime(2026, 10, 25, 20, 29, tzinfo=UTC))
    b, cc = buckets()
    assert cc["today_date"] == "2026-10-25"
    assert b == {"overdue": ["yesterday"], "today": ["today"], "upcoming_7_days": ["tomorrow", "week"]}
    # 00:01 on 26 Oct in Tehran is 20:31 UTC on 25 Oct: the UTC date has not changed, the local one has
    _pin_clock(monkeypatch, datetime(2026, 10, 25, 20, 31, tzinfo=UTC))
    b, cc = buckets()
    assert cc["today_date"] == "2026-10-26"
    assert b == {"overdue": ["yesterday", "today"], "today": ["tomorrow"], "upcoming_7_days": ["week", "later"]}
    assert cc["overdue_count"] >= 2


def test_stale_leads_respect_setting(client, monkeypatch):
    now = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    _pin_clock(monkeypatch, now)
    lead = make_party(client, roles=["buyer"])
    won = make_party(client, roles=["buyer"])
    client.post(f"/api/parties/{won['id']}/roles/buyer/stage", json={"stage": "won"})
    for p in (lead, won):
        r = log(client, p["id"], body="old", no_followup_reason="x",
                occurred_at=(now - timedelta(days=10)).isoformat())
        assert r.status_code == 201

    def stale_ids():
        return {s["party_id"] for s in client.get("/api/command-center").json()["stale_leads"]}

    assert lead["id"] not in stale_ids()  # default 14 days
    client.patch("/api/settings", json={"parties.stale_lead_days": 7})
    try:
        ids = stale_ids()
        assert lead["id"] in ids and won["id"] not in ids  # won is not a stale-able stage
        log(client, lead["id"], body="new", no_followup_reason="x", occurred_at=(now - timedelta(days=1)).isoformat())
        assert lead["id"] not in stale_ids()
    finally:
        client.patch("/api/settings", json={"parties.stale_lead_days": 14})


def test_funnel_counts_and_board(client):
    party = make_party(client, name_fa=f"تامین‌کننده {tag()}", roles=["supplier"])
    cc = client.get("/api/command-center").json()
    assert set(cc["funnel_counts"]["supplier"]) == {"identified", "contacted", "responded", "qualified", "in_use",
                                                    "blacklisted", "dormant"}
    assert cc["funnel_counts"]["supplier"]["identified"] >= 1
    board = client.get("/api/parties/funnel/supplier").json()
    first = board["stages"][0]
    assert first["code"] == "identified" and party["id"] in [c["party_id"] for c in first["cards"]]


# ---- search ---------------------------------------------------------------------------------

def test_persian_search_with_arabic_yeh_kaf(client):
    t = tag()
    party = make_party(client, name_fa=f"بازرگانی کیمیا پارس {t}")
    contact = client.post("/api/contacts", json={"party_id": party["id"], "name_fa": f"مهندس یکتا {t}"}).json()
    log(client, party["id"], body=f"درخواست کاتالوگ لوله‌های فولادی {t}", no_followup_reason="x")

    def ids(q, kind):
        groups = client.get("/api/search", params={"q": q}).json()["groups"]
        return [i["id"] for g in groups if g["type"] == kind for i in g["items"]]

    assert party["id"] in ids(f"كيميا {t}", "party")
    assert contact["id"] in ids(f"يكتا {t}", "contact")
    assert any(ids(f"كاتالوگ {t}", "interaction"))
    listed = client.get("/api/parties", params={"q": "كيميا پارس"}).json()["items"]
    assert party["id"] in [p["id"] for p in listed]
    found = client.get("/api/interactions", params={"q": f"كاتالوگ {t}"}).json()["items"]
    assert len(found) == 1


def test_search_contact_by_phone_digits(client):
    x = f"{uuid.uuid4().int % 10000:04d}"
    party = make_party(client)
    c = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "Phone Person",
                                           "methods": [{"type": "whatsapp", "value": f"+98 935 111 {x}"}]}).json()
    groups = client.get("/api/search", params={"q": f"935111{x}"}).json()["groups"]
    assert c["id"] in [i["id"] for g in groups if g["type"] == "contact" for i in g["items"]]


# ---- cross-cutting -----------------------------------------------------------------------

def test_audit_rows_for_all_new_tables(client, db):
    party = make_party(client, roles=["buyer"])
    c = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "Audit",
                                           "methods": [{"type": "telegram", "value": f"@audit{tag()}"}]}).json()
    log(client, party["id"], body="audit", followup={"action": "a", "due_on": tomorrow()})
    tables = db.execute(text(
        "SELECT DISTINCT table_name FROM core.audit WHERE table_name IN ('core.party', 'core.party_role', "
        "'core.contact', 'core.contact_method', 'core.interaction', 'core.followup', 'core.funnel_stage')"
    )).scalars().all()
    assert set(tables) == {"core.party", "core.party_role", "core.contact", "core.contact_method",
                           "core.interaction", "core.followup", "core.funnel_stage"}
    body_audit = db.execute(text("SELECT after FROM core.audit WHERE table_name = 'core.interaction' "
                                 "ORDER BY id DESC LIMIT 1")).scalar()
    assert "body" in body_audit and "body_norm" not in body_audit
    assert c["methods"][0]["value_norm"].startswith("audit")


def test_every_write_records_an_event(client):
    party = make_party(client)
    actions = {e["action"] for e in client.get("/api/events", params={"entity_type": "party",
                                                                     "entity_id": party["id"]}).json()["items"]}
    assert "create" in actions


@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/parties", {"name_en": "x", "bogus": 1}),
    ("patch", "/api/parties/{party}", {"bogus": 1}),
    ("post", "/api/parties/{party}/roles", {"role": "agent", "bogus": 1}),
    ("post", "/api/parties/{party}/roles/buyer/stage", {"stage": "won", "bogus": 1}),
    ("post", "/api/parties/{party}/documents", {"document_id": str(uuid.uuid4()), "bogus": 1}),
    ("post", "/api/contacts", {"party_id": "{party}", "name_en": "x", "bogus": 1}),
    ("post", "/api/contacts", {"party_id": "{party}", "name_en": "x",
                               "methods": [{"type": "email", "value": "a@b.c", "bogus": 1}]}),
    ("patch", "/api/contacts/{contact}", {"bogus": 1}),
    ("post", "/api/contacts/{contact}/methods", {"type": "email", "value": "z@z.z", "bogus": 1}),
    ("patch", "/api/contacts/methods/{method}", {"bogus": 1}),
    ("post", "/api/interactions", {"party_id": "{party}", "channel": "call", "direction": "in",
                                   "no_followup_reason": "x", "bogus": 1}),
    ("post", "/api/interactions", {"party_id": "{party}", "channel": "call", "direction": "in",
                                   "followup": {"action": "a", "due_on": "2030-01-01", "bogus": 1}}),
    ("patch", "/api/interactions/{interaction}", {"bogus": 1}),
    ("post", "/api/interactions/{interaction}/documents", {"document_id": str(uuid.uuid4()), "bogus": 1}),
    ("post", "/api/followups", {"party_id": "{party}", "action": "a", "due_on": "2030-01-01", "bogus": 1}),
    ("post", "/api/followups/{followup}/done", {"bogus": 1}),
    ("post", "/api/followups/{followup}/reschedule", {"due_on": "2030-01-02", "bogus": 1}),
    ("post", "/api/followups/{followup}/cancel", {"note": "n", "bogus": 1}),
])
def test_every_new_request_model_rejects_unknown_fields(client, method, path, body):
    party = make_party(client, roles=["buyer"])
    contact = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "c",
                                                 "methods": [{"type": "telegram", "value": f"@m{tag()}"}]}).json()
    row = log(client, party["id"], no_followup_reason="x").json()
    f = client.post("/api/followups", json={"party_id": party["id"], "action": "a", "due_on": "2030-01-01"}).json()
    ids = {"party": party["id"], "contact": contact["id"], "method": contact["methods"][0]["id"],
           "interaction": row["id"], "followup": f["id"]}

    def fill(value):
        if isinstance(value, str):
            return value.format(**ids)
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fill(v) for v in value]
        return value

    r = getattr(client, method)(fill(path), json=fill(body))
    assert r.status_code == 422, (path, r.status_code, r.text)
    assert r.json()["error"]["code"] == "validation_error"


def test_duplicate_create_returns_409_and_persists_nothing_including_events(client, db):
    value = f"dup{tag()}@example.com"
    p1, p2 = make_party(client), make_party(client)
    assert client.post("/api/contacts", json={"party_id": p1["id"], "name_en": "first",
                                              "methods": [{"type": "email", "value": value}]}).status_code == 201
    events_before = db.execute(text("SELECT count(*) FROM core.event")).scalar()
    contacts_before = db.scalar(select(func.count()).select_from(Contact))
    r = client.post("/api/contacts", json={"party_id": p2["id"], "name_en": "second",
                                           "methods": [{"type": "phone", "value": "1"},
                                                       {"type": "email", "value": value}]})
    assert r.status_code == 409
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Contact)) == contacts_before
    assert db.execute(text("SELECT count(*) FROM core.event")).scalar() == events_before


def test_requires_login(anon_client):
    for path in ("/api/parties", "/api/command-center", "/api/followups", "/api/interactions"):
        assert anon_client.get(path).status_code == 401


def test_backup_and_restore_test_include_party_tables(client):
    from app.modules.system import backup

    party = make_party(client, roles=["buyer"])
    client.post("/api/contacts", json={"party_id": party["id"], "name_en": "Backup",
                                       "methods": [{"type": "email", "value": f"bk{tag()}@example.com"}]})
    log(client, party["id"], body="backup me", followup={"action": "a", "due_on": tomorrow()})
    run_id = backup.run_backup("manual", source="script")
    result = backup.restore_test(run_id, source="script")
    assert result["status"] == "passed", result
    import json
    from pathlib import Path

    from app.core.db import new_session
    from app.modules.system.models import BackupRun

    with new_session() as db:
        dump = Path(db.get(BackupRun, run_id).db_dump_path)
    counts = json.loads(backup.manifest_path(dump).read_text())["row_counts"]
    for table in ("core.party", "core.party_role", "core.funnel_stage", "core.contact", "core.contact_method",
                  "core.interaction", "core.followup"):
        assert counts[table] >= 1, table
