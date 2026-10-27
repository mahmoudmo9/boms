"""v0.4.0 section 0: carry-over fixes from v0.3.2."""

from sqlalchemy import text

from tests.test_parties import make_party, tag
from tests.test_sourcing_inquiries import events
from tests.test_sourcing_rfq import make_case, new_rfq, offer_body, soon, supplier


def count(db, table):
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar()


def test_offer_on_draft_recipient_is_422_and_persists_nothing(client, db):
    case, (item,) = make_case(client, [{"name": "Draft recipient item"}])
    party = supplier(client)
    body = new_rfq(client, case, [item], [{"party_id": party["id"]}])
    rid = body["recipients"][0]["id"]
    before = (count(db, "ops.supplier_offer"), count(db, "core.interaction"))
    r = client.post("/api/offers", json=offer_body(case, party, [{"line_item_id": item["id"], "unit_price": "5"}],
                                                   rfq_recipient_id=rid))
    assert r.status_code == 422 and r.json()["error"]["code"] == "recipient_not_sent"
    assert "Mark the RFQ as sent" in r.json()["error"]["message"]
    assert (count(db, "ops.supplier_offer"), count(db, "core.interaction")) == before
    # unsolicited offers stay allowed; after mark-sent the RFQ offer works
    assert client.post(f"/api/rfqs/recipients/{rid}/mark-sent", json={}).status_code == 200
    r = client.post("/api/offers", json=offer_body(case, party, [{"line_item_id": item["id"], "unit_price": "5"}],
                                                   rfq_recipient_id=rid))
    assert r.status_code == 201, r.text
    assert client.get(f"/api/rfqs/{body['id']}").json()["recipients"][0]["status"] == "replied"
    other_case, (other,) = make_case(client, [{"name": "Unsolicited"}])
    r = client.post("/api/offers", json=offer_body(other_case, party, [{"line_item_id": other["id"], "unit_price": "1"}]))
    assert r.status_code == 201


def test_withdraw_note_is_in_offer_history(client):
    case, (item,) = make_case(client, [{"name": "Withdraw note"}])
    party = supplier(client)
    off = client.post("/api/offers", json=offer_body(case, party, [{"line_item_id": item["id"], "unit_price": "5"}])).json()
    client.post(f"/api/offers/{off['id']}/status", json={"status": "withdrawn", "note": "supplier changed price"})
    assert events(client, "offer", off["id"], "status")[0]["data"]["note"] == "supplier changed price"
    assert client.get(f"/api/offers/{off['id']}").json()["status_note"] == "supplier changed price"


def test_product_edit_keeps_aliases_and_warns_on_duplicate(client):
    t = tag()
    first = client.post("/api/products", json={"name_en": f"Polypropylene {t}", "confirm_duplicate": True}).json()["product"]
    other = client.post("/api/products", json={"name_en": f"Glycol {t}", "aliases": [f"MEG {t}"],
                                               "confirm_duplicate": True}).json()["product"]
    r = client.patch(f"/api/products/{other['id']}", json={"notes": "edited", "hs_code": "2905", "kind_note": "liquid"})
    assert r.status_code == 200 and r.json()["notes"] == "edited"
    page = client.get(f"/api/products/{other['id']}").json()
    assert [a["alias"] for a in page["aliases"]] == [f"MEG {t}"]
    r = client.patch(f"/api/products/{other['id']}", json={"name_en": f"Polypropylene {t}"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "possible_duplicate"
    assert first["id"] in [d["id"] for d in r.json()["error"]["details"]["possible_duplicates"]]
    r = client.patch(f"/api/products/{other['id']}", json={"name_en": f"Polypropylene {t}", "confirm_duplicate": True})
    assert r.status_code == 200
    assert client.post(f"/api/products/{other['id']}/archive").json()["status"] == "archived"
    assert client.post(f"/api/products/{other['id']}/unarchive").json()["status"] == "active"


def test_unarchive_method_duplicate_is_stable_409(client):
    party = make_party(client)
    value = f"buyer{tag()}@example.com"
    c = client.post("/api/contacts", json={"party_id": party["id"], "name_en": "Reza",
                                           "methods": [{"type": "email", "value": value}]}).json()
    old = c["methods"][0]
    assert client.post(f"/api/contacts/methods/{old['id']}/archive").status_code == 200
    r = client.post(f"/api/contacts/{c['id']}/methods", json={"type": "email", "value": value})
    assert r.status_code == 201, r.text
    new_id = r.json()["id"] if "id" in r.json() else r.json()["methods"][-1]["id"]
    r = client.post(f"/api/contacts/methods/{old['id']}/unarchive")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "duplicate_active_method"
    assert err["details"]["contact_id"] == c["id"] and err["details"]["party_id"] == party["id"]
    assert err["details"]["method_id"] == new_id
    assert "violates" not in err["message"] and "constraint" not in err["message"].lower()
