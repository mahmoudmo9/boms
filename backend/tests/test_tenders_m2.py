"""v0.6.0 Phase 7b, milestone 2: envelopes and the company documents library, guarantees, tender costs."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from tests.conftest import unique_bytes, upload
from tests.test_listings_store import tag
from tests.test_quotes import ready_case
from tests.test_tenders import at, manual_tender, setad_tender_case
from tests.test_sourcing_inquiries import events


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def library_doc(client, expires_on=None, title=None):
    doc = upload(client, f"reg-{tag()}.txt", unique_bytes("company doc")).json()
    r = client.post("/api/company-documents", json={"title": title or f"آگهی تأسیس {tag()}", "category": "registration",
                                                    "document_id": doc["id"], "expires_on": expires_on})
    assert r.status_code == 201, r.text
    return r.json()


def item_of(t, title_part=None, kind=None):
    return next(i for i in t["envelope_items"] if (kind and i["kind"] == kind) or (title_part and title_part in i["title"]))


# ---- library ---------------------------------------------------------------------------------------------------------

def test_company_documents_expiry_states_and_suggestions(client):
    ok = library_doc(client, day(200))
    soon = library_doc(client, day(10))
    old = library_doc(client, day(-1))
    none = library_doc(client, None)
    states = {d["id"]: d["expiry"] for d in client.get("/api/company-documents").json()}
    assert [states[x["id"]] for x in (ok, soon, old, none)] == ["ok", "soon", "expired", "none"]
    assert {d["id"] for d in client.get("/api/company-documents", params={"expiry": "expired"}).json()} >= {old["id"]}
    sug = client.get("/api/company-documents/suggestions").json()
    assert {"title": "اساسنامه", "category": "registration"} in sug and len(sug) == 8
    cc = client.get("/api/command-center").json()["tenders"]["documents_expiring"]
    assert {soon["id"], old["id"]} <= {d["id"] for d in cc} and ok["id"] not in {d["id"] for d in cc}
    before = len(client.get("/api/company-documents").json())
    r = client.post("/api/company-documents", json={"title": "x", "issued_on": day(5), "expires_on": day(1)})
    assert r.status_code == 422          # a CHECK rule (BOMS convention: rule 422, duplicate 409); nothing stored
    assert r.json()["error"]["details"]["constraint"] == "company_document_dates"
    assert len(client.get("/api/company-documents").json()) == before
    assert client.post("/api/company-documents", json={"title": "x", "bogus": 1}).status_code == 422


# ---- envelopes -------------------------------------------------------------------------------------------------------

def test_envelope_template_copy_add_remove_reorder_and_progress(client):
    case, t, party = manual_tender(client)
    b_items = [i for i in t["envelope_items"] if i["envelope"] == "B"]
    assert len(b_items) == 11 and t["envelope_progress"] == {"A": [0, 1], "B": [0, 11], "C": [0, 2], "all": [0, 14]}
    r = client.post(f"/api/tenders/{t['id']}/envelope-items", json={"envelope": "B", "title": "نمونهٔ کالا"})
    assert r.status_code == 201 and r.json()["envelope_progress"]["B"] == [0, 12]
    new = item_of(r.json(), "نمونهٔ کالا")
    assert new["position"] == 12
    order = [new["id"]] + [i["id"] for i in b_items]
    r = client.post(f"/api/tenders/{t['id']}/envelope-items/reorder", json={"envelope": "B", "item_ids": order})
    assert [i["id"] for i in r.json()["envelope_items"] if i["envelope"] == "B"] == order
    assert client.post(f"/api/tenders/{t['id']}/envelope-items/reorder", json={"envelope": "B", "item_ids": order[:3]}).status_code == 422
    r = client.patch(f"/api/envelope-items/{b_items[0]['id']}", json={"status": "ready"})
    assert r.json()["envelope_progress"]["B"] == [1, 12] and r.json()["envelope_progress"]["all"] == [1, 15]
    r = client.delete(f"/api/envelope-items/{new['id']}")
    assert r.json()["envelope_progress"]["B"] == [1, 11]
    assert [i["position"] for i in r.json()["envelope_items"] if i["envelope"] == "B"] == list(range(1, 12))
    # a template edited in settings, then copied again
    r = client.post("/api/envelope-templates", json={"name": f"کوتاه {tag()}", "lines": [
        {"envelope": "A", "title": "تضمین", "kind": "bid_bond"}, {"envelope": "C", "title": "فرم قیمت", "kind": "price_form"}]})
    assert r.status_code == 201
    r = client.post(f"/api/tenders/{t['id']}/envelope-items/from-template", json={"template_id": r.json()["id"]})
    assert r.json()["envelope_progress"]["all"][1] == 16


def test_library_document_fills_the_item_and_an_expired_one_blocks_ready(client):
    case, t, party = manual_tender(client)
    good, expired = library_doc(client, day(90)), library_doc(client, day(-5))
    item = item_of(t, "آگهی تأسیس")
    r = client.patch(f"/api/envelope-items/{item['id']}", json={"company_document_id": good["id"]})
    filled = next(i for i in r.json()["envelope_items"] if i["id"] == item["id"])
    assert filled["status"] == "ready" and filled["document_id"] == good["document_id"]
    assert filled["company_document"]["expiry"] == "ok"
    other = item_of(t, "اساسنامه")
    r = client.patch(f"/api/envelope-items/{other['id']}", json={"company_document_id": expired["id"]})
    stays = next(i for i in r.json()["envelope_items"] if i["id"] == other["id"])
    assert stays["status"] == "not_ready" and stays["company_document"]["expiry"] == "expired"
    r = client.patch(f"/api/envelope-items/{other['id']}", json={"status": "ready"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "company_document_expired"
    assert r.json()["error"]["details"]["title"] == expired["title"]
    # a library document in use cannot be deleted
    r = client.delete(f"/api/company-documents/{good['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"] == {"envelope_items": 1}


def test_bid_bond_item_follows_the_guarantee(client, db):
    case, t, raw, lid = setad_tender_case(client, db)
    bond = item_of(t, kind="bid_bond")
    gid = bond["guarantee_id"]
    r = client.patch(f"/api/envelope-items/{bond['id']}", json={"status": "ready"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "guarantee_not_issued"
    client.post(f"/api/guarantees/{gid}/status", json={"status": "requested"})
    assert item_of(client.get(f"/api/tenders/{t['id']}").json(), kind="bid_bond")["status"] == "in_progress"
    client.post(f"/api/guarantees/{gid}/status", json={"status": "issued", "valid_until": day(120)})
    assert item_of(client.get(f"/api/tenders/{t['id']}").json(), kind="bid_bond")["status"] == "ready"
    client.post(f"/api/guarantees/{gid}/status", json={"status": "submitted"})
    assert item_of(client.get(f"/api/tenders/{t['id']}").json(), kind="bid_bond")["status"] == "submitted"


# ---- guarantees ------------------------------------------------------------------------------------------------------

def test_guarantee_flow_history_extension_and_reminders(client, db):
    case, t, party = manual_tender(client)
    r = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "bid", "form": "bank",
                                             "amount": "500000000", "bank_name": "بانک ملت", "beneficiary_party_id": party["id"]})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["amount_currency"] == "IRR" and g["status"] == "to_request" and g["reminders"] == []
    for status in ("requested", "issued"):
        g = client.post(f"/api/guarantees/{g['id']}/status", json={"status": status, "valid_until": day(60)}).json()
    assert g["issued_on"] == date.today().isoformat() and g["valid_until"] == day(60)
    assert sorted(x["due_on"] for x in g["reminders"]) == [day(30), day(53)]       # 30 and 7 days before
    r = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "extended"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "valid_until_required"
    r = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "extended", "valid_until": day(40)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "extension_not_later"
    g = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "extended", "valid_until": day(90),
                                                               "reason": "تمدید مهلت مناقصه"}).json()
    assert g["valid_until"] == day(90) and sorted(x["due_on"] for x in g["reminders"]) == [day(60), day(83)]
    kinds = [e["kind"] for e in g["history"]]
    assert kinds == ["status", "requested", "issued", "extended"]
    ext = g["history"][-1]
    assert ext["valid_until"] == day(90) and ext["reason"] == "تمدید مهلت مناقصه" and ext["old_status"] == "issued"
    r = client.delete(f"/api/guarantees/{g['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "guarantee_issued"   # cancel instead
    r = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "cancelled"})
    assert r.status_code == 422                                                      # reason required
    g = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "released", "reason": "اصل ضمانت‌نامه مسترد شد"}).json()
    assert g["status"] == "released" and g["reminders"] == []
    r = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "issued"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "guarantee_closed"
    assert len(events(client, "guarantee", g["id"], "status")) == 4
    listed = client.get("/api/guarantees", params={"purpose": "bid", "status": "released"}).json()
    assert g["id"] in [x["id"] for x in listed]
    # a guarantee not yet issued can be deleted
    draft = client.post("/api/guarantees", json={"case_id": case["id"], "purpose": "performance"}).json()
    assert client.delete(f"/api/guarantees/{draft['id']}").status_code == 204


def test_guarantee_validity_must_cover_the_proposal_validity(client):
    case, t, party = manual_tender(client)
    client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(10)})
    client.patch(f"/api/tenders/{t['id']}", json={"proposal_validity_days": 90})
    g = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "bid"}).json()
    g = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "issued", "valid_until": day(60)}).json()
    assert g["coverage"]["code"] == "guarantee_validity_short" and g["coverage"]["needed_until"] == day(100)
    detail = client.get(f"/api/tenders/{t['id']}").json()
    assert "guarantee_validity_short" in [b["code"] for b in detail["blockers"]]
    g = client.post(f"/api/guarantees/{g['id']}/status", json={"status": "extended", "valid_until": day(100)}).json()
    assert g["coverage"] is None


def test_blocked_deposit_is_shown_with_exposure_and_the_sheet_formula_is_unchanged(client):
    case, items, party, sheet = ready_case(client, country="IR")
    before = client.get(f"/api/cost-sheets/{sheet['id']}").json()["computation"]
    client.post(f"/api/cases/{case['id']}/tender")
    g = client.post("/api/guarantees", json={"case_id": case["id"], "purpose": "bid", "form": "cash_deposit",
                                             "blocked_deposit": "300000000", "fee": "1500000"}).json()
    tied = client.get(f"/api/cases/{case['id']}/guarantees/tied-up").json()
    assert tied == {"IRR": {"blocked_deposit": "300000000.0000", "fee": "1500000.0000", "total": "301500000.0000"}}
    after = client.get(f"/api/cost-sheets/{sheet['id']}").json()["computation"]
    assert after["totals"] == before["totals"] and after.get("exposure") == before.get("exposure")
    client.post(f"/api/guarantees/{g['id']}/status", json={"status": "cancelled", "reason": "شرکت نکردیم"})
    assert client.get(f"/api/cases/{case['id']}/guarantees/tied-up").json() == {}


# ---- costs ---------------------------------------------------------------------------------------------------------

def test_costs_totals_refundable_and_add_to_cost_sheet(client):
    case, items, party, sheet = ready_case(client, country="IR")
    t = client.post(f"/api/cases/{case['id']}/tender").json()
    for body in ({"kind": "documents_purchase", "amount": "1500000", "paid_on": day(0)},
                 {"kind": "deposit", "amount": "50000000", "paid_on": day(0)},
                 {"kind": "travel", "amount": "2000000"},
                 {"kind": "guarantee_fee", "amount": "750000", "paid_on": day(0)}):
        r = client.post(f"/api/tenders/{t['id']}/costs", json=body)
        assert r.status_code == 201, r.text
    t = r.json()
    deposit = next(c for c in t["costs"] if c["kind"] == "deposit")
    assert deposit["refundable"] is True
    tot = t["cost_totals"]["IRR"]
    assert Decimal(tot["spent"]) == Decimal("52250000") and Decimal(tot["refundable_outstanding"]) == Decimal("50000000")
    assert Decimal(tot["unpaid"]) == Decimal("2000000") and Decimal(tot["net"]) == Decimal("4250000")
    t = client.patch(f"/api/tender-costs/{deposit['id']}", json={"refunded_on": day(0)}).json()
    assert Decimal(t["cost_totals"]["IRR"]["refundable_outstanding"]) == 0 and Decimal(t["cost_totals"]["IRR"]["refunded"]) == Decimal("50000000")
    # the sheet is final: no draft to add to
    r = client.post(f"/api/tenders/{t['id']}/costs/to-sheet")
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_draft_sheet"
    new = client.post(f"/api/cost-sheets/{sheet['id']}/new-version").json()
    r = client.post(f"/api/tenders/{t['id']}/costs/to-sheet")
    assert r.status_code == 200, r.text
    lines = client.get(f"/api/cost-sheets/{new['id']}").json()["lines"]
    line = next(x for x in lines if x["label"] == "هزینه شرکت در مناقصه")
    assert Decimal(line["amount"]) == Decimal("4250000") and line["scope"] == "case" and line["kind"] == "other"
