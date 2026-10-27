"""Costing API: templates, tax parameters, cost sheets (prefill, versions, FX, warnings) and the quote gate."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.modules.parties import clock
from tests.test_parties import tag
from tests.test_sourcing_inquiries import audit_ops, events
from tests.test_sourcing_rfq import make_case, offer_body, supplier

TODAY = date.today()


def day(n: int = 0) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


def selected_case(client, currencies=("USD", "EUR"), valid_days=30):
    """A case with two items, each with a selected offer (one per currency)."""
    case, items = make_case(client, [{"name": "Valve", "quantity": "10", "unit_code": "pc"},
                                     {"name": "Pump", "quantity": "2", "unit_code": "pc"}])
    offers = []
    for item, currency, price in zip(items, currencies, ("12.5", "300")):
        party = supplier(client)
        off = client.post("/api/offers", json=offer_body(case, party, [{"line_item_id": item["id"], "unit_price": price}],
                                                         currency=currency, valid_until=day(valid_days))).json()
        r = client.post(f"/api/line-items/{item['id']}/select", json={"offer_item_id": off["items"][0]["id"]})
        assert r.status_code == 200, r.text
        offers.append(off)
    return case, items, offers


def new_sheet(client, case, **extra):
    r = client.post("/api/cost-sheets", json={"case_id": case["id"], "deal_type": "import", "pricing_currency": "IRR",
                                              **extra})
    assert r.status_code == 201, r.text
    return r.json()


def priced_sheet(client, case, fx_age=0):
    sheet = new_sheet(client, case)
    sid = sheet["id"]
    client.put(f"/api/cost-sheets/{sid}/fx", json={"from_currency": "USD", "to_currency": "IRR", "rate": "600000",
                                                   "rate_kind": "free market", "source_note": "exchange shop",
                                                   "as_of": day(-fx_age)})
    client.put(f"/api/cost-sheets/{sid}/fx", json={"from_currency": "EUR", "to_currency": "IRR", "rate": "650000",
                                                   "rate_kind": "free market", "as_of": day(-fx_age)})
    for line in sheet["lines"]:
        if line["kind"] != "purchase" and line["basis"] == "total":
            client.patch(f"/api/cost-sheets/lines/{line['id']}", json={"amount": "10000000", "currency": "IRR"})
        elif line["basis"].startswith("percent") and line["percent"] is None:
            client.patch(f"/api/cost-sheets/lines/{line['id']}", json={"percent": "4"})
    r = client.patch(f"/api/cost-sheets/{sid}", json={"pricing_method": "margin", "target_percent": "20"})
    assert r.status_code == 200, r.text
    return r.json()


def test_create_from_import_template_prefills_purchase_lines(client, db):
    case, items, offers = selected_case(client)
    sheet = new_sheet(client, case, language="en")
    assert sheet["version"] == 1 and sheet["status"] == "draft" and sheet["decimals"] == 0  # IRR: whole rials
    purchase = [ln for ln in sheet["lines"] if ln["kind"] == "purchase"]
    assert [(ln["line_item_id"], ln["amount"], ln["currency"], ln["basis"]) for ln in purchase] == [
        (items[0]["id"], "12.5000", "USD", "per_unit"), (items[1]["id"], "300.0000", "EUR", "per_unit")]
    assert purchase[0]["source_offer_item_id"] == offers[0]["items"][0]["id"]
    kinds = [ln["kind"] for ln in sheet["lines"]]
    assert kinds == ["purchase", "purchase", "freight_international", "insurance", "bank_fees", "customs_duty", "levy",
                     "customs_clearance", "storage", "inspection", "freight_domestic"]
    assert sheet["lines"][2]["label"] == "International freight" and sheet["lines"][2]["scope"] == "case"
    # without FX the computation names the missing pair
    assert sheet["computation"] is None and sheet["compute_error"]["code"] == "fx_missing"
    r = client.get(f"/api/cost-sheets/{sheet['id']}/computation")
    assert r.status_code == 422 and r.json()["error"]["details"] == {"from_currency": "USD", "to_currency": "IRR"}
    assert audit_ops(db, "ops.cost_sheet", sheet["id"]) == ["I"]
    assert events(client, "cost_sheet", sheet["id"], "create")[0]["data"]["lines"] == 11


def test_priced_sheet_numbers_and_breakdown(client):
    case, items, _ = selected_case(client)
    sheet = priced_sheet(client, case)
    c = sheet["computation"]
    # purchase: 10 x 12.5 USD x 600,000 = 75,000,000; 2 x 300 EUR x 650,000 = 390,000,000
    rows = {r["item_id"]: r for r in c["items"]}
    assert (rows[items[0]["id"]]["purchase"], rows[items[1]["id"]]["purchase"]) == ("75000000", "390000000")
    assert c["totals"]["margin_percent"] == "20.00" and c["totals"]["markup_percent"] == "25.00"
    assert all(Decimal(r["total_price"]) == Decimal(r["total_price"]).to_integral() for r in c["items"])
    freight = next(ln for ln in c["lines"] if ln["kind"] == "freight_international")
    assert sum(Decimal(v) for v in freight["shares"].values()) == Decimal(10000000)
    assert {f["from_currency"] for f in c["fx_used"]} == {"USD", "EUR"}
    assert sheet["gate"]["failures"] == [{"code": "sheet_not_final", "status": "draft"}]
    # the default validity (7 days) is capped at the FX age limit (3 days)
    assert sheet["gate"]["valid_until"] == day(3) and sheet["gate"]["valid_until_capped"] is True


def test_invalid_selected_offer_warns(client):
    case, items, offers = selected_case(client)
    sheet = new_sheet(client, case)
    client.post(f"/api/offers/{offers[0]['id']}/status", json={"status": "withdrawn", "note": "price changed"})
    codes = [w["code"] for w in client.get(f"/api/cost-sheets/{sheet['id']}").json()["warnings"]]
    assert "offer_invalid" in codes and "selection_changed" in codes
    # the line is kept (not silently dropped)
    assert any(ln["source_offer_item_id"] == offers[0]["items"][0]["id"]
               for ln in client.get(f"/api/cost-sheets/{sheet['id']}").json()["lines"])


def test_versioning_final_read_only_and_superseded(client, db):
    case, _, _ = selected_case(client)
    first = priced_sheet(client, case)
    r = client.post(f"/api/cost-sheets/{first['id']}/finalize")
    assert r.status_code == 200 and r.json()["status"] == "final"
    r = client.patch(f"/api/cost-sheets/{first['id']}", json={"target_percent": "30"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "sheet_not_draft"
    line = first["lines"][0]
    assert client.patch(f"/api/cost-sheets/lines/{line['id']}", json={"amount": "1"}).status_code == 409
    assert client.delete(f"/api/cost-sheets/{first['id']}").status_code == 409
    second = client.post(f"/api/cost-sheets/{first['id']}/new-version").json()
    assert second["version"] == 2 and second["status"] == "draft"
    assert len(second["lines"]) == len(first["lines"]) and len(second["fx"]) == 2
    assert second["computation"]["totals"] == first["computation"]["totals"]
    client.patch(f"/api/cost-sheets/{second['id']}", json={"target_percent": "25"})
    client.post(f"/api/cost-sheets/{second['id']}/finalize")
    assert client.get(f"/api/cost-sheets/{first['id']}").json()["status"] == "superseded"
    summary = client.get(f"/api/cases/{case['id']}/costing").json()
    assert summary["current"]["version"] == 2 and summary["current"]["margin_percent"] == "25.00"
    assert [s["status"] for s in summary["sheets"]] == ["final", "superseded"]
    assert events(client, "cost_sheet", first["id"], "superseded")
    # drafts can be deleted
    third = client.post(f"/api/cost-sheets/{second['id']}/new-version").json()
    assert client.delete(f"/api/cost-sheets/{third['id']}").status_code == 204
    assert audit_ops(db, "ops.cost_sheet", third["id"])[-1] == "D"


def test_tax_parameter_selected_by_effective_date_and_unconfirmed_warning(client):
    kind_name = f"Duty {tag()}"
    old = client.post("/api/tax-parameters", json={"kind": "duty_default", "name": kind_name, "rate_percent": "4",
                                                   "deal_type": "import", "effective_from": "2020-01-01",
                                                   "effective_to": day(-31)}).json()
    new = client.post("/api/tax-parameters", json={"kind": "duty_default", "name": kind_name, "rate_percent": "6",
                                                   "deal_type": "import", "effective_from": day(-30)}).json()
    r = client.get("/api/tax-parameters/in-force", params={"kind": "duty_default", "deal_type": "import", "on": day(-40)})
    assert r.json()["id"] == old["id"]
    assert client.get("/api/tax-parameters/in-force", params={"kind": "duty_default", "deal_type": "import",
                                                              "on": day()}).json()["id"] == new["id"]
    # a rate is never overwritten: PATCH cannot change it
    r = client.patch(f"/api/tax-parameters/{new['id']}", json={"rate_percent": "7"})
    assert r.status_code == 422
    case, _, _ = selected_case(client)
    sheet = new_sheet(client, case)
    duty = next(ln for ln in sheet["lines"] if ln["kind"] == "customs_duty")
    assert duty["tax_parameter_id"] == new["id"] and duty["percent"] == "6.0000"
    old_sheet = new_sheet(client, case, sheet_date=day(-40))
    assert next(ln for ln in old_sheet["lines"] if ln["kind"] == "customs_duty")["percent"] == "4.0000"
    assert "unconfirmed_parameter" in [w["code"] for w in sheet["warnings"]]
    r = client.patch(f"/api/tax-parameters/{new['id']}", json={"confirmed_by": "Mr. Karimi (accountant)",
                                                                "confirmed_on": day()})
    assert r.status_code == 200
    assert "unconfirmed_parameter" not in [w["code"] for w in client.get(f"/api/cost-sheets/{sheet['id']}").json()["warnings"]]
    # in use -> cannot be deleted
    assert client.delete(f"/api/tax-parameters/{new['id']}").json()["error"]["code"] == "in_use"


def test_stale_fx_warns_fails_gate_and_override_is_an_event(client, monkeypatch):
    case, _, _ = selected_case(client)
    sheet = priced_sheet(client, case, fx_age=10)
    assert "fx_stale" in [w["code"] for w in sheet["warnings"]]
    client.post(f"/api/cost-sheets/{sheet['id']}/finalize")
    gate = client.get(f"/api/cost-sheets/{sheet['id']}/gate").json()
    codes = [f["code"] for f in gate["failures"]]
    assert "fx_stale" in codes
    r = client.post(f"/api/cost-sheets/{sheet['id']}/override", json={"kind": "fx_stale", "reason": ""})
    assert r.status_code == 422
    r = client.post(f"/api/cost-sheets/{sheet['id']}/override", json={"kind": "fx_stale", "reason": "rate re-checked by phone"})
    assert r.status_code == 200
    gate = client.get(f"/api/cost-sheets/{sheet['id']}/gate").json()
    assert "fx_stale" not in [f["code"] for f in gate["failures"]]
    ev = events(client, "cost_sheet", sheet["id"], "gate_override")[0]["data"]
    assert ev == {"kind": "fx_stale", "reason": "rate re-checked by phone"}


def test_gate_reports_every_failure_together_then_passes(client):
    case, items, _ = selected_case(client, valid_days=5)
    sheet = new_sheet(client, case)
    param = client.post("/api/tax-parameters", json={"kind": "levy", "name": f"Levy {tag()}", "rate_percent": "1",
                                                     "deal_type": "all", "effective_from": "2020-01-01"}).json()
    sid = sheet["id"]
    client.put(f"/api/cost-sheets/{sid}/fx", json={"from_currency": "USD", "to_currency": "IRR", "rate": "600000",
                                                   "as_of": day(-9)})
    client.put(f"/api/cost-sheets/{sid}/fx", json={"from_currency": "EUR", "to_currency": "IRR", "rate": "650000",
                                                   "as_of": day(-9)})
    levy = next(ln for ln in sheet["lines"] if ln["kind"] == "levy")
    client.patch(f"/api/cost-sheets/lines/{levy['id']}", json={"tax_parameter_id": param["id"]})
    client.patch(f"/api/cost-sheets/{sid}", json={"pricing_method": "margin", "target_percent": "20",
                                                  "min_acceptable_price": "999999999999", "validity_days": 30})
    gate = client.get(f"/api/cost-sheets/{sid}/gate", params={"valid_until": day(30)}).json()
    codes = {f["code"] for f in gate["failures"]}
    assert {"sheet_not_final", "lines_incomplete", "below_minimum", "validity_too_long", "unconfirmed_parameter",
            "fx_stale"} <= codes, codes
    too_long = next(f for f in gate["failures"] if f["code"] == "validity_too_long")
    assert too_long["max_valid_until"] == day(-9 + 3)  # FX age limit is earlier than the offers' validity (5 days)

    # fix everything
    for line in client.get(f"/api/cost-sheets/{sid}").json()["lines"]:
        if line["kind"] != "purchase" and line["basis"] == "total" and line["amount"] is None:
            client.patch(f"/api/cost-sheets/lines/{line['id']}", json={"amount": "0", "currency": "IRR"})
        elif line["basis"].startswith("percent") and line["percent"] is None:
            client.patch(f"/api/cost-sheets/lines/{line['id']}", json={"percent": "0"})
    for cur, rate in (("USD", "600000"), ("EUR", "650000")):
        client.put(f"/api/cost-sheets/{sid}/fx", json={"from_currency": cur, "to_currency": "IRR", "rate": rate, "as_of": day()})
    client.patch(f"/api/cost-sheets/{sid}", json={"min_acceptable_price": "1", "validity_days": 3})
    client.post(f"/api/cost-sheets/{sid}/override", json={"kind": "unconfirmed_parameter", "reason": "adviser on leave"})
    client.post(f"/api/cost-sheets/{sid}/finalize")
    gate = client.get(f"/api/cost-sheets/{sid}/gate").json()
    assert gate["ok"] is True, gate
    # validity can never exceed the earliest offer validity (5 days) nor the FX limit (3 days)
    gate = client.get(f"/api/cost-sheets/{sid}/gate", params={"valid_until": day(4)}).json()
    assert [f["code"] for f in gate["failures"]] == ["validity_too_long"]
    assert gate["max_valid_until"] == day(3)


def test_margin_100_rejected_and_rounding_needs_step(client):
    case, _, _ = selected_case(client)
    sheet = new_sheet(client, case)
    r = client.patch(f"/api/cost-sheets/{sheet['id']}", json={"pricing_method": "margin", "target_percent": "100"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_margin"
    r = client.patch(f"/api/cost-sheets/{sheet['id']}", json={"rounding": "up"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "rounding_step_required"
    r = client.patch(f"/api/cost-sheets/{sheet['id']}", json={"rounding": "up", "rounding_step": "1000"})
    assert r.status_code == 200


def test_line_rules_and_manual_price(client):
    case, items, _ = selected_case(client)
    sheet = priced_sheet(client, case)
    sid = sheet["id"]
    r = client.post(f"/api/cost-sheets/{sid}/lines", json={"kind": "other", "label": "x", "scope": "item"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "item_required"
    r = client.post(f"/api/cost-sheets/{sid}/lines", json={"kind": "other", "label": "x", "basis": "percent_of_cif",
                                                           "amount": "5", "currency": "USD"})
    assert r.json()["error"]["code"] == "amount_not_allowed"
    r = client.post(f"/api/cost-sheets/{sid}/lines", json={"kind": "other", "label": "Agent", "amount": "300",
                                                           "currency": "USD", "allocation": "manual",
                                                           "manual_shares": {items[0]["id"]: "1", items[1]["id"]: "2"}})
    assert r.status_code == 201, r.text
    agent = next(ln for ln in client.get(f"/api/cost-sheets/{sid}").json()["computation"]["lines"]
                 if ln["line_id"] == r.json()["id"])
    assert agent["shares"] == {items[0]["id"]: "60000000", items[1]["id"]: "120000000"}
    r = client.patch(f"/api/cost-sheets/{sid}", json={"price_overrides": {items[0]["id"]: "9999999"}})
    row = next(i for i in r.json()["computation"]["items"] if i["item_id"] == items[0]["id"])
    assert row["manual"] is True and row["unit_price"] == "9999999"
    assert client.post(f"/api/cost-sheets/{sid}/lines", json={"kind": "other", "label": "x", "bogus": 1}).status_code == 422


def test_templates_edit_reorder_archive_and_delete_rules(client):
    t = client.post("/api/cost-templates", json={"name": f"Air import {tag()}", "deal_type": "import", "lines": [
        {"kind": "purchase", "label_en": "Purchase", "basis": "per_unit"},
        {"kind": "freight_international", "label_en": "Air freight", "basis": "total", "paid_before_receipt": True}]}).json()
    assert [ln["position"] for ln in t["lines"]] == [1, 2]
    r = client.patch(f"/api/cost-templates/{t['id']}", json={"lines": [
        {"kind": "freight_international", "label_en": "Air freight", "basis": "total"},
        {"kind": "purchase", "label_en": "Purchase", "basis": "per_unit"},
        {"kind": "inspection", "label_fa": "بازرسی", "basis": "total", "allocation": "equal"}]})
    assert [ln["kind"] for ln in r.json()["lines"]] == ["freight_international", "purchase", "inspection"]
    defaults = [x for x in client.get("/api/cost-templates").json() if x["is_default"]]
    assert sorted(x["deal_type"] for x in defaults) == ["domestic", "export", "import"]
    case, _, _ = selected_case(client)
    new_sheet(client, case, template_id=t["id"])
    assert client.delete(f"/api/cost-templates/{t['id']}").json()["error"]["code"] == "in_use"
    assert client.patch(f"/api/cost-templates/{t['id']}", json={"status": "archived"}).json()["status"] == "archived"
    assert t["id"] not in [x["id"] for x in client.get("/api/cost-templates").json()]
    loose = client.post("/api/cost-templates", json={"name": f"Loose {tag()}", "deal_type": "domestic"}).json()
    assert client.delete(f"/api/cost-templates/{loose['id']}").status_code == 204
    r = client.post("/api/cost-templates", json={"name": "x", "deal_type": "import", "lines": [], "bogus": True})
    assert r.status_code == 422


def test_blank_sheet_and_export_template(client):
    case, _, _ = selected_case(client)
    blank = new_sheet(client, case, blank=True)
    assert blank["template_id"] is None and {ln["kind"] for ln in blank["lines"]} == {"purchase"}
    export = new_sheet(client, case, deal_type="export", language="fa")
    assert export["lines"][2]["label"] == "حمل داخلی تا بندر/مرز"
    r = client.post("/api/cost-sheets", json={"case_id": case["id"], "deal_type": "import", "pricing_currency": "ZZZ"})
    assert r.status_code == 422


def test_search_finds_cost_sheets(client):
    word = f"Sheetsearch{tag()}"
    case, _ = make_case(client, [{"name": "Item"}], title=f"Case {word}")
    sheet = new_sheet(client, case, blank=True, notes=f"note {word}")
    groups = {g["type"]: [h["id"] for h in g["items"]]
              for g in client.get("/api/search", params={"q": word, "limit": 20}).json()["groups"]}
    assert sheet["id"] in groups["cost_sheet"]
