"""v0.2.1: real deletes, interaction corrections, archive with open follow-ups, E.164 phones, phone search,
shared numbers."""

import uuid
from datetime import UTC, date, datetime

import psycopg
import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.cli import alembic_config
from app.core import dbadmin
from app.core.config import get_config
from app.modules.parties.normalize import normalize_method
from tests.conftest import TEST_DB, create_empty_database, superuser_conninfo, unique_bytes, upload
from tests.test_parties import log, make_party, tag, tomorrow


def number() -> str:
    """A random Iranian mobile number in local form: 0912 + 7 digits."""
    return f"0912{uuid.uuid4().int % 10**7:07d}"


def contact(client, party_id, methods=(), **extra):
    r = client.post("/api/contacts", json={"party_id": party_id, "name_en": f"C {tag()}",
                                           "methods": list(methods), **extra})
    assert r.status_code == 201, r.text
    return r.json()


def events(client, entity_type, entity_id, action):
    return client.get("/api/events", params={"entity_type": entity_type, "entity_id": entity_id,
                                             "action": action}).json()["items"]


def audit_ops(db, table, row_id) -> list[str]:
    return list(db.execute(text("SELECT op FROM core.audit WHERE table_name = :t AND row_id = :r ORDER BY id"),
                           {"t": table, "r": str(row_id)}).scalars())


def delete(client, url, **kwargs):
    return client.request("DELETE", url, **kwargs)


# ---- 1. deletes -----------------------------------------------------------------------------

def test_delete_method_always_allowed_with_snapshot_and_audit(client, db):
    party = make_party(client)
    c = contact(client, party["id"], [{"type": "email", "value": f"m{tag()}@example.com"}])
    method = c["methods"][0]
    log(client, party["id"], contact_id=c["id"], no_followup_reason="fyi")  # contact in use: method still deletable
    assert delete(client, f"/api/contacts/methods/{method['id']}").status_code == 204
    ev = events(client, "contact", c["id"], "method_delete")[0]
    assert ev["data"]["deleted"]["id"] == method["id"] and ev["data"]["deleted"]["value"] == method["value"]
    assert audit_ops(db, "core.contact_method", method["id"]) == ["I", "D"]


# v0.3.1: sourcing registers its counts with parties.references
NO_SOURCING = {"inquiries": 0, "cases": 0, "rfq_recipients": 0, "offers": 0, "capabilities": 0}


def test_delete_contact_allowed_and_blocked(client, db):
    party = make_party(client)
    free = contact(client, party["id"], [{"type": "phone", "value": number()}])
    assert delete(client, f"/api/contacts/{free['id']}").status_code == 204
    ev = events(client, "contact", free["id"], "delete")[0]
    snapshot = ev["data"]["deleted"]
    assert snapshot["name_en"] == free["name_en"] and snapshot["methods"][0]["value_norm"].startswith("+98")
    assert audit_ops(db, "core.contact", free["id"])[-1] == "D"
    assert audit_ops(db, "core.contact_method", free["methods"][0]["id"])[-1] == "D"

    used = contact(client, party["id"])
    log(client, party["id"], contact_id=used["id"], no_followup_reason="fyi")
    log(client, party["id"], contact_id=used["id"], no_followup_reason="fyi")
    r = delete(client, f"/api/contacts/{used['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "in_use" and r.json()["error"]["details"] == {"interactions": 2, "rfq_recipients": 0, "offers": 0}


def test_delete_party_allowed_with_contacts_roles_and_snapshot(client, db):
    party = make_party(client, name_fa="طرف حذفی", roles=["buyer"])
    c = contact(client, party["id"], [{"type": "whatsapp", "value": number()}])
    r = delete(client, f"/api/parties/{party['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"interactions": 0, "followups": 0, "documents": 0, **NO_SOURCING}
    assert client.get(f"/api/parties/{party['id']}").status_code == 404
    ev = events(client, "party", party["id"], "delete")[0]
    snap = ev["data"]["deleted"]
    assert snap["party"]["name_fa"] == "طرف حذفی" and snap["roles"][0]["role"] == "buyer"
    assert snap["contacts"][0]["id"] == c["id"] and snap["contacts"][0]["methods"][0]["type"] == "whatsapp"
    assert audit_ops(db, "core.party", party["id"])[-1] == "D"
    assert audit_ops(db, "core.contact", c["id"])[-1] == "D"


def test_delete_party_blocked_counts(client):
    party = make_party(client)
    log(client, party["id"], body="a", followup={"action": "call", "due_on": tomorrow()})
    doc = upload(client, "p.txt", unique_bytes("party delete")).json()
    client.post(f"/api/parties/{party['id']}/documents", json={"document_id": doc["id"]})
    r = delete(client, f"/api/parties/{party['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "in_use"
    assert r.json()["error"]["details"] == {"interactions": 1, "followups": 1, "documents": 1, **NO_SOURCING}
    assert client.get(f"/api/parties/{party['id']}").status_code == 200


def test_cascade_delete_needs_exact_name_and_snapshots_interactions(client, db):
    name = f"Test Party {tag()}"
    party = make_party(client, name_en=name)
    sent_at = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    doc = upload(client, "i.txt", unique_bytes("cascade")).json()
    row = log(client, party["id"], subject="Quote", body="pasted text", channel="email", direction="out",
              occurred_at=sent_at.isoformat(), followup={"action": "call", "due_on": tomorrow()},
              document_ids=[doc["id"]]).json()
    url = f"/api/parties/{party['id']}?cascade=true"
    r = delete(client, url, json={"confirm_name": name.lower()})
    assert r.status_code == 422 and r.json()["error"]["code"] == "confirm_name_mismatch"
    assert delete(client, url).status_code == 422
    r = delete(client, url, json={"confirm_name": name})
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"interactions": 1, "followups": 1, "documents": 1, **NO_SOURCING}
    snap = events(client, "party", party["id"], "delete")[0]["data"]["deleted"]
    (i,) = snap["interactions"]
    assert (i["subject"], i["body"], i["channel"], i["direction"]) == ("Quote", "pasted text", "email", "out")
    assert datetime.fromisoformat(i["occurred_at"]) == sent_at
    assert snap["followups"][0]["action"] == "call" and snap["document_links"][0]["document_id"] == doc["id"]
    assert audit_ops(db, "core.interaction", row["id"])[-1] == "D"
    assert client.get(f"/api/documents/{doc['id']}").status_code == 200  # the file itself is untouched
    # the flag was transaction-local: a later plain DELETE is still rejected
    other = make_party(client)
    kept = log(client, other["id"], no_followup_reason="x").json()
    with pytest.raises(DBAPIError) as info:
        db.execute(text("DELETE FROM core.interaction WHERE id = :i"), {"i": kept["id"]})
    assert isinstance(info.value.orig, psycopg.errors.RestrictViolation)
    db.rollback()


def test_interaction_delete_needs_flag_in_database(client):
    party = make_party(client)
    row = log(client, party["id"], no_followup_reason="x").json()
    with dbadmin.superuser_conn(superuser_conninfo(), TEST_DB) as conn:
        with pytest.raises(psycopg.errors.RestrictViolation):
            with conn.transaction():
                conn.execute("DELETE FROM core.interaction WHERE id = %s", (row["id"],))
        with conn.transaction():
            conn.execute("SET LOCAL boms.allow_interaction_delete = 'off'")
            with pytest.raises(psycopg.errors.RestrictViolation):
                with conn.transaction():
                    conn.execute("DELETE FROM core.interaction WHERE id = %s", (row["id"],))
    assert client.get(f"/api/interactions/{row['id']}").status_code == 200


def test_event_and_audit_stay_append_only(db):
    for table in ("core.event", "core.audit"):
        with pytest.raises(DBAPIError):
            db.execute(text(f"DELETE FROM {table} WHERE id = (SELECT max(id) FROM {table})"))
        db.rollback()
        with pytest.raises(DBAPIError):
            db.execute(text("SELECT set_config('boms.allow_interaction_delete', 'on', true)"))
            db.execute(text(f"DELETE FROM {table} WHERE id = (SELECT max(id) FROM {table})"))
        db.rollback()


# ---- 2. interaction corrections ------------------------------------------------------------

def test_move_interaction_to_other_party_moves_followups(client, db):
    p1, p2 = make_party(client), make_party(client)
    c1, c2 = contact(client, p1["id"]), contact(client, p2["id"])
    doc = upload(client, "move.txt", unique_bytes("move")).json()
    row = log(client, p1["id"], contact_id=c1["id"], body="wrong party", document_ids=[doc["id"]],
              followup={"action": "Send offer", "due_on": tomorrow()}).json()
    unrelated = client.post("/api/followups", json={"party_id": p1["id"], "action": "x", "due_on": tomorrow()}).json()

    r = client.patch(f"/api/interactions/{row['id']}", json={"party_id": p2["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "contact_not_of_party"  # c1 belongs to p1
    r = client.patch(f"/api/interactions/{row['id']}", json={"party_id": p2["id"], "contact_id": c1["id"]})
    assert r.status_code == 422

    when = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    r = client.patch(f"/api/interactions/{row['id']}", json={
        "party_id": p2["id"], "contact_id": c2["id"], "channel": "call", "direction": "out",
        "occurred_at": when.isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["party_id"], body["contact_id"], body["channel"], body["direction"]) == (
        p2["id"], c2["id"], "call", "out")
    assert body["followups"][0]["party_id"] == p2["id"]
    assert body["documents"][0]["document_id"] == doc["id"]  # document links stay
    open_p1 = client.get("/api/followups", params={"party_id": p1["id"]}).json()["items"]
    assert [f["id"] for f in open_p1] == [unrelated["id"]]

    ev = events(client, "interaction", row["id"], "correct")[0]["data"]
    assert ev["before"]["party_id"] == p1["id"] and ev["after"]["party_id"] == p2["id"]
    assert ev["before"]["contact_id"] == c1["id"] and ev["after"]["contact_id"] == c2["id"]
    assert ev["before"]["channel"] == "whatsapp" and ev["after"]["channel"] == "call"
    assert ev["before"]["direction"] == "in" and ev["after"]["direction"] == "out"
    assert datetime.fromisoformat(ev["after"]["occurred_at"]) == when
    assert ev["moved_followups"] == [body["followups"][0]["id"]]
    assert events(client, "followup", body["followups"][0]["id"], "move")

    r = client.patch(f"/api/interactions/{row['id']}", json={"contact_id": None})
    assert r.status_code == 200 and r.json()["contact_id"] is None
    r = client.patch(f"/api/interactions/{row['id']}", json={"occurred_at": "2026-09-01T08:00:00"})
    assert r.status_code == 422


def test_interaction_guard_needs_flag_and_keeps_reason_immutable(client, db):
    p1, p2 = make_party(client), make_party(client)
    row = log(client, p1["id"], no_followup_reason="info").json()
    for sql in ("UPDATE core.interaction SET party_id = :p WHERE id = :i",
                "UPDATE core.interaction SET occurred_at = now() - interval '1 day' WHERE id = :i",
                "UPDATE core.interaction SET direction = 'out' WHERE id = :i"):
        with pytest.raises(DBAPIError) as info:
            db.execute(text(sql), {"p": p2["id"], "i": row["id"]})
        assert isinstance(info.value.orig, psycopg.errors.RestrictViolation)
        db.rollback()
    for sql in ("UPDATE core.interaction SET no_followup_reason = 'changed' WHERE id = :i",
                "UPDATE core.interaction SET created_at = now() WHERE id = :i"):
        with pytest.raises(DBAPIError):
            db.execute(text("SELECT set_config('boms.interaction_edit', 'on', true)"))
            db.execute(text(sql), {"i": row["id"]})
        db.rollback()
    r = client.patch(f"/api/interactions/{row['id']}", json={"no_followup_reason": "x"})
    assert r.status_code == 422  # unknown field for PATCH


# ---- 3. archive with open follow-ups ------------------------------------------------------

def test_archive_cancels_open_followups_by_default(client):
    party = make_party(client)
    f = client.post("/api/followups", json={"party_id": party["id"], "action": "a", "due_on": tomorrow()}).json()
    r = client.post(f"/api/parties/{party['id']}/archive", json={"open_followups": "cancel"})
    assert r.status_code == 200 and r.json()["open_followups"] == []
    rows = client.get("/api/followups", params={"party_id": party["id"], "status": "cancelled"}).json()["items"]
    assert rows[0]["id"] == f["id"] and rows[0]["done_note"] == "party archived"
    assert events(client, "followup", f["id"], "cancel")[0]["data"] == {"note": "party archived"}
    assert events(client, "party", party["id"], "archive")[0]["data"]["cancelled"] == [f["id"]]
    # no body: the default is cancel
    other = make_party(client)
    client.post("/api/followups", json={"party_id": other["id"], "action": "a", "due_on": tomorrow()})
    assert client.post(f"/api/parties/{other['id']}/archive").json()["open_followups"] == []


def test_archive_keep_leaves_followups_in_command_center(client):
    party = make_party(client)
    f = client.post("/api/followups", json={"party_id": party["id"], "action": "keep me",
                                            "due_on": date.today().isoformat()}).json()
    r = client.post(f"/api/parties/{party['id']}/archive", json={"open_followups": "keep"})
    assert r.status_code == 200 and [x["id"] for x in r.json()["open_followups"]] == [f["id"]]
    today = client.get("/api/command-center").json()["today"]
    item = next(x for x in today if x["id"] == f["id"])
    assert item["party_status"] == "archived"
    assert delete(client, f"/api/parties/{party['id']}").status_code == 409  # delete only when none
    assert client.post(f"/api/parties/{party['id']}/archive", json={"open_followups": "drop"}).status_code == 422


# ---- 4. phone numbers --------------------------------------------------------------------

@pytest.mark.parametrize("typed", ["0912 345 6789", "+98 912 345 6789", "0098 912 345 6789", "۰۹۱۲ ۳۴۵ ۶۷۸۹"])
def test_phone_forms_store_e164(typed):
    assert normalize_method("phone", typed) == "+989123456789"
    assert normalize_method("whatsapp", typed, "IR") == "+989123456789"


def test_phone_region_from_party_and_client(client):
    uae = make_party(client, country_iso2="AE")
    c = contact(client, uae["id"], [{"type": "phone", "value": "050 123 4567"}])
    m = c["methods"][0]
    assert (m["value"], m["value_norm"], m["value_display"]) == ("050 123 4567", "+971501234567", "+971 50 123 4567")
    # client region wins over the party country
    r = client.post(f"/api/contacts/{c['id']}/methods",
                    json={"type": "whatsapp", "value": "0912 345 6789", "region": "IR", "confirm_shared": True})
    assert r.status_code == 201 and r.json()["value_norm"] == "+989123456789"
    # no country -> Iran
    plain = make_party(client)
    c2 = contact(client, plain["id"], [{"type": "phone", "value": number()}])
    assert c2["methods"][0]["value_norm"].startswith("+98912")
    assert c2["methods"][0]["value_display"].startswith("+98 912 ")


# phonenumbers' "possible" check is length-based: "0912 345" is a possible Iranian number and is accepted.
@pytest.mark.parametrize("value", ["123", "+98 912 345 6789 1234 5", "+999 123 4567", "phone"])
def test_invalid_phone_is_422(client, value):
    party = make_party(client)
    r = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "X",
                                           "methods": [{"type": "phone", "value": value}]})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_phone" and r.json()["error"]["details"]["reason"]


def test_phone_regions(client):
    regions = {r["iso2"]: r for r in client.get("/api/parties/phone-regions").json()}
    assert regions["IR"]["calling_code"] == 98 and regions["AE"]["calling_code"] == 971
    assert regions["IR"]["name_fa"] and regions["AE"]["name_en"]


def test_migration_0005_prefixes_phones_and_downgrades():
    db_name = "boms_test_parties_0005"
    create_empty_database(db_name)
    url = get_config().db_url(db_name)
    cfg = alembic_config(url)
    engine = create_engine(url)

    def norms():
        with engine.connect() as conn:
            return dict(conn.execute(text("SELECT type, value_norm FROM core.contact_method")).all())

    try:
        command.upgrade(cfg, "0004")
        with engine.begin() as conn:
            party = conn.execute(text("INSERT INTO core.party (name_en) VALUES ('Old') RETURNING id")).scalar()
            person = conn.execute(text("INSERT INTO core.contact (party_id, name_en) VALUES (:p, 'A') RETURNING id"),
                                  {"p": party}).scalar()
            for kind, value, norm in (("phone", "0912 345 6789", "989123456789"),
                                      ("whatsapp", "+971 50 123 4567", "971501234567"),
                                      ("email", "a@b.com", "a@b.com")):
                conn.execute(text("INSERT INTO core.contact_method (contact_id, type, value, value_norm) "
                                  "VALUES (:c, :t, :v, :n)"), {"c": person, "t": kind, "v": value, "n": norm})
        command.upgrade(cfg, "0005")
        assert norms() == {"phone": "+989123456789", "whatsapp": "+971501234567", "email": "a@b.com"}
        command.downgrade(cfg, "0004")
        assert norms() == {"phone": "989123456789", "whatsapp": "971501234567", "email": "a@b.com"}
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()
        dbadmin.drop_database(superuser_conninfo(), db_name)


# ---- 5. phone search -----------------------------------------------------------------------

def test_phone_search_in_any_format(client, db):
    from app.modules.parties.searchable import _contacts

    local = number()
    rest = local[4:]
    party = make_party(client)
    c = contact(client, party["id"], [{"type": "whatsapp", "value": local}])
    spaced = f"+98 912 {rest[:3]} {rest[3:]}"
    for query in (local, f"912{rest[:3]}", f"98912{rest}", spaced):
        groups = client.get("/api/search", params={"q": query, "types": "contact", "limit": 50}).json()["groups"]
        assert c["id"] in [h["id"] for g in groups for h in g["items"]], query
    # "0912" matches every test number with that prefix: check the provider without the result limit
    assert c["id"] in [h.id for h in _contacts(db, "0912", "0912", 100000)]


# ---- 6/7. shared numbers -------------------------------------------------------------------

def test_shared_number_warns_then_confirms(client, db):
    local = number()
    p1, p2 = make_party(client, name_en=f"First {tag()}"), make_party(client)
    first = contact(client, p1["id"], [{"type": "phone", "value": local}])
    body = {"party_id": p2["id"], "name_en": "Second", "methods": [{"type": "phone", "value": f"+98{local[1:]}"}]}
    r = client.post("/api/contacts", json=body)
    assert r.status_code == 200 and r.json()["created"] is False
    (shared,) = r.json()["shared_with"]
    assert (shared["contact_name"], shared["party_name"], shared["party_id"]) == (
        first["name_en"], p1["name_en"], p1["id"])
    assert client.get("/api/contacts", params={"party_id": p2["id"]}).json() == []
    r = client.post("/api/contacts", json={**body, "confirm_shared": True})
    assert r.status_code == 201 and r.json()["created"] is True
    assert r.json()["methods"][0]["value_norm"] == first["methods"][0]["value_norm"]

    # add-method path
    third = contact(client, p2["id"])
    r = client.post(f"/api/contacts/{third['id']}/methods", json={"type": "phone", "value": local})
    assert r.status_code == 200 and r.json()["created"] is False and len(r.json()["shared_with"]) == 2
    r = client.post(f"/api/contacts/{third['id']}/methods",
                    json={"type": "phone", "value": local, "confirm_shared": True})
    assert r.status_code == 201

    # the same contact twice is a hard 409, also directly in the database
    r = client.post(f"/api/contacts/{first['id']}/methods",
                    json={"type": "phone", "value": local, "confirm_shared": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_contact_method"
    with pytest.raises(DBAPIError) as info:
        db.execute(text("INSERT INTO core.contact_method (contact_id, type, value, value_norm) "
                        "VALUES (:c, 'phone', 'x', :n)"), {"c": first["id"], "n": first["methods"][0]["value_norm"]})
    assert isinstance(info.value.orig, psycopg.errors.UniqueViolation)
    db.rollback()


def test_archived_values_do_not_block(client):
    local = number()
    party = make_party(client)
    c = contact(client, party["id"], [{"type": "phone", "value": local}])
    old = c["methods"][0]
    assert client.post(f"/api/contacts/methods/{old['id']}/archive").json()["status"] == "archived"
    # re-adding on the same contact creates a new row
    r = client.post(f"/api/contacts/{c['id']}/methods", json={"type": "phone", "value": local})
    assert r.status_code == 201 and r.json()["id"] != old["id"] and r.json()["shared_with"] == []
    # restoring the archived copy now collides with the active one on the same contact
    assert client.post(f"/api/contacts/methods/{old['id']}/unarchive").status_code == 409
    # an archived value on another contact gives no warning
    other = contact(client, make_party(client)["id"])
    new_id = r.json()["id"]
    client.post(f"/api/contacts/methods/{new_id}/archive")
    r = client.post(f"/api/contacts/{other['id']}/methods", json={"type": "phone", "value": local})
    assert r.status_code == 201 and r.json()["shared_with"] == []


def test_new_bodies_reject_unknown_fields(client):
    party = make_party(client)
    assert client.post(f"/api/parties/{party['id']}/archive", json={"open_followups": "keep", "x": 1}).status_code == 422
    r = delete(client, f"/api/parties/{party['id']}?cascade=true", json={"confirm_name": "a", "force": True})
    assert r.status_code == 422
    c = contact(client, party["id"])
    r = client.post(f"/api/contacts/{c['id']}/methods", json={"type": "phone", "value": number(), "extra": 1})
    assert r.status_code == 422
