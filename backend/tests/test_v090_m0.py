"""v0.9.0 milestone 0: cost of money and guarantee fees as profit lines (planned, actual, snapshot), the VAT decision on
the first domestic invoice, the draft credit note of a customer claim, search ranking with exact codes first and actual
costs searchable, coverage statuses from selected onward."""
from decimal import Decimal

from tests.test_execution_m1 import day
from tests.test_finance_m2 import import_deal
from tests.test_finance_m3 import settled
from tests.test_sourcing_inquiries import events

D = Decimal


def test_cost_of_money_and_guarantee_are_profit_lines_and_in_the_snapshot(client):
    case, party, sup, so, po, inv, pi = settled(client)
    g = client.post("/api/guarantees", json={"case_id": case["id"], "purpose": "performance", "fee": "1500000",
                                             "fee_currency": "IRR", "valid_until": day(-1)}).json()
    client.post(f"/api/guarantees/{g['id']}/status", json={"status": "released"})
    p = client.get(f"/api/cases/{case['id']}/profit").json()
    rows = {r["kind"]: r for r in p["rows"]}
    assert D(rows["guarantee"]["actual"]["base"]) == 1_500_000                    # the fee is its own line, not bank fees
    com = rows["cost_of_money"]                                                    # USD paid on day −3, money in on day 0
    assert D(com["actual"]["base"]) == D(p["cost_of_money"]["actual"]["base"]) > 0
    assert D(p["cost"]["actual"]["base"]) == sum(D(r["actual"]["base"]) for r in p["rows"])
    check = client.get(f"/api/cases/{case['id']}/close-checklist").json()
    snap = client.post(f"/api/cases/{case['id']}/close", json={"reasons": {x["code"]: "x" for x in check["problems"]},
                                                               "confirm_cancel_open": True}).json()
    kinds = {r["kind"] for r in snap["rows"]}
    assert {"guarantee", "cost_of_money"} <= kinds and snap["frozen"] is True


def test_planned_cost_includes_the_sheets_cost_of_money_and_guarantee(client, db):
    from uuid import UUID

    from app.modules.finance import profit

    case, party, sup, so, po = import_deal(client)
    p = profit.plan(db, UUID(case["id"]))
    assert set(p["by_kind"]) >= {"cost_of_money", "guarantee"}
    assert p["cost"] == sum(p["by_kind"].values())


def test_vat_decision_on_the_first_domestic_invoice(client, monkeypatch):
    from app.modules.costing import service as costing

    real = costing.parameter_in_force

    class Vat:
        rate_percent = Decimal("10")

    monkeypatch.setattr(costing, "parameter_in_force",
                        lambda db, kind, deal_type, on: Vat() if kind == "vat" else real(db, kind, deal_type, on))
    case, party, sup, so, po = import_deal(client)
    assert client.patch("/api/settings", json={"finance.vat_default_domestic": None}).status_code == 200
    try:
        inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]}).json()
        r = client.post(f"/api/sales-invoices/{inv['id']}/issue")
        assert r.status_code == 409 and r.json()["error"]["code"] == "vat_decision_required"
        assert r.json()["error"]["details"] == {"rate": "10.0000", "issue_date": day(0)} or \
            D(r.json()["error"]["details"]["rate"]) == 10
        r = client.post(f"/api/sales-invoices/{inv['id']}/issue", json={"vat_decision": "zero"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "vat_reason_required"
        r = client.post(f"/api/sales-invoices/{inv['id']}/issue", json={"vat_decision": "zero", "vat_reason": "کالای معاف"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert D(out["vat_rate"]) == 0 and out["vat_note"] == "کالای معاف" and D(out["vat_amount"]) == 0
        assert client.get("/api/settings").json()["values"]["finance.vat_default_domestic"] == {"mode": "zero", "reason": "کالای معاف"}
        # later invoices use the default without asking, still editable with a note
        case2, party2, sup2, so2, po2 = import_deal(client)
        client.patch("/api/settings", json={"finance.vat_default_domestic": None})
        client.patch("/api/settings", json={"finance.vat_default_domestic": {"mode": "apply"}})
        inv2 = client.post("/api/sales-invoices", json={"sales_order_id": so2["id"]}).json()
        assert D(inv2["vat_rate"]) == 10
        assert client.post(f"/api/sales-invoices/{inv2['id']}/issue").status_code == 200
    finally:
        client.patch("/api/settings", json={"finance.vat_default_domestic": {"mode": "apply"}})


def test_a_customer_claim_discount_drafts_a_credit_note(client, db):
    case, party, sup, so, po, inv, pi = settled(client)
    claim = client.post("/api/claims", json={"direction": "from_customer", "kind": "defect", "case_id": case["id"],
                                             "counterparty_id": party["id"]}).json()
    r = client.post(f"/api/claims/{claim['id']}/status", json={"status": "resolved", "resolution": "discount",
                                                               "resolution_amount": "5000000", "resolution_amount_currency": "IRR"})
    assert r.status_code == 200, r.text
    notes = [i for i in client.get(f"/api/cases/{case['id']}/finance").json()["sales_invoices"] if i["kind"] == "credit_note"]
    assert len(notes) == 1 and notes[0]["status"] == "draft" and D(notes[0]["subtotal"]) == 5_000_000
    assert notes[0]["corrects_invoice_id"] == inv["id"] and notes[0]["claim_id"] == claim["id"]
    assert events(client, "claim", claim["id"], "credit_note_drafted")
    # a supplier claim does not
    c2 = client.post("/api/claims", json={"direction": "against_supplier", "kind": "defect", "purchase_order_id": po["id"]}).json()
    client.post(f"/api/claims/{c2['id']}/status", json={"status": "resolved", "resolution": "discount", "resolution_amount": "1",
                                                        "resolution_amount_currency": "USD"})
    assert len([i for i in client.get(f"/api/cases/{case['id']}/finance").json()["sales_invoices"] if i["kind"] == "credit_note"]) == 1
    # no issued invoice in the claim's currency: nothing drafted, an event says why
    c3 = client.post("/api/claims", json={"direction": "from_customer", "kind": "delay", "case_id": case["id"],
                                          "counterparty_id": party["id"]}).json()
    client.post(f"/api/claims/{c3['id']}/status", json={"status": "resolved", "resolution": "credit_note", "resolution_amount": "10",
                                                        "resolution_amount_currency": "EUR"})
    assert events(client, "claim", c3["id"], "credit_note_not_created")


def test_search_exact_code_first_and_actual_costs_found(client):
    case, party, sup, so, po, inv, pi = settled(client)
    number = client.get(f"/api/sales-invoices/{inv['id']}").json()["number"]
    groups = client.get("/api/search", params={"q": number, "limit": 10}).json()["groups"]
    assert groups[0]["type"] == "sales_invoice" and groups[0]["items"][0]["match"] == "exact_code"
    assert groups[0]["items"][0]["id"] == inv["id"]
    prefix = client.get("/api/search", params={"q": number[:-2], "limit": 10}).json()["groups"]
    assert prefix[0]["items"][0]["match"] in ("exact_code", "code_prefix")
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "storage", "description": "انبارداری بندر شهید رجایی",
                                                                "amount": "12345678", "currency": "IRR"})
    for q in ("انبارداری بندر", "12345678"):
        groups = client.get("/api/search", params={"q": q}).json()["groups"]
        assert any(g["type"] == "actual_cost" for g in groups), q


def test_coverage_counts_every_status_from_selected_onward(client):
    case, party, sup, so, po = import_deal(client)           # the item is delivered
    cov = client.get(f"/api/cases/{case['id']}/coverage").json()
    assert cov["gate"]["missing"] == [] and cov["items"][0]["status"] == "delivered"

