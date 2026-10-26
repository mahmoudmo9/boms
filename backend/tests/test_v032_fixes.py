"""v0.3.2: no_response keeps rfq_sent (+ resend list), cascade delete cancels chase follow-ups, contact person on
offers, RFQ default title and the reply-by sentence without a date."""

from datetime import date, timedelta

from sqlalchemy import text

from app.modules.sourcing import rfq as rfq_service
from tests.test_parties import tag
from tests.test_sourcing_inquiries import events
from tests.test_sourcing_rfq import contact, make_case, new_rfq, offer_body, soon, supplier
from tests.test_v031_fixes import add_offer, item_of

PAST = (date.today() - timedelta(days=1)).isoformat()


def sourcing(client):
    return client.get("/api/command-center").json()["sourcing"]


def ids(rows):
    return {r["item_id"] for r in rows}


def send(client, recipient_id):
    r = client.post(f"/api/rfqs/recipients/{recipient_id}/mark-sent", json={"followup": {"action": "chase", "due_on": soon(1)}})
    assert r.status_code == 200, r.text


def expired_rfq(client, case, items, parties):
    """An RFQ past respond_by, sent to ``parties``, then the expiry job (all recipients -> no_response)."""
    body = new_rfq(client, case, items, [{"party_id": p["id"]} for p in parties], respond_by=PAST)
    for r in body["recipients"]:
        send(client, r["id"])
    return body


# ---- change 1: no_response keeps rfq_sent ----------------------------------------------------------------

def test_all_no_response_keeps_rfq_sent_and_lists_for_resend(client, db):
    case, (item,) = make_case(client, [{"name": "No reply item"}])
    a, b = supplier(client), supplier(client)
    expired_rfq(client, case, [item], [a, b])
    rfq_service.expire_no_reply(db)
    db.commit()
    assert item_of(client, item["id"])["status"] == "rfq_sent"
    cc = sourcing(client)
    assert item["id"] not in ids(cc["items_without_rfq"])
    assert item["id"] in ids(cc["no_response_resend"])
    row = next(r for r in cc["no_response_resend"] if r["item_id"] == item["id"])
    assert row["case_id"] == case["id"] and row["recipients"] == 2

    # a new RFQ sent to another supplier -> leaves the list
    other = supplier(client)
    fresh = new_rfq(client, case, [item], [{"party_id": other["id"]}])
    send(client, fresh["recipients"][0]["id"])
    assert item["id"] not in ids(sourcing(client)["no_response_resend"])


def test_declined_and_no_response_mix_is_listed(client, db):
    case, (item,) = make_case(client, [{"name": "Declined item"}])
    a, b = supplier(client), supplier(client)
    body = expired_rfq(client, case, [item], [a, b])
    client.post(f"/api/rfqs/recipients/{body['recipients'][0]['id']}/decline", json={"note": "no stock"})
    rfq_service.expire_no_reply(db)
    db.commit()
    assert item_of(client, item["id"])["status"] == "rfq_sent"
    assert item["id"] in ids(sourcing(client)["no_response_resend"])


def test_replied_with_valid_offer_is_not_listed(client, db):
    case, (item,) = make_case(client, [{"name": "Answered item"}])
    a, b = supplier(client), supplier(client)
    expired_rfq(client, case, [item], [a, b])
    add_offer(client, case, a, item)
    rfq_service.expire_no_reply(db)
    db.commit()
    assert item_of(client, item["id"])["status"] == "has_offer"
    assert item["id"] not in ids(sourcing(client)["no_response_resend"])


def test_draft_only_is_uncovered(client):
    case, (item,) = make_case(client, [{"name": "Draft only item"}])
    new_rfq(client, case, [item], [{"party_id": supplier(client)["id"]}])
    assert item_of(client, item["id"])["status"] == "uncovered"
    cc = sourcing(client)
    assert item["id"] in ids(cc["items_without_rfq"]) and item["id"] not in ids(cc["no_response_resend"])


# ---- change 2: cascade delete cancels the chase follow-ups -----------------------------------------------

def test_case_cascade_cancels_chase_followups_only(client, db):
    party = supplier(client)
    unrelated = client.post("/api/interactions", json={
        "party_id": party["id"], "channel": "call", "direction": "out", "body": "other deal",
        "followup": {"action": "call about other deal", "due_on": soon(3)}}).json()
    case, (item,) = make_case(client, [{"name": "Chased item"}])
    body = new_rfq(client, case, [item], [{"party_id": party["id"]}])
    client.post(f"/api/rfqs/recipients/{body['recipients'][0]['id']}/mark-sent", json={})
    off = add_offer(client, case, party, item, no_followup_reason=None,
                    followup={"action": "check offer", "due_on": soon(2)})
    recipient = client.get(f"/api/rfqs/{body['id']}").json()["recipients"][0]
    chase_ids = [str(i) for i in db.execute(text(
        "SELECT id FROM core.followup WHERE interaction_id IN (:a, :b) AND status = 'open'"),
        {"a": recipient["interaction_id"], "b": off["interaction_id"]}).scalars()]
    assert len(chase_ids) == 2
    r = client.request("DELETE", f"/api/cases/{case['id']}?cascade=true", json={"confirm_title": case["title"]})
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["followups_cancelled"] == 2
    rows = dict(db.execute(text("SELECT id::text, status || '|' || coalesce(done_note, '') FROM core.followup "
                                "WHERE party_id = :p"), {"p": party["id"]}).all())
    for fid in chase_ids:
        assert rows[fid] == "cancelled|case deleted"
        assert events(client, "followup", fid, "cancel")[0]["data"]["note"] == "case deleted"
    other = [fid for fid in rows if fid not in chase_ids]
    assert len(other) == 1 and rows[other[0]] == "open|"
    assert client.get(f"/api/interactions/{unrelated['id']}").status_code == 200
    assert client.get(f"/api/interactions/{recipient['interaction_id']}").status_code == 200
    snap = events(client, "case", case["id"], "delete")[0]["data"]["deleted"]
    assert sorted(snap["cancelled_followups"]) == sorted(chase_ids)


# ---- change 3: contact person on offers --------------------------------------------------------------------

def test_offer_contact_checked_shown_and_used(client, db):
    party = supplier(client)
    abbas = contact(client, party["id"], name=f"Abbas {tag()}")
    stranger = contact(client, supplier(client)["id"], name="Stranger")
    case, (item,) = make_case(client, [{"name": "Contact item"}])
    body = new_rfq(client, case, [item], [{"party_id": party["id"], "contact_id": abbas["id"]}])
    rec = body["recipients"][0]
    assert rec["contact_id"] == abbas["id"] and rec["contact_name_en"] == abbas["name_en"]
    send(client, rec["id"])

    r = client.post("/api/offers", json=offer_body(case, party, [{"line_item_id": item["id"], "unit_price": "5"}],
                                                   contact_id=stranger["id"]))
    assert r.status_code == 422 and r.json()["error"]["code"] == "contact_not_of_party"
    off = add_offer(client, case, party, item, contact_id=abbas["id"], rfq_recipient_id=rec["id"])
    assert off["contact_name_en"] == abbas["name_en"]
    r = client.patch(f"/api/offers/{off['id']}", json={"contact_id": stranger["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "contact_not_of_party"
    assert client.get(f"/api/interactions/{off['interaction_id']}").json()["contact_id"] == abbas["id"]

    row = client.get(f"/api/cases/{case['id']}/comparison").json()["items"][0]["groups"][0]["unit_groups"][0]["rows"][0]
    assert row["contact_name_en"] == abbas["name_en"]
    made = client.post(f"/api/line-items/{item['id']}/create-product", json={"confirm_duplicate": True}).json()
    prices = client.get(f"/api/products/{made['product_id']}").json()["prices"]["offers"]
    assert prices[0]["contact_en"] == abbas["name_en"]

    # an archived contact is still shown
    assert client.post(f"/api/contacts/{abbas['id']}/archive").status_code == 200
    assert client.get(f"/api/offers/{off['id']}").json()["contact_name_en"] == abbas["name_en"]
    assert client.get(f"/api/rfqs/{body['id']}").json()["recipients"][0]["contact_name_en"] == abbas["name_en"]


# ---- change 4: RFQ title, read-only sent text, reply-by sentence --------------------------------------------

def test_default_rfq_title_is_unique_per_case(client):
    case, (a, b) = make_case(client, [{"name": "Ball valve"}, {"name": "Gate valve"}])
    party = supplier(client)
    first = new_rfq(client, case, [a], [{"party_id": party["id"]}])
    second = new_rfq(client, case, [b, a], [{"party_id": party["id"]}])
    third = new_rfq(client, case, [a], [{"party_id": party["id"]}], title="  ")
    named = new_rfq(client, case, [a], [{"party_id": party["id"]}], title="My own title")
    assert (first["title"], second["title"], third["title"]) == ("RFQ 1 - Ball valve", "RFQ 2 - Gate valve",
                                                                   "RFQ 3 - Ball valve")
    assert named["title"] == "My own title"


def test_sent_recipient_text_is_read_only(client):
    case, (item,) = make_case(client, [{"name": "Read only"}])
    body = new_rfq(client, case, [item], [{"party_id": supplier(client)["id"]}, {"party_id": supplier(client)["id"]}])
    sent, draft = body["recipients"]
    send(client, sent["id"])
    for change in ({"message_text": "changed"}, {"subject": "changed"}, {"rerender": True}):
        r = client.patch(f"/api/rfqs/recipients/{sent['id']}", json=change)
        assert r.status_code == 409 and r.json()["error"]["code"] == "recipient_sent", change
    r = client.patch(f"/api/rfqs/recipients/{draft['id']}", json={"message_text": "edited draft"})
    assert r.status_code == 200 and r.json()["message_text"] == "edited draft"


def test_no_reply_by_sentence_without_respond_by(client):
    case, (item,) = make_case(client, [{"name": "No date item"}])
    recipients = [{"party_id": supplier(client)["id"], "channel": ch, "language": lang}
                  for lang in ("en", "fa") for ch in ("email", "whatsapp")]
    body = new_rfq(client, case, [item], recipients[:1], respond_by=None)
    for spec in recipients[1:]:
        r = client.post(f"/api/rfqs/{body['id']}/recipients", json=spec)
        assert r.status_code == 201, r.text
    texts = {(r["language"], r["channel"]): r["message_text"] for r in client.get(f"/api/rfqs/{body['id']}").json()["recipients"]}
    assert len(texts) == 4
    for (lang, channel), message in texts.items():
        assert "reply by" not in message.lower() and " تا " not in message and " ." not in message, (lang, channel, message)
        assert "No date item" in message
    assert texts[("en", "email")].count("validity of your offer.\n\n") == 1
    assert "lead time and validity please.\n" in texts[("en", "whatsapp")]
    assert "مدت اعتبار قیمت.\n" in texts[("fa", "whatsapp")]
    # with a date the sentence is there
    dated = new_rfq(client, case, [item], recipients[:1])
    assert "reply by" in dated["recipients"][0]["message_text"]


def test_expiry_job_repairs_statuses_stored_by_v031(client, db):
    case, (item,) = make_case(client, [{"name": "Stale status item"}])
    expired_rfq(client, case, [item], [supplier(client)])
    rfq_service.expire_no_reply(db)
    # what v0.3.1 stored for this situation
    db.execute(text("UPDATE ops.line_item SET status = 'uncovered' WHERE id = :i"), {"i": item["id"]})
    db.commit()
    from app.modules.sourcing.handlers import expire

    result = expire(db, {})
    db.commit()
    assert result["items_recomputed"] >= 1
    assert item_of(client, item["id"])["status"] == "rfq_sent"
    assert events(client, "line_item", item["id"], "status")[0]["data"]["new_status"] == "rfq_sent"
