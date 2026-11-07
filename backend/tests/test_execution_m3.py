"""v0.7.0 Phase 8, milestone 3: shipments (quantity limit, events, documents, delay warnings), inspections, receipts,
claims, deliveries with the ``delivered`` item status, and the integrations (command center, search, parties, cascade,
audit, migrations, backup)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from tests.conftest import unique_bytes, upload
from tests.test_execution_m1 import a_document, confirmed_order, day
from tests.test_execution_m2 import by_currency, create_pos, sent_po
from tests.test_sourcing_inquiries import audit_ops, events


def deal(client, **order):
    """A confirmed order (both quote items accepted) with two POs sent and confirmed (USD: Valve x10, EUR: Pump x2)."""
    case, items, party, quote, so = confirmed_order(client, **order)
    pos = by_currency(create_pos(client, so)["created"])
    out = {}
    for cur, po in pos.items():
        po = sent_po(client, po)
        r = client.post(f"/api/purchase-orders/{po['id']}/confirm", json={"confirmed_ready_on": day(20)})
        out[cur] = r.json()
    return case, party, so, out


def line_status(client, line_item_id):
    return client.get(f"/api/line-items/{line_item_id}").json()["status"]


def open_followups(db, ref_id, purpose):
    kind = {"invoice": "invoice_issue", "warranty_end": "warranty_end", "warranty_remind": "warranty_remind"}.get(purpose)
    if kind:                                        # v0.8.0: internal reminders are tasks
        return db.execute(text("SELECT id, due_on, title AS action FROM core.task WHERE source = 'execution' "
                               "AND source_id = :r AND source_kind = :k AND status = 'open'"), {"r": ref_id, "k": kind}).all()
    return db.execute(text("SELECT f.id, f.due_on, f.action FROM ops.execution_followup l JOIN core.followup f ON f.id = l.followup_id "
                           "WHERE l.ref_id = :r AND l.purpose = :p AND f.status = 'open'"), {"r": ref_id, "p": purpose}).all()


# ---- shipments ---------------------------------------------------------------------------------------------------------

def test_shipment_quantity_limit_eta_events_documents(client):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    item = usd["items"][0]                                        # Valve x10
    r = client.post("/api/shipments", json={"purchase_order_id": usd["id"], "mode": "sea", "eta": day(30),
                                            "items": [{"purchase_order_item_id": item["id"], "quantity": "6"}]})
    assert r.status_code == 201, r.text
    s1 = r.json()
    assert s1["direction"] == "inbound" and s1["first_eta"] == day(30) and s1["sales_order_id"] == so["id"]
    r = client.post("/api/shipments", json={"purchase_order_id": usd["id"],
                                            "items": [{"purchase_order_item_id": item["id"], "quantity": "5"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_shipped"
    assert r.json()["error"]["details"]["already_shipped"].startswith("6")
    r = client.post("/api/shipments", json={"purchase_order_id": usd["id"],
                                            "items": [{"purchase_order_item_id": item["id"], "quantity": "4"}]})
    assert r.status_code == 201
    # ETA moved: an event with old -> new, the first ETA kept
    r = client.patch(f"/api/shipments/{s1['id']}", json={"eta": day(36), "containers": ["MSCU1234567", "MSCU7654321"],
                                                         "status": "in_transit"})
    out = r.json()
    kinds = [e["kind"] for e in out["events"]]
    assert "delay" in kinds and "departed" in kinds and out["first_eta"] == day(30)
    assert f"{day(30)} → {day(36)}" in next(e["note"] for e in out["events"] if e["kind"] == "delay")
    r = client.post(f"/api/shipments/{s1['id']}/events", json={"kind": "transshipment", "note": "Jebel Ali"})
    assert r.status_code == 201 and r.json()["events"][-1]["kind"] == "transshipment"
    doc = a_document(client, "bl.pdf")
    r = client.post(f"/api/shipments/{s1['id']}/documents", json={"kind": "bl", "document_id": doc, "number": "MEDU998877"})
    out = r.json()
    assert [d["kind"] for d in out["documents"]] == ["bl"] and out["transport_doc_no"] == "MEDU998877"
    client.post(f"/api/shipments/{s1['id']}/documents", json={"kind": "packing_list", "document_id": a_document(client, "pl.pdf")})
    kinds = sorted(d["kind"] for d in client.get(f"/api/shipments/{s1['id']}").json()["documents"])
    assert kinds == ["bl", "packing_list"]
    r = client.post(f"/api/shipments/{s1['id']}/documents", json={"kind": "passport", "document_id": doc})
    assert r.status_code == 422


def test_delay_warnings_three_kinds_on_a_fixed_clock(client, db):
    from app.modules.execution import logistics

    client.patch("/api/settings", json={"execution.delay_warning_days": 3})
    case, party, so, pos = deal(client)
    usd, eur = pos["USD"], pos["EUR"]
    s = client.post("/api/shipments", json={"purchase_order_id": usd["id"], "eta": day(10)}).json()
    client.patch(f"/api/shipments/{s['id']}", json={"eta": day(15)})          # moved 5 days > 3
    import uuid

    db.expire_all()
    on = date.today() + timedelta(days=25)                                     # ETA passed, EUR ready date passed
    kinds = sorted(w["kind"] for w in logistics.delay_warnings(db, uuid.UUID(case["id"]), on=on))
    assert kinds == ["eta_moved", "eta_passed", "ready_passed", "ready_passed"]
    client.post(f"/api/purchase-orders/{eur['id']}/status", json={"status": "ready"})
    client.patch(f"/api/shipments/{s['id']}", json={"ata": day(14)})
    db.expire_all()
    kinds = sorted(w["kind"] for w in logistics.delay_warnings(db, uuid.UUID(case["id"]), on=on))
    assert kinds == ["eta_moved", "ready_passed"]
    on_time = sorted(w["kind"] for w in logistics.delay_warnings(db, uuid.UUID(case["id"]), on=date.today()))
    assert on_time == ["eta_moved"]


# ---- inspections and receipts -------------------------------------------------------------------------------------------

def test_failed_inspection_offers_a_prefilled_claim(client):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    s = client.post("/api/shipments", json={"purchase_order_id": usd["id"]}).json()
    r = client.post("/api/inspections", json={"shipment_id": s["id"], "kind": "pre_shipment", "result": "pass"})
    assert r.status_code == 201 and r.json()["claim_suggestion"] is None
    r = client.post("/api/inspections", json={"purchase_order_id": usd["id"], "kind": "on_arrival", "items": [
        {"purchase_order_item_id": usd["items"][0]["id"], "quantity": "2", "result": "fail", "note": "زنگ‌زدگی"}]})
    insp = r.json()
    assert insp["result"] == "pending"
    r = client.patch(f"/api/inspections/{insp['id']}", json={"result": "fail", "notes": "۲ عدد معیوب"})
    out = r.json()
    sug = out["claim_suggestion"]
    assert out["done_on"] == day(0) and sug["direction"] == "against_supplier" and sug["kind"] == "defect"
    assert sug["counterparty_id"] == usd["supplier_party_id"] and sug["inspection_id"] == insp["id"]
    assert sug["items"][0]["result"] == "fail"
    r = client.post("/api/claims", json={k: v for k, v in sug.items() if k not in ("case_id",)})
    assert r.status_code == 201 and r.json()["inspection_id"] == insp["id"]
    assert events(client, "inspection", insp["id"], "result")


def test_receipts_update_the_po_and_short_lines_offer_a_claim(client):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    item = usd["items"][0]
    r = client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(0), "items": [
        {"purchase_order_item_id": item["id"], "quantity": "7", "condition": "ok"},
    ]})
    assert r.status_code == 201
    po = client.get(f"/api/purchase-orders/{usd['id']}").json()
    assert Decimal(po["items"][0]["received_quantity"]) == 7 and po["status"] == "confirmed"
    r = client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(0), "items": [
        {"purchase_order_item_id": item["id"], "quantity": "4"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_received"
    r = client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(1), "items": [
        {"purchase_order_item_id": item["id"], "quantity": "3", "condition": "short", "note": "۱ عدد کم"}]})
    rec = r.json()
    assert rec["claim_suggestion"]["kind"] == "shortage" and rec["claim_suggestion"]["receipt_id"] == rec["id"]
    po = client.get(f"/api/purchase-orders/{usd['id']}").json()
    assert po["status"] == "received" and Decimal(po["items"][0]["received_quantity"]) == 10
    r = client.post(f"/api/receipts/{rec['id']}/reverse", json={"reason": "ثبت اشتباه"})
    assert r.status_code == 204
    assert client.get(f"/api/purchase-orders/{usd['id']}").json()["status"] == "shipped"
    # direct to the customer: no receipt
    eur = pos["EUR"]
    client.patch(f"/api/purchase-orders/{eur['id']}", json={"direct_to_customer": True})
    r = client.post("/api/receipts", json={"purchase_order_id": eur["id"], "received_on": day(0), "items": [
        {"purchase_order_item_id": eur["items"][0]["id"], "quantity": "2"}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "direct_to_customer"


# ---- claims --------------------------------------------------------------------------------------------------------------

def test_claim_status_flow_events_periodic_followup_and_links(client, db):
    from app.modules.execution import claims as claims_service

    case, party, so, pos = deal(client)
    usd = pos["USD"]
    r = client.post("/api/claims", json={"direction": "against_supplier", "kind": "shortage", "purchase_order_id": usd["id"],
                                         "counterparty_id": usd["supplier_party_id"], "claimed_amount": "25",
                                         "claimed_amount_currency": "USD"})
    assert r.status_code == 201, r.text
    claim = r.json()
    assert claim["case_id"] == case["id"] and claim["status"] == "open"
    f = open_followups(db, claim["id"], "claim")
    assert len(f) == 1 and f[0].due_on == date.today() + timedelta(days=7) and "پیگیری ادعا" in f[0].action
    client.post(f"/api/followups/{f[0].id}/done", json={"note": "تماس گرفته شد"})
    db.expire_all()
    assert open_followups(db, claim["id"], "claim") == []
    assert claims_service.refresh_followups(db) >= 1
    db.commit()
    assert len(open_followups(db, claim["id"], "claim")) == 1                # the next one
    for status in ("submitted", "negotiating"):
        assert client.post(f"/api/claims/{claim['id']}/status", json={"status": status}).status_code == 200
    r = client.post(f"/api/claims/{claim['id']}/status", json={"status": "resolved"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "resolution_required"
    r = client.post(f"/api/claims/{claim['id']}/status", json={"status": "resolved", "resolution": "credit_note",
                                                               "resolution_amount": "20"})
    out = r.json()
    assert out["status"] == "resolved" and out["resolution_amount_currency"] == "USD" and out["resolved_on"] == day(0)
    db.expire_all()
    assert open_followups(db, claim["id"], "claim") == []
    statuses = [e["data"]["new_status"] for e in events(client, "claim", claim["id"], "status")]
    assert sorted(statuses) == ["negotiating", "resolved", "submitted"]
    # a link from another case is refused
    other_case, other_party, other_so, other_pos = deal(client)
    r = client.post("/api/claims", json={"case_id": case["id"], "direction": "against_carrier", "kind": "damage",
                                         "counterparty_id": usd["supplier_party_id"], "purchase_order_id": other_pos["USD"]["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "link_not_of_case"


# ---- deliveries and the delivered status ------------------------------------------------------------------------------------

def test_deliveries_partial_progress_delivered_status_followups_and_reversal(client, db):
    case, party, so, pos = deal(client, warranty_months=12)
    perf = client.post("/api/guarantees", json={"case_id": case["id"], "purpose": "performance", "valid_until": day(400)}).json()
    client.patch(f"/api/sales-orders/{so['id']}", json={"performance_guarantee_id": perf["id"]})
    valve, pump = sorted(so["items"], key=lambda i: Decimal(i["quantity"]), reverse=True)   # Valve x10, Pump x2
    assert line_status(client, valve["line_item_id"]) == "sold"
    r = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0), "items": [
        {"sales_order_item_id": valve["id"], "quantity": "11"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_delivered"
    receipt = a_document(client, "warehouse-receipt.pdf")
    r = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0), "receiver_name": "انبار مشتری",
                                             "receipt_document_id": receipt,
                                             "items": [{"sales_order_item_id": valve["id"], "quantity": "6"}]})
    out = r.json()
    assert out["progress"]["items_delivered"] == 0 and out["status"] == "in_progress"
    assert next(i for i in out["items"] if i["id"] == valve["id"])["delivered"].startswith("6")
    assert line_status(client, valve["line_item_id"]) == "sold"                         # not complete: still sold
    r = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(1), "items": [
        {"sales_order_item_id": valve["id"], "quantity": "4"}]})
    assert r.json()["progress"]["items_delivered"] == 1 and line_status(client, valve["line_item_id"]) == "delivered"
    assert line_status(client, pump["line_item_id"]) == "sold"
    r = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(2), "items": [
        {"sales_order_item_id": pump["id"], "quantity": "2"}]})
    out = r.json()
    assert out["status"] == "delivered" and out["delivered_at"] and out["progress"] == {
        "items": out["progress"]["items"], "items_total": 2, "items_delivered": 2}
    assert line_status(client, pump["line_item_id"]) == "delivered"
    db.expire_all()
    invoice = open_followups(db, so["id"], "invoice")
    assert len(invoice) == 1 and "صدور فاکتور و پیگیری تسویه" in invoice[0].action
    warranty = open_followups(db, so["id"], "warranty_end")
    from app.modules.execution.deliveries import add_months

    assert len(warranty) == 1 and warranty[0].due_on == add_months(date.today() + timedelta(days=2), 12)
    release = client.get(f"/api/guarantees/{perf['id']}").json()["reminders"]
    assert [x["purpose"] for x in release if x["purpose"] == "guarantee_release"] == ["guarantee_release"]
    header = client.get(f"/api/cases/{case['id']}/execution").json()["header"]
    assert header["items_delivered"] == 2 and header["items_total"] == 2 and header["order"]["status"] == "delivered"
    assert header["order"]["warranty_ends_on"]
    # reversing the last delivery: back to in_progress, the pump back to sold, the follow-ups cancelled
    deliveries = client.get(f"/api/cases/{case['id']}/execution").json()["deliveries"]
    last = max(deliveries, key=lambda d: d["delivered_on"])
    r = client.post(f"/api/deliveries/{last['id']}/reverse", json={"reason": ""})
    assert r.status_code == 422
    r = client.post(f"/api/deliveries/{last['id']}/reverse", json={"reason": "رسید اشتباه"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    assert line_status(client, pump["line_item_id"]) == "sold" and line_status(client, valve["line_item_id"]) == "delivered"
    db.expire_all()
    assert open_followups(db, so["id"], "invoice") == [] and open_followups(db, so["id"], "warranty_end") == []
    assert open_followups(db, so["id"], "warranty_remind") == []
    release = client.get(f"/api/guarantees/{perf['id']}").json()["reminders"]
    assert not [x for x in release if x["purpose"] == "guarantee_release"]


def test_a_legacy_delivered_item_without_delivery_data_stays_delivered(client, db):
    """``delivered`` set before v0.7.0 (no sales order) is not cleared by the new rule."""
    case, items, party, quote, so = confirmed_order(client)
    other = client.post("/api/cases", json={"title": "Legacy"}).json()
    item = client.post("/api/line-items/bulk", json={"case_id": other["id"], "items": [{"name": "Old", "quantity": "1"}]}).json()["items"][0]
    db.execute(text("UPDATE ops.line_item SET status = 'delivered' WHERE id = :i"), {"i": item["id"]})
    db.commit()
    from app.modules.sourcing import items as sourcing_items

    sourcing_items.recompute_items(db, [item["id"]], "script")
    db.commit()
    assert line_status(client, item["id"]) == "delivered"


# ---- integration -------------------------------------------------------------------------------------------------------------

def test_command_center_section_on_a_fixed_dataset(client, db):
    from app.modules.execution import dashboard

    case, party, so, pos = deal(client)
    usd = pos["USD"]
    client.post("/api/shipments", json={"purchase_order_id": usd["id"], "eta": day(5)})
    client.post("/api/claims", json={"direction": "against_supplier", "kind": "delay", "purchase_order_id": usd["id"],
                                     "counterparty_id": usd["supplier_party_id"]})
    client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "balance", "amount": "10",
                                                 "due_on": day(2)})
    client.patch(f"/api/sales-orders/{so['id']}", json={"notes": "x"})
    db.expire_all()
    on = date.today() + timedelta(days=25)
    out = dashboard.summary(db, on)
    mine = lambda key, field="case_id": [x for x in out[key] if x[field] == case["id"]]  # noqa: E731
    assert len(mine("ready_passed")) == 2 and [x["kind"] for x in mine("shipments_delayed")] == ["eta_passed"]
    assert len(mine("claims_open")) == 1 and [x["kind"] for x in mine("payments_overdue")] == ["balance"]
    assert mine("steps_due") and all(s["overdue"] or s["due_on"] for s in mine("steps_due"))
    assert mine("pos_unconfirmed") == []
    cc = client.get("/api/command-center").json()
    assert set(cc["execution"]) == {"pos_unconfirmed", "ready_passed", "shipments_delayed", "steps_due", "payments_overdue",
                                    "claims_open", "deliveries_due"}


def test_search_providers(client):
    case, party, so, pos = deal(client, customer_ref="CR-SEARCH-77")
    usd = pos["USD"]
    client.post(f"/api/purchase-orders/{usd['id']}/ready-date", json={"ready_due_on": day(25), "reason": "x"})
    s = client.post("/api/shipments", json={"purchase_order_id": usd["id"], "transport_doc_kind": "bl",
                                            "transport_doc_no": "MEDU55443322", "containers": ["TGHU8899001"]}).json()
    p = client.get(f"/api/cases/{case['id']}/execution").json()["processes"][0]
    kotaj = next(x for x in p["steps"] if x["code"] == "declaration_kotaj")
    client.patch(f"/api/process-steps/{kotaj['id']}", json={"reference": "KTJ-55667788"})

    def found(q, wanted):
        return wanted in str(client.get("/api/search", params={"q": q}).json())

    assert found("CR-SEARCH-77", so["id"]) and found(so["number"], so["id"])
    assert found(usd["number"], usd["id"])
    assert found("MEDU55443322", s["id"]) and found("TGHU8899001", s["id"])
    assert found("KTJ-55667788", kotaj["id"])


def test_party_delete_counts_and_party_lists(client):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    r = client.delete(f"/api/parties/{usd['supplier_party_id']}")
    assert r.status_code == 409 and r.json()["error"]["details"]["purchase_orders"] >= 1
    r = client.delete(f"/api/parties/{so['customer_party_id']}")
    assert r.status_code == 409 and r.json()["error"]["details"]["sales_orders"] >= 1
    lists = client.get(f"/api/parties/{usd['supplier_party_id']}/execution").json()
    assert [p["number"] for p in lists["purchase_orders"]] == [usd["number"]]
    assert client.get(f"/api/parties/{so['customer_party_id']}/execution").json()["sales_orders"][0]["id"] == so["id"]


def test_cascade_delete_counts_and_cancels_followups(client, db):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "amount": "5"})
    s = client.post("/api/shipments", json={"purchase_order_id": usd["id"], "eta": day(9),
                                            "items": [{"purchase_order_item_id": usd["items"][0]["id"], "quantity": "1"}]}).json()
    client.post(f"/api/shipments/{s['id']}/events", json={"kind": "loaded"})
    client.post("/api/claims", json={"direction": "against_supplier", "kind": "delay", "purchase_order_id": usd["id"],
                                     "counterparty_id": usd["supplier_party_id"]})
    client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(0),
                                       "items": [{"purchase_order_item_id": usd["items"][0]["id"], "quantity": "1"}]})
    client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0),
                                         "items": [{"sales_order_item_id": so["items"][0]["id"], "quantity": "1"}]})
    open_before = db.execute(text("SELECT count(*) FROM ops.execution_followup l JOIN core.followup f ON f.id = l.followup_id "
                                  "WHERE l.case_id = :c AND f.status = 'open'"), {"c": case["id"]}).scalar()
    assert open_before >= 3
    r = client.request("DELETE", f"/api/cases/{case['id']}", params={"cascade": "true"}, json={"confirm_title": case["title"]})
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert counts["sales_orders"] == 1 and counts["purchase_orders"] == 2 and counts["shipments"] == 1
    assert counts["process_steps"] == 13 and counts["claims"] == 1 and counts["deliveries"] == 1 and counts["receipts"] == 1
    assert counts["payment_milestones"] == 1 and counts["shipment_events"] == 1
    for table in ("sales_order", "purchase_order", "shipment", "process", "claim", "delivery", "receipt", "execution_followup"):
        assert db.execute(text(f"SELECT count(*) FROM ops.{table} WHERE "
                               f"{'case_id' if table not in ('delivery', 'receipt') else 'id'} = :c"), {"c": case["id"]}).scalar() == 0
    db.expire_all()
    still_open = db.execute(text("SELECT count(*) FROM core.followup WHERE status = 'open' AND action LIKE :a"),
                            {"a": f"%{so['number']}%"}).scalar()
    assert still_open == 0


def test_audit_rows_and_events_for_every_new_table(client, db):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    ms = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "amount": "5"}).json()
    client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": "5", "paid_on": day(0)})
    client.post(f"/api/sales-orders/{so['id']}/amend", json={"reason": "r", "changes": {"delivery_due_on": day(50)}})
    s = client.post("/api/shipments", json={"purchase_order_id": usd["id"], "eta": day(9),
                                            "items": [{"purchase_order_item_id": usd["items"][0]["id"], "quantity": "1"}]}).json()
    client.post(f"/api/shipments/{s['id']}/events", json={"kind": "loaded"})
    client.post(f"/api/shipments/{s['id']}/documents", json={"kind": "bl", "document_id": a_document(client, "b.pdf")})
    client.post("/api/inspections", json={"shipment_id": s["id"], "kind": "on_arrival", "result": "pass"})
    rc = client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(0),
                                            "items": [{"purchase_order_item_id": usd["items"][0]["id"], "quantity": "1"}]}).json()
    client.post("/api/claims", json={"direction": "against_supplier", "kind": "delay", "receipt_id": rc["id"],
                                     "counterparty_id": usd["supplier_party_id"]})
    client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0),
                                         "items": [{"sales_order_item_id": so["items"][0]["id"], "quantity": "1"}]})
    tpl = client.post("/api/process-templates", json={"deal_type": "export", "name": "temp", "steps": [
        {"code": "a", "label_fa": "الف", "label_en": "A"}]}).json()
    assert client.delete(f"/api/process-templates/{tpl['id']}").status_code == 204
    tables = ["sales_order", "sales_order_item", "sales_order_change", "purchase_order", "purchase_order_item",
              "purchase_order_change", "payment_milestone", "payment_record", "process", "process_step", "shipment",
              "shipment_item", "shipment_event", "shipment_document", "inspection", "receipt", "receipt_item", "delivery",
              "delivery_item", "claim", "execution_followup", "sales_order_sequence", "purchase_order_sequence",
              "process_template", "process_template_step"]
    for table in tables:
        n = db.execute(text("SELECT count(*) FROM core.audit WHERE table_name = :t"), {"t": f"ops.{table}"}).scalar()
        assert n > 0, table
    for entity in ("sales_order", "purchase_order", "payment_milestone", "process", "shipment", "inspection", "receipt",
                   "claim", "delivery"):
        assert db.execute(text("SELECT count(*) FROM core.event WHERE entity_type = :e"), {"e": entity}).scalar() > 0, entity
    assert audit_ops(db, "ops.sales_order", so["id"])[0] == "I"


def test_unknown_fields_and_constraint_errors_persist_nothing(client, db):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    for path, body in (("/api/shipments", {"purchase_order_id": usd["id"], "bogus": 1}),
                       ("/api/claims", {"direction": "against_supplier", "kind": "delay", "bogus": 1}),
                       ("/api/deliveries", {"sales_order_id": so["id"], "delivered_on": day(0), "items": [], "x": 1}),
                       ("/api/receipts", {"purchase_order_id": usd["id"], "received_on": day(0), "items": [], "x": 1})):
        assert client.post(path, json=body).status_code == 422, path
    before = db.execute(text("SELECT count(*) FROM ops.shipment WHERE case_id = :c"), {"c": case["id"]}).scalar()
    # an insured amount without currency violates the CHECK: 422 with the constraint name, nothing stored
    r = client.post("/api/shipments", json={"purchase_order_id": usd["id"], "insured_amount": "1000"})
    assert r.status_code == 422 and r.json()["error"]["details"]["constraint"] == "insured_amount_has_currency"
    db.expire_all()
    assert db.execute(text("SELECT count(*) FROM ops.shipment WHERE case_id = :c"), {"c": case["id"]}).scalar() == before
    # unique: a second process of the same deal type
    r = client.post(f"/api/cases/{case['id']}/processes", json={"deal_type": "import"})
    assert r.status_code == 409


def test_item_status_sold_delivered_reversed_sold(client):
    case, party, so, pos = deal(client)
    item = so["items"][0]
    assert line_status(client, item["line_item_id"]) == "sold"
    r = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0),
                                             "items": [{"sales_order_item_id": item["id"], "quantity": item["quantity"]}]})
    assert line_status(client, item["line_item_id"]) == "delivered"
    delivery = client.get(f"/api/cases/{case['id']}/execution").json()["deliveries"][0]
    client.post(f"/api/deliveries/{delivery['id']}/reverse", json={"reason": "برگشت"})
    assert line_status(client, item["line_item_id"]) == "sold"
    assert r.status_code == 201


def test_migration_0013_up_down_up_with_phase7b_data():
    from alembic import command

    from app.cli import alembic_config
    from app.core import dbadmin
    from app.core.config import get_config
    from tests.conftest import create_empty_database, superuser_conninfo

    name = "boms_test_p8_migrations"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    new_tables = {"ops.sales_order", "ops.purchase_order", "ops.payment_milestone", "ops.process", "ops.shipment",
                  "ops.claim", "ops.delivery", "ops.execution_followup"}

    def tables():
        with engine.connect() as conn:
            return set(conn.execute(text("SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname = 'ops'")).scalars())

    def p7b_rows():
        with engine.connect() as conn:
            return conn.execute(text("SELECT (SELECT count(*) FROM ops.tender), (SELECT count(*) FROM ops.guarantee), "
                                     "(SELECT count(*) FROM ops.tender_proposal), (SELECT count(*) FROM ops.message_template)")).one()

    try:
        command.upgrade(cfg, "0012")
        with engine.begin() as conn:    # Phase 7b data: a won tender with an approved proposal and a performance guarantee
            conn.execute(text("INSERT INTO sys.currency (code, name_fa, name_en, minor_units) VALUES ('IRR', 'ریال', 'Rial', 0)"))
            party = conn.execute(text("INSERT INTO core.party (name_fa) VALUES ('برگزارکننده') RETURNING id")).scalar()
            case = conn.execute(text("INSERT INTO ops.\"case\" (title, party_id) VALUES ('Tender case', :p) RETURNING id"),
                                {"p": party}).scalar()
            tender = conn.execute(text("INSERT INTO ops.tender (case_id, organizer_party_id, result, stage) "
                                       "VALUES (:c, :p, 'won', 'result') RETURNING id"), {"c": case, "p": party}).scalar()
            sheet = conn.execute(text("INSERT INTO ops.cost_sheet (case_id, version, deal_type, pricing_currency, status) "
                                      "VALUES (:c, 1, 'domestic', 'IRR', 'final') RETURNING id"), {"c": case}).scalar()
            conn.execute(text("INSERT INTO ops.tender_proposal (tender_id, cost_sheet_id, version, status, currency, approved_at, "
                              "approved_by) VALUES (:t, :s, 1, 'approved', 'IRR', now(), 'admin')"), {"t": tender, "s": sheet})
            conn.execute(text("INSERT INTO ops.guarantee (case_id, tender_id, purpose, status) VALUES (:c, :t, 'performance', 'issued')"),
                         {"c": case, "t": tender})
        before = p7b_rows()
        assert not (new_tables & tables())
        command.upgrade(cfg, "head")
        assert new_tables <= tables()
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ops.process_template_step")).scalar() == 27
            assert conn.execute(text("SELECT count(*) FROM ops.message_template WHERE kind = 'po_terms'")).scalar() == 2
        after = p7b_rows()
        assert after[:3] == before[:3] and after[3] == before[3] + 2
        command.downgrade(cfg, "0012")
        assert not (new_tables & tables()) and p7b_rows() == before
        command.upgrade(cfg, "head")
        assert new_tables <= tables() and p7b_rows()[:3] == before[:3]
    finally:
        engine.dispose()
        dbadmin.drop_database(superuser_conninfo(), name)


def test_backup_and_restore_test_cover_every_table_with_execution_data(client):
    from app.core.db import get_engine
    from app.modules.system import backup

    case, party, so, pos = deal(client)
    usd = pos["USD"]
    ms = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "amount": "5"}).json()
    client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": "5", "paid_on": day(0)})
    s = client.post("/api/shipments", json={"purchase_order_id": usd["id"],
                                            "items": [{"purchase_order_item_id": usd["items"][0]["id"], "quantity": "1"}]}).json()
    client.post(f"/api/shipments/{s['id']}/documents", json={"kind": "bl", "document_id": a_document(client, "b2.pdf")})
    client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(0),
                                         "items": [{"sales_order_item_id": so["items"][0]["id"], "quantity": "1"}]})
    run_id = backup.run_backup("manual", source="script")
    result = backup.restore_test(run_id, source="script")
    with get_engine().connect() as conn:
        counts = backup.table_counts(conn)
    assert result["status"] == "passed", result
    assert result["details"]["tables_checked"] == len(counts) and result["details"]["row_count_mismatches"] == {}
    for table in ("ops.sales_order", "ops.purchase_order", "ops.payment_record", "ops.process_step", "ops.shipment_document",
                  "ops.delivery_item", "ops.execution_followup"):
        assert counts[table] > 0, table
    assert upload and unique_bytes and pytest
