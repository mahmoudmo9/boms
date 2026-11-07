"""v0.8.0 milestone 2: payments with FX and allocation, actual costs, the deal profit against plan, VAT.

The fixed import deal (all amounts hand-computed below):
- 1 item, Pump x10, bought at 100 USD from one supplier; cost sheet (import, IRR) at 1 USD = 500,000 IRR,
  international freight 20,000,000 IRR, customs duty 30,000,000 IRR, margin 20 %, annual cost of money 36 %.
  Plan: purchase 500,000,000; freight 20,000,000; duty 30,000,000; cost 550,000,000; revenue 687,500,000
  (550,000,000 / 0.8); profit 137,500,000.
- Sold in IRR to an Iranian customer; one invoice of 687,500,000 + 10 % VAT 68,750,000 = 756,250,000, paid in full on
  day 0 and allocated.
- Supplier invoice 1,000 USD (approved), paid in two payments: 400 USD on day −20 at 520,000 (208,000,000) and 600 USD
  on day −10 at 540,000 (324,000,000); both allocated: goods = 532,000,000.
- Actual costs: freight 40 USD at 530,000 on day −15 (21,200,000), customs duty 32,000,000 IRR with 3,200,000 input VAT.
- Claim against the supplier resolved with a 50 USD credit note: at the latest case rate (540,000) −27,000,000.
Actual: purchase 505,000,000; freight 21,200,000; duty 32,000,000; cost 558,200,000; revenue 687,500,000;
profit 129,300,000; margin 18.81 %; markup 23.16 %.
Variance: purchase +5,000,000 (+1.00 %); freight +1,200,000 (+6.00 %); duty +2,000,000 (+6.67 %).
FX effect (sheet 500,000 against the real rates): goods 500,000,000 − 532,000,000 = −32,000,000; freight
20,000,000 − 21,200,000 = −1,200,000; claim −25,000,000 − (−27,000,000) = +2,000,000; total −31,200,000.
VAT: output 68,750,000; input 3,200,000; net 65,550,000.
Cost of money: 208,000,000 rial tied up 10 days + 532,000,000 for 10 days = 7,400,000,000 rial-days
× 36 % / 365 = 7,298,630.137 → 7,298,630 (20 days).
"""
from decimal import Decimal

from tests.test_costing import new_sheet
from tests.test_execution_m1 import day
from tests.test_execution_m2 import by_currency, create_pos
from tests.test_finance_m1 import SELLER, deliver, domestic
from tests.test_quotes import _setup_letterhead, buyer, new_quote
from tests.test_sourcing_inquiries import events
from tests.test_sourcing_rfq import make_case, offer_body, supplier

D = Decimal


def import_deal(client):
    _setup_letterhead(client)
    client.patch("/api/settings", json=SELLER)
    case, items = make_case(client, [{"name": "Pump", "quantity": "10", "unit_code": "pc"}])
    sup = supplier(client)
    off = client.post("/api/offers", json=offer_body(case, sup, [{"line_item_id": items[0]["id"], "unit_price": "100"}],
                                                     currency="USD", valid_until=day(30))).json()
    client.post(f"/api/line-items/{items[0]['id']}/select", json={"offer_item_id": off["items"][0]["id"]})
    party = buyer(client, "IR")
    client.patch(f"/api/cases/{case['id']}", json={"party_id": party["id"]})
    sheet = new_sheet(client, case)
    sid = sheet["id"]
    client.put(f"/api/cost-sheets/{sid}/fx", json={"from_currency": "USD", "to_currency": "IRR", "rate": "500000",
                                                   "rate_kind": "free market", "as_of": day(0)})
    for line in sheet["lines"]:
        if line["kind"] == "purchase":
            continue
        body = {"freight_international": {"amount": "20000000", "currency": "IRR"},
                "customs_duty": {"basis": "total", "amount": "30000000", "currency": "IRR"}}.get(line["kind"])
        if body is None:
            body = {"percent": "0", "tax_parameter_id": None} if line["basis"].startswith("percent") else {"amount": "0", "currency": "IRR"}
        r = client.patch(f"/api/cost-sheets/lines/{line['id']}", json=body)
        assert r.status_code == 200, (line["kind"], r.text)
    r = client.patch(f"/api/cost-sheets/{sid}", json={"pricing_method": "margin", "target_percent": "20",
                                                     "annual_cost_of_money_percent": "36"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/cost-sheets/{sid}/finalize")
    assert r.status_code == 200, r.text
    quote = new_quote(client, case)
    assert client.post(f"/api/quotes/{quote['id']}/approve").status_code == 200
    quote = client.post(f"/api/quotes/{quote['id']}/mark-sent", json={}).json()
    client.put(f"/api/quotes/{quote['id']}/outcomes", json={"items": [{"quote_item_id": quote["items"][0]["id"], "outcome": "accepted"}]})
    so = client.post("/api/sales-orders/from-quote", json={"quote_id": quote["id"]}).json()
    so = client.post(f"/api/sales-orders/{so['id']}/confirm", json={"no_document_reason": "test"}).json()
    po = by_currency(create_pos(client, so)["created"])["USD"]
    assert client.post(f"/api/purchase-orders/{po['id']}/approve").status_code == 200, po
    client.post(f"/api/purchase-orders/{po['id']}/mark-sent", json={})
    po = client.post(f"/api/purchase-orders/{po['id']}/confirm", json={"confirmed_ready_on": day(5)}).json()
    client.post("/api/receipts", json={"purchase_order_id": po["id"], "received_on": day(-5), "items": [
        {"purchase_order_item_id": po["items"][0]["id"], "quantity": "10"}]})
    deliver(client, so, on=-1)
    domestic(client, party)
    return case, party, sup, so, po


def payment(client, milestone_id, amount, paid_on, **extra):
    r = client.post(f"/api/payment-milestones/{milestone_id}/payments", json={"amount": amount, "paid_on": paid_on, **extra})
    assert r.status_code == 201, r.text
    return r.json()["records"][-1] if r.json().get("records") else r.json()


def records(client, case):
    return client.get(f"/api/cases/{case['id']}/finance").json()["payments"]


def test_fx_rate_required_for_a_foreign_payment_and_base_amount(client):
    case, party, sup, so, po = import_deal(client)
    ms = client.post("/api/payment-milestones", json={"purchase_order_id": po["id"], "kind": "prepayment", "amount": "1000",
                                                      "amount_currency": "USD"}).json()
    r = client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": "400", "paid_on": day(-20)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "fx_rate_required"
    payment(client, ms["id"], "400", day(-20), fx_rate_to_base="520000", rate_source="صرافی", bank_fee="5")
    rec = records(client, case)[0]
    assert D(rec["base_amount"]) == 208_000_000 and not rec["rate_missing"] and rec["bank_fee_currency"] == "USD"
    # the bank fee is an actual cost (read-only, kind bank_fees) at the payment's rate
    fee = [c for c in client.get(f"/api/cases/{case['id']}/finance").json()["actual_costs"] if c["source"] == "payment_fee"]
    assert len(fee) == 1 and fee[0]["kind"] == "bank_fees" and D(fee[0]["base_amount"]) == 2_600_000 and fee[0]["read_only"]
    # an older record without a rate is flagged and completed
    from app.core.db import new_session
    from sqlalchemy import text

    with new_session() as s:
        s.execute(text("UPDATE ops.payment_record SET fx_rate_to_base = NULL, base_amount = NULL WHERE id = :i"), {"i": rec["id"]})
        s.commit()
    assert records(client, case)[0]["rate_missing"] is True
    r = client.patch(f"/api/payment-records/{rec['id']}", json={"fx_rate_to_base": "521000"})
    assert r.status_code == 200
    rec = records(client, case)[0]
    assert D(rec["base_amount"]) == 208_400_000 and rec["rate_missing"] is False
    assert events(client, "payment_milestone", ms["id"], "payment_update")


def test_allocation_oldest_first_over_allocation_cross_currency_and_advances(client):
    case, party, sup, so, po = import_deal(client)
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]}).json()
    inv = client.post(f"/api/sales-invoices/{inv['id']}/issue").json()
    total = D(inv["total"])
    ms = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "amount": str(total + 1000),
                                                      "amount_currency": "IRR"}).json()
    payment(client, ms["id"], str(total + 1000), day(0))
    rec = records(client, case)[0]
    assert [a["record_id"] for a in client.get(f"/api/cases/{case['id']}/finance").json()["advances"]] == [rec["id"]]
    view = client.get(f"/api/payment-records/{rec['id']}/allocation").json()
    assert [(s["sales_invoice_id"], D(s["amount"])) for s in view["suggestion"]] == [(inv["id"], total)]
    r = client.post(f"/api/payment-records/{rec['id']}/allocations", json={"allocations": [
        {"sales_invoice_id": inv["id"], "amount": str(total + 1)}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_allocated_invoice"
    r = client.post(f"/api/payment-records/{rec['id']}/allocations", json={"allocations": [
        {"sales_invoice_id": inv["id"], "amount": str(total)}]})
    assert r.status_code == 201 and D(r.json()["unallocated"]) == 1000
    assert client.get(f"/api/sales-invoices/{inv['id']}").json()["payment_status"] == "paid"
    assert [D(a["unallocated"]) for a in client.get(f"/api/cases/{case['id']}/finance").json()["advances"]] == [1000]
    # money in cannot pay a supplier invoice
    pi = client.post("/api/purchase-invoices", json={"purchase_order_id": po["id"], "supplier_invoice_no": f"S-{rec['id'][:6]}",
                                                     "invoice_date": day(-3)}).json()
    r = client.post(f"/api/payment-records/{rec['id']}/allocations", json={"allocations": [
        {"purchase_invoice_id": pi["id"], "amount": "1"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "wrong_direction"
    # cross-currency: an IRR payment out to a USD supplier invoice needs fx_rate
    out = client.post("/api/payment-milestones", json={"purchase_order_id": po["id"], "kind": "balance", "amount": "52000000",
                                                       "amount_currency": "IRR"}).json()
    payment(client, out["id"], "52000000", day(0))
    rec2 = [r for r in records(client, case) if r["milestone_id"] == out["id"]][0]
    r = client.post(f"/api/payment-records/{rec2['id']}/allocations", json={"allocations": [
        {"purchase_invoice_id": pi["id"], "amount": "52000000"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "fx_rate_required"
    r = client.post(f"/api/payment-records/{rec2['id']}/allocations", json={"allocations": [
        {"purchase_invoice_id": pi["id"], "amount": "52000000", "fx_rate": "0.000002"}]})
    assert r.status_code == 201, r.text
    pi = client.get(f"/api/purchase-invoices/{pi['id']}").json()
    assert D(pi["allocated"]) == 104 and pi["payment_status"] == "partly_paid"
    # more than the payment's unallocated amount
    r = client.post(f"/api/payment-records/{rec2['id']}/allocations", json={"allocations": [
        {"purchase_invoice_id": pi["id"], "amount": "1", "fx_rate": "0.000002"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_allocated_payment"
    # a reversed allocation (reason) frees the payment again
    alloc = records(client, case)
    alloc_id = [r for r in alloc if r["id"] == rec2["id"]][0]["allocations"][-1]["id"]
    assert client.post(f"/api/payment-allocations/{alloc_id}/reverse", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/payment-allocations/{alloc_id}/reverse", json={"reason": "اشتباه"}).status_code == 204
    assert client.get(f"/api/purchase-invoices/{pi['id']}").json()["payment_status"] == "unpaid"


def test_actual_costs_need_a_rate_when_foreign_and_paid_follows_allocations(client):
    case, party, sup, so, po = import_deal(client)
    r = client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "freight_international", "description": "Sea freight",
                                                                    "amount": "40", "currency": "USD"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "fx_rate_required"
    r = client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "freight_international", "description": "Sea freight",
                                                                    "amount": "40", "currency": "USD", "fx_rate_to_base": "530000",
                                                                    "party_id": sup["id"], "incurred_on": day(-15)})
    assert r.status_code == 201 and D(r.json()["base_amount"]) == 21_200_000 and r.json()["status"] == "incurred"
    cost = r.json()
    r = client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "goods", "description": "x", "amount": "1", "currency": "IRR"})
    assert r.status_code == 422                                                    # goods are supplier invoices, not a cost kind
    ms = client.post("/api/payment-milestones", json={"case_id": case["id"], "party_id": sup["id"], "direction": "out", "kind": "other",
                                                      "amount": "40", "amount_currency": "USD"})
    if ms.status_code != 201:                                                       # milestones may need an order
        ms = client.post("/api/payment-milestones", json={"purchase_order_id": po["id"], "kind": "other", "amount": "40",
                                                          "amount_currency": "USD"})
    ms = ms.json()
    payment(client, ms["id"], "40", day(-14), fx_rate_to_base="530000")
    rec = [r for r in records(client, case) if r["milestone_id"] == ms["id"]][0]
    r = client.post(f"/api/payment-records/{rec['id']}/allocations", json={"allocations": [{"actual_cost_id": cost["id"], "amount": "40"}]})
    assert r.status_code == 201, r.text
    cost = next(c for c in client.get(f"/api/cases/{case['id']}/finance").json()["actual_costs"] if c["id"] == cost["id"])
    assert cost["status"] == "paid" and D(cost["balance_due"]) == 0
    r = client.patch(f"/api/actual-costs/{cost['id']}", json={"amount": "41"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "cost_has_payments"
    assert client.delete(f"/api/actual-costs/{cost['id']}").status_code == 409


def test_the_fixed_import_deal_profit_is_exactly_the_hand_computed_figures(client):
    case, party, sup, so, po = import_deal(client)
    # sales invoice 687,500,000 + 10 % VAT, paid in full on day 0
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]}).json()
    assert D(inv["subtotal"]) == 687_500_000, inv["subtotal"]
    inv = client.patch(f"/api/sales-invoices/{inv['id']}", json={"vat_rate": "10", "vat_note": "نرخ قانونی"}).json()
    inv = client.post(f"/api/sales-invoices/{inv['id']}/issue").json()
    assert D(inv["total"]) == 756_250_000
    ms_in = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "balance", "amount": "756250000",
                                                         "amount_currency": "IRR"}).json()
    payment(client, ms_in["id"], "756250000", day(0))
    # supplier invoice 1,000 USD, two payments at different rates, both allocated
    pi = client.post("/api/purchase-invoices", json={"purchase_order_id": po["id"], "supplier_invoice_no": f"INV-{po['number']}",
                                                     "invoice_date": day(-25)}).json()
    assert client.post(f"/api/purchase-invoices/{pi['id']}/approve").json()["status"] == "approved"
    ms_out = client.post("/api/payment-milestones", json={"purchase_order_id": po["id"], "kind": "prepayment", "amount": "1000",
                                                          "amount_currency": "USD"}).json()
    payment(client, ms_out["id"], "400", day(-20), fx_rate_to_base="520000")
    payment(client, ms_out["id"], "600", day(-10), fx_rate_to_base="540000")
    for rec in records(client, case):
        target = {"sales_invoice_id": inv["id"]} if rec["direction"] == "in" else {"purchase_invoice_id": pi["id"]}
        r = client.post(f"/api/payment-records/{rec['id']}/allocations", json={"allocations": [{**target, "amount": rec["amount"]}]})
        assert r.status_code == 201, r.text
    # actual costs and the claim credit note
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "freight_international", "description": "Sea freight",
                                                                "amount": "40", "currency": "USD", "fx_rate_to_base": "530000",
                                                                "incurred_on": day(-15)})
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "customs_duty", "description": "حقوق ورودی",
                                                                "amount": "32000000", "currency": "IRR", "vat_amount": "3200000",
                                                                "incurred_on": day(-4)})
    claim = client.post("/api/claims", json={"direction": "against_supplier", "kind": "defect", "purchase_order_id": po["id"],
                                             "claimed_amount": "50", "claimed_amount_currency": "USD"}).json()
    r = client.post(f"/api/claims/{claim['id']}/status", json={"status": "resolved", "resolution": "credit_note",
                                                               "resolution_amount": "50"})
    assert r.status_code == 200, r.text
    p = client.get(f"/api/cases/{case['id']}/profit").json()
    assert p["deal_currency"] == "IRR" and p["base_currency"] == "IRR" and p["status"] == "open" and p["frozen"] is False
    rows = {r["kind"]: r for r in p["rows"]}
    expect = {"purchase": (500_000_000, 505_000_000, 5_000_000, "1.00"), "freight_international": (20_000_000, 21_200_000, 1_200_000, "6.00"),
              "customs_duty": (30_000_000, 32_000_000, 2_000_000, "6.67")}
    assert set(rows) == set(expect), rows.keys()
    for kind, (planned, actual, variance, pct) in expect.items():
        row = rows[kind]
        assert (D(row["planned"]["base"]), D(row["actual"]["base"]), D(row["variance"]["base"]), row["variance_percent"]) == \
            (planned, actual, variance, pct), kind
        assert D(row["actual"]["deal"]) == actual                                    # deal currency = IRR here
    assert rows["purchase"]["unrealized"] is True and rows["purchase"]["estimated"] is False    # the claim credit at the latest rate
    assert (D(p["revenue"]["planned"]["base"]), D(p["revenue"]["actual"]["base"])) == (687_500_000, 687_500_000)
    assert (D(p["cost"]["planned"]["base"]), D(p["cost"]["actual"]["base"])) == (550_000_000, 558_200_000)
    assert (D(p["profit"]["planned"]["base"]), D(p["profit"]["actual"]["base"]), D(p["profit"]["variance"]["base"])) == \
        (137_500_000, 129_300_000, -8_200_000)
    assert (p["margin_percent"]["planned"], p["margin_percent"]["actual"]) == ("20.00", "18.81")
    assert (p["markup_percent"]["planned"], p["markup_percent"]["actual"]) == ("25.00", "23.16")
    assert D(p["fx_effect"]["base"]) == -31_200_000
    assert (D(p["vat"]["output"]["base"]), D(p["vat"]["input"]["base"]), D(p["vat"]["net"]["base"])) == \
        (68_750_000, 3_200_000, 65_550_000)
    assert D(p["cost_of_money"]["actual"]["base"]) == 7_298_630 and p["cost_of_money"]["days"] == 20
    assert D(p["cost_of_money"]["planned"]["base"]) == 0 and D(p["cost_of_money"]["annual_percent"]) == 36
    assert D(p["unrealized"]["cost"]) == -27_000_000 and p["missing_rates"] == []
    assert p["expected"]["profit"] is not None


def test_unrealized_amounts_at_the_latest_rate(client):
    case, party, sup, so, po = import_deal(client)
    pi = client.post("/api/purchase-invoices", json={"purchase_order_id": po["id"], "supplier_invoice_no": f"U-{po['number']}",
                                                     "invoice_date": day(-2)}).json()
    client.post(f"/api/purchase-invoices/{pi['id']}/approve")
    p = client.get(f"/api/cases/{case['id']}/profit").json()
    purchase = next(r for r in p["rows"] if r["kind"] == "purchase")
    assert D(purchase["actual"]["base"]) == 500_000_000 and purchase["unrealized"] is True     # no case rate yet: the sheet's
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "freight_international", "description": "f", "amount": "1",
                                                                "currency": "USD", "fx_rate_to_base": "560000", "incurred_on": day(-1)})
    p = client.get(f"/api/cases/{case['id']}/profit").json()
    purchase = next(r for r in p["rows"] if r["kind"] == "purchase")
    assert D(purchase["actual"]["base"]) == 560_000_000 and D(p["unrealized"]["cost"]) == 560_000_000
    # received goods not on an approved invoice: estimated at the PO price
    client.post(f"/api/purchase-invoices/{pi['id']}/cancel", json={"reason": "x"})
    p = client.get(f"/api/cases/{case['id']}/profit").json()
    purchase = next(r for r in p["rows"] if r["kind"] == "purchase")
    assert purchase["estimated"] is True and D(purchase["actual"]["base"]) == 560_000_000
