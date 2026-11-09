"""v0.5.0 section 0: carry-over fixes from v0.4.0 (costing gate, quote approval, terms text, numbering, digits)."""

from datetime import date
from decimal import Decimal

from app.modules.sourcing.jalali import to_jalali

from tests.test_costing import day, new_sheet, priced_sheet, selected_case
from tests.test_quotes import buyer, new_quote, ready_case
from tests.test_sourcing_inquiries import events
from tests.test_sourcing_rfq import contact, new_rfq, supplier


FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def approved(client, quote):
    r = client.post(f"/api/quotes/{quote['id']}/approve")
    assert r.status_code == 200, r.text
    return r.json()


# ---- 1. prices below cost or minimum at approval -------------------------------------------------------

def test_price_below_cost_needs_confirmation_and_reason(client):
    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case)
    row = quote["items"][0]
    below = str((Decimal(row["unit_cost"]) - 1).quantize(Decimal(1)))
    assert client.patch(f"/api/quotes/items/{row['id']}", json={"unit_price": below}).status_code == 200
    r = client.post(f"/api/quotes/{quote['id']}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "below_cost"
    listed = r.json()["error"]["details"]["items"]
    assert [x["quote_item_id"] for x in listed] == [row["id"]] and Decimal(listed[0]["unit_price"]) == Decimal(below)
    r = client.post(f"/api/quotes/{quote['id']}/approve", json={"confirm_below_cost": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    assert client.get(f"/api/quotes/{quote['id']}").json()["status"] == "draft"
    r = client.post(f"/api/quotes/{quote['id']}/approve", json={"confirm_below_cost": True, "reason": "market entry"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/quotes/{quote['id']}").json()["status"] == "approved"
    logged = events(client, "quote", quote["id"], "approve_below_cost")
    assert len(logged) == 1 and logged[0]["data"]["reason"] == "market entry"


def test_price_below_the_per_item_minimum_set_on_the_sheet(client):
    case, items, offers = selected_case(client)
    party = buyer(client)
    client.patch(f"/api/cases/{case['id']}", json={"party_id": party["id"]})
    sheet = priced_sheet(client, case)
    first = next(r for r in sheet["computation"]["items"] if r["item_id"] == items[0]["id"])
    minimum = str(Decimal(first["unit_price"]) - 10)
    client.patch(f"/api/cost-sheets/{sheet['id']}", json={"item_min_prices": {items[0]["id"]: minimum}})
    assert client.post(f"/api/cost-sheets/{sheet['id']}/finalize").status_code == 200
    quote = new_quote(client, case)
    row = next(i for i in quote["items"] if i["line_item_id"] == items[0]["id"])
    assert Decimal(row["min_unit_price"]) == Decimal(minimum)
    client.patch(f"/api/quotes/items/{row['id']}", json={"unit_price": str(Decimal(minimum) - 1)})
    r = client.post(f"/api/quotes/{quote['id']}/approve", json={"confirm_below_cost": True, "reason": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "gate_failed"
    assert {"code": "item_below_minimum", "item_ids": [items[0]["id"]]} in r.json()["error"]["details"]["failures"]


# ---- 2 and 3. unused template lines, finalize while the gate fails ------------------------------------

def _sheet_with_unfilled_lines(client):
    case, items, offers = selected_case(client)
    sheet = new_sheet(client, case)
    sid = sheet["id"]
    for cur, rate in (("USD", "600000"), ("EUR", "650000")):
        client.put(f"/api/cost-sheets/{sid}/fx", json={"from_currency": cur, "to_currency": "IRR", "rate": rate,
                                                       "as_of": day(0)})
    client.patch(f"/api/cost-sheets/{sid}", json={"pricing_method": "margin", "target_percent": "20"})
    return case, client.get(f"/api/cost-sheets/{sid}").json()


def test_finalize_refuses_a_failing_gate_unless_confirmed(client):
    case, sheet = _sheet_with_unfilled_lines(client)
    unfilled = [ln["id"] for ln in sheet["lines"] if ln["kind"] != "purchase"]
    assert sorted(sheet["unfilled_line_ids"]) == sorted(unfilled)
    r = client.post(f"/api/cost-sheets/{sheet['id']}/finalize")
    assert r.status_code == 409 and r.json()["error"]["code"] == "gate_failing"
    codes = [f["code"] for f in r.json()["error"]["details"]["failures"]]
    assert "lines_incomplete" in codes and "sheet_not_final" not in codes
    assert client.get(f"/api/cost-sheets/{sheet['id']}").json()["status"] == "draft"
    r = client.post(f"/api/cost-sheets/{sheet['id']}/finalize", json={"confirm": True})
    assert r.status_code == 200 and r.json()["status"] == "final"
    logged = events(client, "cost_sheet", sheet["id"], "finalize")
    assert "lines_incomplete" in logged[0]["data"]["confirmed_failures"]


def test_treat_unfilled_lines_as_not_applicable(client):
    case, sheet = _sheet_with_unfilled_lines(client)
    r = client.post(f"/api/cost-sheets/{sheet['id']}/lines/not-applicable")
    assert r.status_code == 200, r.text
    after = r.json()
    assert after["unfilled_line_ids"] == []
    marked = [ln for ln in after["lines"] if ln["id"] in sheet["unfilled_line_ids"]]
    assert marked and all(ln["notes"] == "N/A" for ln in marked)
    assert all((ln["percent"] if ln["basis"].startswith("percent") else ln["amount"]) in ("0", "0.0000") for ln in marked)
    assert all(f["code"] != "lines_incomplete" for f in after["gate"]["failures"])
    assert client.post(f"/api/cost-sheets/{sheet['id']}/finalize").status_code == 200
    assert len(events(client, "cost_sheet", sheet["id"], "lines_not_applicable")) == 1


def test_remove_unused_lines_keeps_purchase_lines(client):
    case, sheet = _sheet_with_unfilled_lines(client)
    # an empty purchase line stays (it means an unpriced item)
    purchase = next(ln for ln in sheet["lines"] if ln["kind"] == "purchase")
    client.patch(f"/api/cost-sheets/lines/{purchase['id']}", json={"amount": None})
    r = client.post(f"/api/cost-sheets/{sheet['id']}/lines/remove-unused")
    assert r.status_code == 200, r.text
    kinds = [ln["kind"] for ln in r.json()["lines"]]
    assert kinds == ["purchase", "purchase"]
    assert r.json()["unfilled_line_ids"] == [purchase["id"]]
    assert len(events(client, "cost_sheet", sheet["id"], "lines_remove_unused")[0]["data"]["deleted"]) == 9


def test_final_sheet_lines_cannot_be_marked_or_removed(client):
    case, sheet = _sheet_with_unfilled_lines(client)
    client.post(f"/api/cost-sheets/{sheet['id']}/finalize", json={"confirm": True})
    for path in ("not-applicable", "remove-unused"):
        r = client.post(f"/api/cost-sheets/{sheet['id']}/lines/{path}")
        assert r.status_code == 409 and r.json()["error"]["code"] == "sheet_not_draft"


# ---- 4 and 6. terms text: empty lines omitted, automatic rebuild, hand edits kept ----------------------

def test_terms_omit_empty_lines_in_both_languages_and_outputs(client):
    for country, lang, labels in (("AE", "en", ("Payment terms:", "Lead time:", "Bank details:")),
                                  ("IR", "fa", ("شرایط پرداخت:", "زمان تحویل:", "مشخصات بانکی:"))):
        client.patch("/api/settings", json={"company.bank_details": {"en": "", "fa": ""}})
        case, items, party, sheet = ready_case(client, country=country)
        quote = new_quote(client, case)
        assert quote["language"] == lang and not quote["payment_terms"] and quote["lead_time_days"] is None
        for label in labels:
            assert label not in quote["terms_text"], (lang, label, quote["terms_text"])
        assert not quote["terms_text"].endswith("\n")
        html = client.get(f"/api/quotes/{quote['id']}/print").text
        assert labels[0] not in html
    # a hand-written label without value is dropped from the outputs too
    client.patch(f"/api/quotes/{quote['id']}", json={"terms_text": "شرایط پرداخت:\n\nاعتبار: یک هفته"})
    html = client.get(f"/api/quotes/{quote['id']}/print").text
    assert "شرایط پرداخت:" not in html and "اعتبار: یک هفته" in html


def test_terms_rebuild_automatically_until_edited_by_hand(client):
    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case)
    assert quote["terms_manual"] is False
    r = client.patch(f"/api/quotes/{quote['id']}", json={"payment_terms": "30% advance", "lead_time_days": 45})
    terms = r.json()["terms_text"]
    assert "Payment terms: 30% advance" in terms and "Lead time: 45 days" in terms
    client.patch(f"/api/quotes/{quote['id']}", json={"incoterm": "CIF", "incoterm_place": "Bandar Abbas"})
    assert "Delivery terms: CIF Bandar Abbas" in client.get(f"/api/quotes/{quote['id']}").json()["terms_text"]
    # edited by hand: later changes leave the text alone
    mine = "Special terms agreed by phone."
    r = client.patch(f"/api/quotes/{quote['id']}", json={"terms_text": mine})
    assert r.json()["terms_manual"] is True
    r = client.patch(f"/api/quotes/{quote['id']}", json={"lead_time_days": 60})
    assert r.json()["terms_text"] == mine and r.json()["terms_manual"] is True
    # rebuild from template on request
    r = client.post(f"/api/quotes/{quote['id']}/terms")
    assert r.status_code == 200 and r.json()["terms_manual"] is False and "Lead time: 60 days" in r.json()["terms_text"]
    updates = [e for e in events(client, "quote", quote["id"], "update") if "terms_text" in e["data"]["changes"]]
    assert len(updates) >= 3


# ---- 5. Persian digits in generated texts -------------------------------------------------------------

def test_persian_digits_follow_the_user_setting(client):
    try:
        client.patch("/api/me", json={"digits": "fa"})
        case, items, party, sheet = ready_case(client, country="IR")
        quote = new_quote(client, case, lead_time_days=45)
        assert quote["language"] == "fa"
        assert "۴۵ روز" in quote["terms_text"] and "45" not in quote["terms_text"]
        y, m, d = to_jalali(date.fromisoformat(quote["valid_until"]))
        assert f"{y:04d}/{m:02d}/{d:02d}".translate(FA) in quote["terms_text"]
        # RFQ texts in Persian: the reply-by date and quantities in Persian digits
        sup = supplier(client, country="IR")
        contact(client, sup["id"], email="ali.1402@example.com")
        rfq = new_rfq(client, case, items[:1], [{"party_id": sup["id"], "language": "fa"}], respond_by=day(5))
        text = rfq["recipients"][0]["message_text"]
        assert "مقدار: ۱۰" in text and "۱. " in text
        assert not any(d in text for d in "0123456789"), text
        client.patch("/api/me", json={"digits": "latin"})
        latin = new_quote(client, ready_case(client, country="IR")[0], lead_time_days=45)
        # v0.7.0 section 0: a Persian quote (an output document) uses Persian digits whatever the user chose
        assert "۴۵ روز" in latin["terms_text"]
    finally:
        client.patch("/api/me", json={"digits": "latin"})


# ---- 7. revision numbers ----------------------------------------------------------------------------

def test_revisions_keep_the_base_number_with_a_version_suffix(client):
    case, items, party, sheet = ready_case(client)
    first = new_quote(client, case)
    base = first["number"]
    approved(client, first)
    v2 = client.post(f"/api/quotes/{first['id']}/revise", json={}).json()
    assert v2["number"] == f"{base}-v2"
    approved(client, v2)
    v3 = client.post(f"/api/quotes/{v2['id']}/revise", json={}).json()
    assert v3["number"] == f"{base}-v3"
    # the gap-free base sequence counted only the first version
    other_case = ready_case(client)[0]
    following = new_quote(client, other_case)["number"]
    assert following.rsplit("-", 1)[0] == base.rsplit("-", 1)[0]
    assert int(following.rsplit("-", 1)[1]) == int(base.rsplit("-", 1)[1]) + 1
    out = client.post(f"/api/quotes/{v3['id']}/outputs", json={"format": "docx"}).json()
    assert out["filename"].startswith(f"{base}_ProformaInvoice_") and out["filename"].endswith("_v3_DRAFT.docx")
