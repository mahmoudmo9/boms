"""v0.3.1: item status follows its offers, sourcing-aware party/contact deletes, cascade case/inquiry delete,
per-name product duplicates, visible mark-sent follow-up."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.cli import alembic_config
from app.core import dbadmin
from app.core.config import get_config
from app.modules.parties import clock
from tests.conftest import create_empty_database, superuser_conninfo, unique_bytes, upload
from tests.test_parties import make_party, tag
from tests.test_sourcing_inquiries import audit_ops, events, inquiry
from tests.test_sourcing_rfq import contact, make_case, new_rfq, offer_body, soon, supplier

RAW_DB_WORDS = ("violates", "foreign key", "constraint", "DETAIL", "psycopg")


def item_of(client, item_id):
    return client.get(f"/api/line-items/{item_id}").json()


def sent_case(client, names=("Valve",)):
    """A case whose items are in a SENT RFQ (status rfq_sent)."""
    case, items = make_case(client, [{"name": n} for n in names])
    party = supplier(client)
    body = new_rfq(client, case, items, [{"party_id": party["id"]}])
    r = client.post(f"/api/rfqs/recipients/{body['recipients'][0]['id']}/mark-sent", json={})
    assert r.status_code == 200, r.text
    return case, items, party, body


def add_offer(client, case, party, item, price="5", **extra):
    r = client.post("/api/offers", json=offer_body(case, party, [{"line_item_id": item["id"], "unit_price": price}],
                                                   **extra))
    assert r.status_code == 201, r.text
    return r.json()


def withdraw(client, offer):
    r = client.post(f"/api/offers/{offer['id']}/status", json={"status": "withdrawn", "note": "pulled"})
    assert r.status_code == 200, r.text


def gate_missing(client, case):
    return {m["item_id"] for m in client.get(f"/api/cases/{case['id']}/coverage").json()["gate"]["missing"]}


# ---- change 1: status follows the offers ----------------------------------------------------------

def test_withdraw_only_offer_falls_back_to_rfq_sent(client):
    case, (item,), party, _ = sent_case(client)
    assert item_of(client, item["id"])["status"] == "rfq_sent"
    off = add_offer(client, case, party, item)
    assert item_of(client, item["id"])["status"] == "has_offer"
    withdraw(client, off)
    assert item_of(client, item["id"])["status"] == "rfq_sent"
    ev = events(client, "line_item", item["id"], "status")[0]["data"]
    assert (ev["old_status"], ev["new_status"]) == ("has_offer", "rfq_sent")


def test_withdraw_one_of_two_keeps_has_offer(client):
    case, (item,), party, _ = sent_case(client)
    a = add_offer(client, case, party, item)
    add_offer(client, case, supplier(client), item, price="6")
    withdraw(client, a)
    assert item_of(client, item["id"])["status"] == "has_offer"


def test_expiry_with_fixed_clock_recomputes_and_contacts_nobody(client, db, monkeypatch):
    case, (one, two), party, _ = sent_case(client, ("Only", "Both"))
    short = add_offer(client, case, party, one, valid_until=soon(1))
    r = client.post("/api/offers", json=offer_body(case, party, [
        {"line_item_id": two["id"], "unit_price": "3"}], valid_until=soon(1)))
    other = add_offer(client, case, supplier(client), two, valid_until=soon(30))
    assert {item_of(client, i["id"])["status"] for i in (one, two)} == {"has_offer"}
    later = datetime.combine(clock.today() + timedelta(days=3), datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
    monkeypatch.setattr(clock, "now", lambda: later)
    monkeypatch.setattr(clock, "local_tz", lambda: UTC)
    interactions_before = db.execute(text("SELECT count(*) FROM core.interaction")).scalar()
    followups_before = db.execute(text("SELECT count(*) FROM core.followup")).scalar()
    from app.modules.sourcing.handlers import expire

    result = expire(db, {})
    db.commit()
    assert result["offers_expired"] >= 2
    assert client.get(f"/api/offers/{short['id']}").json()["status"] == "expired"
    assert client.get(f"/api/offers/{r.json()['id']}").json()["status"] == "expired"
    assert item_of(client, one["id"])["status"] == "rfq_sent"
    assert item_of(client, two["id"])["status"] == "has_offer"  # the 30-day offer is still valid
    assert client.get(f"/api/offers/{other['id']}").json()["status"] == "active"
    assert db.execute(text("SELECT count(*) FROM core.interaction")).scalar() == interactions_before
    assert db.execute(text("SELECT count(*) FROM core.followup")).scalar() == followups_before


@pytest.mark.parametrize("cause", ["withdrawn", "expired", "deleted", "superseded", "unavailable"])
def test_selection_lost(client, db, monkeypatch, cause):
    case, (item,), party, _ = sent_case(client)
    off = add_offer(client, case, party, item, valid_until=soon(1) if cause == "expired" else soon(30))
    offer_item_id = off["items"][0]["id"]
    r = client.post(f"/api/line-items/{item['id']}/select", json={"offer_item_id": offer_item_id})
    assert r.json()["status"] == "selected"
    assert item["id"] not in gate_missing(client, case)

    if cause == "withdrawn":
        withdraw(client, off)
    elif cause == "expired":
        later = datetime.combine(clock.today() + timedelta(days=3), datetime.min.time(), tzinfo=UTC)
        monkeypatch.setattr(clock, "now", lambda: later + timedelta(hours=12))
        monkeypatch.setattr(clock, "local_tz", lambda: UTC)
        from app.modules.sourcing.handlers import expire

        expire(db, {})
        db.commit()
    elif cause == "deleted":
        assert client.delete(f"/api/offers/{off['id']}").status_code == 204
    elif cause == "superseded":
        add_offer(client, case, party, item, price="4", supersedes_offer_id=off["id"])
    else:
        r = client.patch(f"/api/offers/items/{offer_item_id}", json={"available": False})
        assert r.status_code == 200, r.text

    detail = item_of(client, item["id"])
    assert detail["selected_offer_item_id"] is None
    expected = "has_offer" if cause == "superseded" else "rfq_sent"
    assert detail["status"] == expected
    (ev,) = events(client, "line_item", item["id"], "selection_lost")
    assert ev["data"] == {"old_offer_item_id": offer_item_id, "cause": cause, "old_status": "selected",
                          "new_status": expected}
    assert item["id"] in gate_missing(client, case)
    row = next(i for i in client.get(f"/api/cases/{case['id']}/coverage").json()["items"] if i["item_id"] == item["id"])
    assert row["selection_lost"] is True


def test_reactivate_gives_has_offer_not_selected(client):
    case, (item,), party, _ = sent_case(client)
    off = add_offer(client, case, party, item)
    client.post(f"/api/line-items/{item['id']}/select", json={"offer_item_id": off["items"][0]["id"]})
    withdraw(client, off)
    assert client.post(f"/api/offers/{off['id']}/status", json={"status": "active"}).status_code == 200
    detail = item_of(client, item["id"])
    assert (detail["status"], detail["selected_offer_item_id"]) == ("has_offer", None)


def test_draft_recipient_is_not_rfq_sent(client):
    case, (item,) = make_case(client, [{"name": "Draft only"}])
    party = supplier(client)
    new_rfq(client, case, [item], [{"party_id": party["id"]}])
    off = add_offer(client, case, party, item)
    assert item_of(client, item["id"])["status"] == "has_offer"
    withdraw(client, off)
    assert item_of(client, item["id"])["status"] == "uncovered"


def test_recipient_decline_and_rfq_cancel_recompute(client):
    case, (item,), party, body = sent_case(client)
    client.post(f"/api/rfqs/recipients/{body['recipients'][0]['id']}/decline", json={"note": "no"})
    assert item_of(client, item["id"])["status"] == "rfq_sent"  # v0.3.2: a declined recipient still counts as sent
    case2, (item2,), _, body2 = sent_case(client)
    client.post(f"/api/rfqs/{body2['id']}/cancel", json={"reason": "stop"})
    assert item_of(client, item2["id"])["status"] == "uncovered"


def test_cancelled_and_no_coverage_untouched(client):
    case, (a, b), party, _ = sent_case(client, ("Cancelled", "NoCov"))
    oa, ob = add_offer(client, case, party, a), add_offer(client, case, supplier(client), b)
    client.post(f"/api/line-items/{a['id']}/cancel", json={"reason": "dropped"})
    client.post(f"/api/line-items/{b['id']}/no-coverage", json={"reason": "not available"})
    withdraw(client, oa)
    withdraw(client, ob)
    assert item_of(client, a["id"])["status"] == "cancelled"
    detail = item_of(client, b["id"])
    assert detail["status"] == "rfq_sent" and detail["no_coverage_confirmed"] is True
    client.delete(f"/api/line-items/{b['id']}/no-coverage")
    assert item_of(client, b["id"])["no_coverage_confirmed"] is False


def test_command_center_selection_lost_and_percent_on_fixed_dataset():
    from app.modules.parties import service as parties
    from app.modules.sourcing import dashboard, offers, rfq
    from app.modules.sourcing import coverage as coverage_service
    from app.modules.sourcing import inquiries as inquiries_service
    from app.modules.sourcing import items as items_service
    from app.modules.system.seed import seed_base_data

    name = "boms_test_v031_cc"
    create_empty_database(name)
    url = get_config().db_url(name)
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    today = clock.today()
    try:
        with Session(engine) as db:
            seed_base_data(db)
            sup, _ = parties.create_party(db, {"name_en": "Supplier", "roles": ["supplier"], "confirm_duplicate": True},
                                          "script")
            case = inquiries_service.create_case(db, {"title": "Open case"}, "script")
            a, b, c, d = items_service.add_items(db, None, case.id, [{"name": n} for n in "ABCD"], "script")
            body = rfq.create_rfq(db, {"case_id": case.id, "respond_by": today + timedelta(days=5),
                                       "items": [{"line_item_id": i.id} for i in (a, b, c)],
                                       "recipients": [{"party_id": sup.id}]}, "script")
            rfq.mark_sent(db, rfq.recipients_of(db, body.id)[0].id, {}, "script")
            offer = offers.record_offer(db, {"case_id": case.id, "party_id": sup.id, "channel": "email",
                                             "currency": "USD", "valid_until": today + timedelta(days=30),
                                             "items": [{"line_item_id": i.id, "unit_price": Decimal("5")}
                                                       for i in (a, b)],
                                             "no_followup_reason": "fyi"}, "script")
            rows = {r.line_item_id: r for r in offers.offer_items(db, offer.id)}
            coverage_service.select_offer(db, a.id, rows[a.id].id, None, "script")
            coverage_service.select_offer(db, b.id, rows[b.id].id, None, "script")
            offers.update_offer_item(db, rows[a.id].id, {"available": False}, "script")
            db.commit()
            result = dashboard.summary(db, today)
            assert [r["name"] for r in result["selection_lost"]] == ["A"]
            assert result["selection_lost"][0]["cause"] == "unavailable"
            # A rfq_sent (lost), B selected, C rfq_sent, D uncovered -> 3 of 4 have a status
            assert (result["open_items"], result["open_items_with_status"], result["coverage_status_percent"]) == (4, 3, 75.0)
            assert result["cases_not_covered"][0]["not_covered"] == 3
            # selected again -> leaves the list
            offers.update_offer_item(db, rows[a.id].id, {"available": True}, "script")
            coverage_service.select_offer(db, a.id, rows[a.id].id, None, "script")
            db.commit()
            assert dashboard.summary(db, today)["selection_lost"] == []
    finally:
        engine.dispose()
        dbadmin.drop_database(superuser_conninfo(), name)


# ---- change 3: deletes know the sourcing records -------------------------------------------------

def _no_raw(body):
    message = body["error"]["message"]
    assert not any(word.lower() in message.lower() for word in RAW_DB_WORDS), message


def test_party_delete_with_sourcing_records_is_409_with_counts(client):
    party = supplier(client)
    c = contact(client, party["id"])
    inquiry(client, party_id=party["id"])
    case, (item,) = make_case(client, [{"name": "X"}], party_id=party["id"])
    body = new_rfq(client, case, [item], [{"party_id": party["id"], "contact_id": c["id"]}])
    client.post(f"/api/rfqs/recipients/{body['recipients'][0]['id']}/mark-sent", json={})
    add_offer(client, case, party, item, contact_id=c["id"])
    client.post(f"/api/capabilities/party/{party['id']}", json={"kind": "tag", "tag_text": "valves"})
    r = client.delete(f"/api/parties/{party['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "in_use"
    _no_raw(r.json())
    details = r.json()["error"]["details"]
    assert {k: details[k] for k in ("inquiries", "cases", "rfq_recipients", "offers", "capabilities")} == {
        "inquiries": 1, "cases": 1, "rfq_recipients": 1, "offers": 1, "capabilities": 1}
    assert details["interactions"] == 2  # the send and the offer
    name = party["name_en"]
    r = client.request("DELETE", f"/api/parties/{party['id']}?cascade=true", json={"confirm_name": name})
    assert r.status_code == 409 and r.json()["error"]["code"] == "in_use", r.text
    _no_raw(r.json())
    assert r.json()["error"]["details"]["rfq_recipients"] == 1
    assert client.get(f"/api/parties/{party['id']}").status_code == 200

    r = client.delete(f"/api/contacts/{c['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["details"] == {"interactions": 2, "rfq_recipients": 1, "offers": 1}


def test_party_with_only_capability_tags_deletes_them(client, db):
    party = supplier(client)
    (cap,) = client.post(f"/api/capabilities/party/{party['id']}", json={"kind": "tag", "tag_text": "pumps"}).json()
    r = client.delete(f"/api/parties/{party['id']}")
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["capabilities"] == 1
    assert audit_ops(db, "core.party_capability", cap["id"])[-1] == "D"
    assert events(client, "party", party["id"], "capabilities_removed")[0]["data"]["removed"][0]["tag"] == "pumps"


def test_case_cascade_delete(client, db):
    case, (item, other), party, body = sent_case(client, ("Main", "Second"))
    off = add_offer(client, case, party, item)
    client.post(f"/api/line-items/{item['id']}/select", json={"offer_item_id": off["items"][0]["id"]})
    doc = upload(client, "case.txt", unique_bytes("case cascade")).json()
    client.post(f"/api/cases/{case['id']}/documents", json={"document_id": doc["id"]})
    client.post(f"/api/offers/{off['id']}/documents", json={"document_id": doc["id"]})
    recipient = client.get(f"/api/rfqs/{body['id']}").json()["recipients"][0]
    url = f"/api/cases/{case['id']}?cascade=true"
    r = client.request("DELETE", url, json={"confirm_title": case["title"].lower() + "x"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "confirm_title_mismatch"
    assert client.request("DELETE", url).status_code == 422
    r = client.request("DELETE", url, json={"confirm_title": case["title"]})
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"items": 2, "rfqs": 1, "recipients": 1, "offers": 1, "offer_items": 1,
                                  "documents": 2, "followups_cancelled": 1}
    assert client.get(f"/api/cases/{case['id']}").status_code == 404
    assert client.get(f"/api/rfqs/{body['id']}").status_code == 404
    assert client.get(f"/api/offers/{off['id']}").status_code == 404
    # interactions and files stay
    assert client.get(f"/api/interactions/{recipient['interaction_id']}").status_code == 200
    assert client.get(f"/api/interactions/{off['interaction_id']}").status_code == 200
    assert client.get(f"/api/documents/{doc['id']}").status_code == 200
    snap = events(client, "case", case["id"], "delete")[0]["data"]
    assert snap["cascade"] is True and snap["deleted"]["case"]["title"] == case["title"]
    assert {i["name"] for i in snap["deleted"]["items"]} == {"Main", "Second"}
    assert snap["deleted"]["offer_items"][0]["id"] == off["items"][0]["id"]
    for table, row_id in (("ops.case", case["id"]), ("ops.line_item", item["id"]), ("ops.rfq", body["id"]),
                          ("ops.rfq_recipient", recipient["id"]), ("ops.supplier_offer", off["id"]),
                          ("ops.offer_item", off["items"][0]["id"])):
        assert audit_ops(db, table, row_id)[-1] == "D", table
    # the supplier can now be deleted with cascade (its interactions go with it)
    r = client.request("DELETE", f"/api/parties/{party['id']}?cascade=true", json={"confirm_name": party["name_en"]})
    assert r.status_code == 200, r.text


def test_inquiry_cascade_delete(client, db):
    inq = inquiry(client, items=[{"name": "Pipe"}])
    doc = upload(client, "inq.txt", unique_bytes("inquiry cascade")).json()
    client.post(f"/api/inquiries/{inq['id']}/documents", json={"document_id": doc["id"]})
    url = f"/api/inquiries/{inq['id']}?cascade=true"
    assert client.request("DELETE", url, json={"confirm_subject": "DELETE"}).status_code == 422
    r = client.request("DELETE", url, json={"confirm_subject": inq["subject"]})
    assert r.status_code == 200, r.text
    assert r.json()["counts"] == {"items": 1, "documents": 1}
    assert client.get(f"/api/inquiries/{inq['id']}").status_code == 404
    assert client.get(f"/api/documents/{doc['id']}").status_code == 200
    assert audit_ops(db, "ops.inquiry", inq["id"])[-1] == "D"
    assert events(client, "inquiry", inq["id"], "delete")[0]["data"]["deleted"]["items"][0]["name"] == "Pipe"

    blank = client.post("/api/inquiries", json={"source_channel": "email"}).json()
    assert client.request("DELETE", f"/api/inquiries/{blank['id']}?cascade=true",
                          json={"confirm_subject": "DELETE"}).status_code == 200

    converted = inquiry(client)
    client.put(f"/api/inquiries/{converted['id']}/decision", json={
        "light": "green", "reason": "ok", "feasible_sourcing": "yes", "exposure_acceptable": "yes",
        "requirements_ok": "yes"})
    assert client.post(f"/api/inquiries/{converted['id']}/convert", json={}).status_code == 201
    r = client.request("DELETE", f"/api/inquiries/{converted['id']}?cascade=true",
                       json={"confirm_subject": converted["subject"]})
    assert r.status_code == 409 and r.json()["error"]["details"] == {"cases": 1}


def test_fk_errors_never_copy_db_text(client):
    case, (item,) = make_case(client, [{"name": "Unit"}])
    r = client.patch(f"/api/line-items/{item['id']}", json={"unit_code": "zz_unknown"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_unit"
    _no_raw(r.json())
    r = client.post("/api/products", json={"name_en": f"P {tag()}", "default_unit_code": "zz_unknown"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_unit"
    _no_raw(r.json())


# ---- change 4: product duplicates by each name -----------------------------------------------------

def test_product_duplicates_compare_each_name(client):
    t = tag()
    existing = client.post("/api/products", json={"name_fa": f"پلی‌اتیلن سنگین {t}", "name_en": f"HDPE X {t}",
                                                  "confirm_duplicate": True}).json()["product"]
    r = client.post("/api/products", json={"name_fa": f"پلي‌اتيلن سنگين {t}"})  # Arabic yeh/kaf, Persian name only
    assert r.json()["created"] is False
    assert existing["id"] in [d["id"] for d in r.json()["possible_duplicates"]]
    r = client.post("/api/products", json={"name_en": f"hdpe x {t}"})
    assert r.json()["created"] is False
    assert [d["score"] for d in r.json()["possible_duplicates"] if d["id"] == existing["id"]] == [1.0]
    r = client.post("/api/products", json={"name_en": f"Zirconium oxide powder {tag()}{tag()}"})
    assert r.json()["created"] is True, r.json()
    r = client.post("/api/products", json={"name_fa": f"پلي‌اتيلن سنگين {t}", "confirm_duplicate": True})
    assert r.json()["created"] is True
    # update path
    other = client.post("/api/products", json={"name_en": f"Unrelated thing {tag()}{tag()}"}).json()["product"]
    r = client.patch(f"/api/products/{other['id']}", json={"name_en": f"HDPE X {t}"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "possible_duplicate"
    assert existing["id"] in [d["id"] for d in r.json()["error"]["details"]["possible_duplicates"]]
    r = client.patch(f"/api/products/{other['id']}", json={"name_en": f"HDPE X {t}", "confirm_duplicate": True})
    assert r.status_code == 200 and r.json()["name_en"] == f"HDPE X {t}"
    # create from item
    case, (item,) = make_case(client, [{"name": f"پلي‌اتيلن سنگين {t}"}])
    r = client.post(f"/api/line-items/{item['id']}/create-product", json={})
    assert r.json()["created"] is False and existing["id"] in [d["id"] for d in r.json()["possible_duplicates"]]
    r = client.post(f"/api/line-items/{item['id']}/create-product", json={"confirm_duplicate": True})
    assert r.status_code == 201


# ---- change 5: the mark-sent follow-up is recorded ----------------------------------------------------

def test_mark_sent_records_followup_id(client):
    case, items = make_case(client, [{"name": "Hose"}])
    party = supplier(client)
    body = new_rfq(client, case, items, [{"party_id": party["id"]}])
    client.post(f"/api/rfqs/recipients/{body['recipients'][0]['id']}/mark-sent", json={})
    ev = events(client, "rfq", body["id"], "sent")[0]["data"]
    detail = client.get(f"/api/interactions/{ev['interaction_id']}").json()
    assert ev["followup_id"] == detail["followups"][0]["id"]
    assert detail["followups"][0]["due_on"] == soon(5)

    no_date = new_rfq(client, case, items, [{"party_id": supplier(client)["id"]}], respond_by=None)
    rid = no_date["recipients"][0]["id"]
    r = client.post(f"/api/rfqs/recipients/{rid}/mark-sent", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "next_action_required"
    r = client.post(f"/api/rfqs/recipients/{rid}/mark-sent", json={"no_followup_reason": "they will call"})
    assert r.status_code == 200
    ev = [e for e in events(client, "rfq", no_date["id"], "sent")][0]["data"]
    assert ev["followup_id"] is None and ev["no_followup_reason"] == "they will call"
