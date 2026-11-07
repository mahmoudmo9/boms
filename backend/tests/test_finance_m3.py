"""v0.8.0 milestone 3: closing (checklist, reasons, read-only, reopen, frozen snapshot), ratings, the finance workspace
(aging, payables, deals, VAT, CSV and zip), and the integrations (command center, search, parties, cascade, audit,
migrations, backup)."""
import csv
import io
import zipfile
from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, text

from tests.test_execution_m1 import day
from tests.test_execution_m3 import deal
from tests.test_finance_m1 import SELLER, deliver
from tests.test_finance_m2 import import_deal, payment, records
from tests.test_listings_store import tag
from tests.test_quotes import _setup_letterhead
from tests.test_sourcing_inquiries import events

D = Decimal


def settled(client):
    """The import deal invoiced, paid both ways, Moadian accepted: the checklist passes except open tasks."""
    case, party, sup, so, po = import_deal(client)
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]}).json()
    inv = client.post(f"/api/sales-invoices/{inv['id']}/issue").json()
    client.post(f"/api/sales-invoices/{inv['id']}/moadian", json={"moadian_status": "accepted", "moadian_tax_id": f"TX{tag()}"})
    ms_in = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "balance", "amount": inv["total"],
                                                         "amount_currency": "IRR"}).json()
    payment(client, ms_in["id"], inv["total"], day(0), reference=f"REF-{tag()}")
    pi = client.post("/api/purchase-invoices", json={"purchase_order_id": po["id"], "supplier_invoice_no": f"S-{tag()}",
                                                     "invoice_date": day(-5)}).json()
    client.post(f"/api/purchase-invoices/{pi['id']}/approve")
    ms_out = client.post("/api/payment-milestones", json={"purchase_order_id": po["id"], "kind": "balance", "amount": "1000",
                                                          "amount_currency": "USD"}).json()
    payment(client, ms_out["id"], "1000", day(-3), fx_rate_to_base="530000")
    for rec in records(client, case):
        target = {"sales_invoice_id": inv["id"]} if rec["direction"] == "in" else {"purchase_invoice_id": pi["id"]}
        assert client.post(f"/api/payment-records/{rec['id']}/allocations",
                           json={"allocations": [{**target, "amount": rec["amount"]}]}).status_code == 201
    return case, party, sup, so, po, inv, pi


def statuses(client, case):
    return {i["status"] for i in client.get(f"/api/cases/{case['id']}").json()["items"]}


# ---- closing --------------------------------------------------------------------------------------------------------

def test_the_checklist_lists_every_problem_together(client):
    case, party, sup, so, po = import_deal(client)
    client.post("/api/sales-invoices", json={"sales_order_id": so["id"]})                       # a draft
    client.post("/api/claims", json={"direction": "against_supplier", "kind": "delay", "purchase_order_id": po["id"]})
    client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "balance", "amount": "10",
                                                 "amount_currency": "IRR"})
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "storage", "description": "انبار", "amount": "5000000",
                                                                "currency": "IRR"})
    g = client.post("/api/guarantees", json={"case_id": case["id"], "purpose": "bid"}).json()
    client.post(f"/api/guarantees/{g['id']}/status", json={"status": "issued", "valid_until": day(60)})
    perf = client.post("/api/guarantees", json={"case_id": case["id"], "purpose": "performance", "valid_until": day(200)}).json()
    client.post(f"/api/guarantees/{perf['id']}/status", json={"status": "issued", "valid_until": day(200)})
    check = client.get(f"/api/cases/{case['id']}/close-checklist").json()
    codes = {p["code"] for p in check["problems"]}
    assert codes == {"invoice_drafts", "received_not_invoiced", "claims_open", "milestones_open", "costs_unpaid",
                     "guarantees_not_released"}, codes
    assert check["passes"] is False and [n["code"] for n in check["notes"]] == ["guarantee_running"]
    assert check["to_cancel"]["tasks"]                                                           # checklist step reminders
    r = client.post(f"/api/cases/{case['id']}/close", json={"reasons": {"claims_open": "پیگیری جدا"}})
    assert r.status_code == 409 and r.json()["error"]["code"] == "close_checklist"
    assert set(r.json()["error"]["details"]["unexplained"]) == codes - {"claims_open"}
    # a status set by hand is refused for a deal with a sales order
    r = client.patch(f"/api/cases/{case['id']}", json={"status": "closed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "use_close_deal"


def test_close_with_reasons_items_closed_read_only_then_reopen(client, db):
    case, party, sup, so, po, inv, pi = settled(client)
    check = client.get(f"/api/cases/{case['id']}/close-checklist").json()
    assert check["problems"] == [], check["problems"]
    r = client.post(f"/api/cases/{case['id']}/close", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "open_tasks"                  # confirm cancelling tasks
    live = client.get(f"/api/cases/{case['id']}/profit").json()
    r = client.post(f"/api/cases/{case['id']}/close", json={"confirm_cancel_open": True})
    assert r.status_code == 200, r.text
    snap = r.json()
    assert snap["frozen"] is True and snap["status"] == "closed" and snap["profit"]["actual"] == live["profit"]["actual"]
    assert statuses(client, case) == {"closed"}
    detail = client.get(f"/api/cases/{case['id']}").json()
    assert detail["status"] == "closed"
    assert client.get(f"/api/cases/{case['id']}/tasks").json() == []                             # open tasks cancelled
    assert events(client, "case", case["id"], "deal_closed")
    # read-only: writes refused with case_closed; notes, ratings and documents stay writable
    for method, path, body in (("post", f"/api/cases/{case['id']}/actual-costs", {"kind": "other", "description": "x",
                                                                                   "amount": "1", "currency": "IRR"}),
                               ("patch", f"/api/sales-orders/{so['id']}", {"notes": "x"}),
                               ("post", "/api/sales-invoices", {"sales_order_id": so["id"], "over_delivered_reason": "x",
                                                                "lines": [{"description": "x", "quantity": "1", "unit_price": "1"}]}),
                               ("post", f"/api/sales-invoices/{inv['id']}/moadian", {"moadian_note": "x"})):
        r = getattr(client, method)(path, json=body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "case_closed", (path, r.text)
    assert client.patch(f"/api/cases/{case['id']}", json={"notes": "یادداشت پس از بستن"}).status_code == 200
    r = client.patch(f"/api/cases/{case['id']}", json={"status": "open"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "use_reopen"
    # the snapshot is frozen: later reads return it unchanged
    again = client.get(f"/api/cases/{case['id']}/profit").json()
    assert again["computed_at"] == snap["computed_at"] and again["frozen"] is True
    # reopen: a reason, the snapshot removed (event), items derived again
    assert client.post(f"/api/cases/{case['id']}/reopen", json={"reason": " "}).status_code == 422
    r = client.post(f"/api/cases/{case['id']}/reopen", json={"reason": "اصلاح فاکتور"})
    assert r.status_code == 200 and r.json()["frozen"] is False
    assert statuses(client, case) == {"delivered"}
    assert client.get(f"/api/cases/{case['id']}").json()["status"] == "open"
    assert db.execute(text("SELECT count(*) FROM ops.deal_result WHERE case_id = :c"), {"c": case["id"]}).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM core.event WHERE entity_type = 'deal_result' AND action = 'removed' "
                           "AND entity_id = :c"), {"c": case["id"]}).scalar() == 1
    assert client.patch(f"/api/sales-orders/{so['id']}", json={"notes": "x"}).status_code == 200


def test_close_with_reasons_for_remaining_problems(client):
    case, party, sup, so, po = import_deal(client)
    check = client.get(f"/api/cases/{case['id']}/close-checklist").json()
    reasons = {p["code"]: "به‌صورت دستی بررسی شد" for p in check["problems"]}
    r = client.post(f"/api/cases/{case['id']}/close", json={"reasons": reasons, "confirm_cancel_open": True})
    assert r.status_code == 200, r.text
    ev = events(client, "case", case["id"], "deal_closed")[0]["data"]
    assert set(ev["reasons"]) == set(reasons) and set(ev["problems"]) == set(reasons)


# ---- ratings ---------------------------------------------------------------------------------------------------------

def test_ratings_per_party_per_case_party_page_and_suggestions(client):
    case, party, sup, so, po, inv, pi = settled(client)
    body = {"party_id": sup["id"], "role": "supplier", "quality": 4, "timeliness": 5, "communication": 3, "price": 4}
    r = client.post(f"/api/cases/{case['id']}/ratings", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "case_not_closed"
    client.post(f"/api/cases/{case['id']}/close", json={"confirm_cancel_open": True})
    assert client.post(f"/api/cases/{case['id']}/ratings", json=body).status_code == 200
    r = client.post(f"/api/cases/{case['id']}/ratings", json={**body, "role": "supplier", "payment_behavior": 2})
    assert r.status_code == 422 and r.json()["error"]["code"] == "criterion_not_for_role"
    r = client.post(f"/api/cases/{case['id']}/ratings", json={"party_id": party["id"], "role": "customer", "payment_behavior": 5,
                                                               "quality": 4, "note": "پرداخت به‌موقع"})
    assert r.status_code == 200
    r = client.post(f"/api/cases/{case['id']}/ratings", json={"party_id": party["id"], "role": "supplier", "quality": 3})
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_a_party_of_the_deal"
    # a second save replaces the first
    client.post(f"/api/cases/{case['id']}/ratings", json={**body, "quality": 2})
    summary = client.get(f"/api/parties/{sup['id']}/finance").json()["ratings"]
    assert summary["count"] == 1 and summary["average"]["quality"] == 2.0 and summary["average"]["timeliness"] == 5.0
    assert summary["last"][0]["case_title"] == client.get(f"/api/cases/{case['id']}").json()["title"]
    # the Phase 5 suggestions show the supplier's average (2 + 5 + 3 + 4) / 4 = 3.5
    items = client.post("/api/line-items/bulk", json={"case_id": client.post("/api/cases", json={"title": "next"}).json()["id"],
                                                      "items": [{"name": "Pump 2", "hs_code": "841370"}]}).json()["items"]
    client.post(f"/api/capabilities/party/{sup['id']}", json={"kind": "hs", "code": "8413"})
    rows = client.get("/api/rfqs/supplier-suggestions", params={"item_ids": [items[0]["id"]]}).json()
    mine = next(r for r in rows if r["party_id"] == sup["id"])
    assert mine["rating"] == {"average": 3.5, "count": 1}


# ---- the workspace -----------------------------------------------------------------------------------------------------

def test_aging_buckets_and_payables_windows_on_a_fixed_clock(client, db):
    from app.modules.finance import workspace

    _setup_letterhead(client)
    client.patch("/api/settings", json=SELLER)
    case, party, so, pos = deal(client)
    deliver(client, so)
    valve = next(i for i in so["items"] if i["description"] == "Valve")
    numbers = {}
    for past in (10, 45, 75, 120):
        inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "issue_date": day(-past - 30),
                                                       "due_date": day(-past),
                                                       "lines": [{"sales_order_item_id": valve["id"], "quantity": "1"}]}).json()
        numbers[past] = client.post(f"/api/sales-invoices/{inv['id']}/issue", json={"issue_date": day(-past - 30)}).json()["id"]
    db.expire_all()
    out = workspace.receivables(db, date.today())
    mine = {r["invoice_id"]: r for r in out["invoices"] if r["case_id"] == case["id"]}
    assert [mine[numbers[p]]["bucket"] for p in (10, 45, 75, 120)] == ["0-30", "31-60", "61-90", "90+"]
    assert mine[numbers[45]]["days_past_due"] == 45
    row = next(r for r in out["by_party"] if r["party_id"] == party["id"])
    price = D(valve["unit_price"])
    assert all(D(row[b]) == price for b in workspace.BUCKETS) and D(row["total"]) == 4 * price
    # payables: overdue / within 7 / within 30 / later
    usd = pos["USD"]
    client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(0), "items": [
        {"purchase_order_item_id": usd["items"][0]["id"], "quantity": "10"}]})
    ids = {}
    for n, due in ((1, -1), (2, 5), (3, 20), (4, 60)):
        pi = client.post("/api/purchase-invoices", json={"purchase_order_id": usd["id"], "supplier_invoice_no": f"P{n}-{tag()}",
                                                         "invoice_date": day(-30), "due_date": day(due),
                                                         "lines": [{"purchase_order_item_id": usd["items"][0]["id"], "quantity": "1"}]}).json()
        ids[due] = pi["id"]
    db.expire_all()
    pay = {r["id"]: r for r in workspace.payables(db, date.today())["items"]}
    assert [pay[ids[d]]["window"] for d in (-1, 5, 20, 60)] == ["overdue", "due_7", "due_30", "later"]


def test_deals_list_vat_and_csv_exports_with_bom_and_row_counts(client):
    case, party, sup, so, po, inv, pi = settled(client)
    deals = {d["case_id"]: d for d in client.get("/api/finance/deals").json()}
    d = deals[case["id"]]
    assert D(d["revenue"]["actual"]["deal"]) == D(inv["subtotal"]) and d["status"] == "open"
    assert d["margin_percent"]["planned"] == "20.00"
    assert case["id"] in {x["case_id"] for x in client.get("/api/finance/deals", params={"state": "open"}).json()}
    assert case["id"] not in {x["case_id"] for x in client.get("/api/finance/deals", params={"state": "closed"}).json()}
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "customs_clearance", "description": "ترخیص",
                                                                "amount": "1000000", "currency": "IRR", "vat_amount": "100000",
                                                                "incurred_on": day(0)})
    vat = client.get("/api/finance/vat", params={"date_from": day(0), "date_to": day(0)}).json()
    assert vat["currency"] == "IRR" and len(vat["periods"]) == 1 and D(vat["periods"][0]["input"]) >= 100000
    client.patch("/api/me", json={"language": "en", "calendar": "gregorian"})
    r = client.get("/api/finance/exports/sales_invoices.csv", params={"date_from": day(0), "date_to": day(0)})
    assert r.status_code == 200 and r.content[:3] == b"\xef\xbb\xbf" and "text/csv" in r.headers["content-type"]
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert rows[0][:4] == ["Number", "Kind", "Status", "Issue date"] and rows[0][4] == "issue_date (ISO)"
    mine = [row for row in rows[1:] if row[0] == inv["number"]]
    assert len(mine) == len(inv["lines"]) and mine[0][4] == day(0)
    client.patch("/api/me", json={"language": "fa", "calendar": "jalali"})
    try:
        r = client.get("/api/finance/exports/payments.csv")
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        assert rows[0][0] == "تاریخ پرداخت" and rows[0][1] == "paid_on (ISO)"
        from app.modules.sourcing.jalali import to_jalali

        y, m, dd = to_jalali(date.today())
        assert any(row[0] == f"{y}/{m:02d}/{dd:02d}" and row[1] == day(0) for row in rows[1:])
        z = client.get("/api/finance/exports/all.zip", params={"date_from": day(-60), "date_to": day(0)})
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(z.content)) as archive:
            names = sorted(archive.namelist())
            assert names == sorted(f"{n}.csv" for n in ("sales_invoices", "purchase_invoices", "payments", "actual_costs",
                                                         "deals", "receivables"))
            assert all(archive.read(n)[:3] == b"\xef\xbb\xbf" for n in names)
    finally:
        client.patch("/api/me", json={"language": "en", "calendar": "gregorian"})


# ---- integrations ---------------------------------------------------------------------------------------------------------

def test_command_center_finance_section_on_a_fixed_dataset(client, db):
    from app.modules.finance import dashboard

    case, party, sup, so, po = import_deal(client)
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "lines": [
        {"sales_order_item_id": so["items"][0]["id"], "quantity": "4"}]}).json()
    client.post(f"/api/sales-invoices/{inv['id']}/issue", json={"issue_date": day(-40)})
    ms = client.post("/api/payment-milestones", json={"purchase_order_id": po["id"], "kind": "prepayment", "amount": "10",
                                                      "amount_currency": "USD"}).json()
    payment(client, ms["id"], "10", day(-1), fx_rate_to_base="530000")
    from app.core.db import new_session

    with new_session() as s:
        s.execute(text("UPDATE ops.payment_record SET fx_rate_to_base = NULL, base_amount = NULL WHERE milestone_id = :m"),
                  {"m": ms["id"]})
        s.commit()
    db.expire_all()
    out = dashboard.summary(db, date.today())
    mine = lambda key: [x for x in out[key] if x["case_id"] == case["id"]]  # noqa: E731
    assert [x["number"] for x in mine("receivables_overdue")] and mine("moadian_pending")[0]["moadian_status"] == "not_sent"
    assert D(mine("delivered_not_invoiced")[0]["quantity"]) == 6 and mine("received_not_invoiced")
    assert len(mine("payments_without_rate")) == 1 and mine("ready_to_close") == []
    cc = client.get("/api/command-center").json()
    assert set(cc["finance"]) == {"receivables_overdue", "payables_due", "delivered_not_invoiced", "received_not_invoiced",
                                  "moadian_pending", "payments_without_rate", "ready_to_close"}


def test_search_invoice_numbers_tax_ids_supplier_numbers_payment_references(client):
    case, party, sup, so, po, inv, pi = settled(client)
    sales = client.get(f"/api/sales-invoices/{inv['id']}").json()
    rec = [r for r in records(client, case) if r["direction"] == "in"][0]
    for q, kind, wanted in ((sales["number"], "sales_invoice", inv["id"]), (sales["moadian_tax_id"], "sales_invoice", inv["id"]),
                            (pi["supplier_invoice_no"], "purchase_invoice", pi["id"]), (rec["reference"], "payment", rec["id"])):
        flat = str(client.get("/api/search", params={"q": q}).json())
        assert wanted in flat, (kind, q)


def test_party_delete_counts_and_cascade_delete_of_a_closed_deal(client, db):
    case, party, sup, so, po, inv, pi = settled(client)
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "storage", "description": "انبار", "amount": "100",
                                                                "currency": "IRR", "party_id": sup["id"]})
    r = client.delete(f"/api/parties/{party['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"]["sales_invoices"] == 1
    r = client.delete(f"/api/parties/{sup['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"]["purchase_invoices"] == 1
    assert r.json()["error"]["details"]["actual_costs"] == 1
    check = client.get(f"/api/cases/{case['id']}/close-checklist").json()
    client.post(f"/api/cases/{case['id']}/close", json={"reasons": {p["code"]: "x" for p in check["problems"]},
                                                        "confirm_cancel_open": True})
    client.post(f"/api/cases/{case['id']}/ratings", json={"party_id": sup["id"], "role": "supplier", "quality": 4})
    r = client.request("DELETE", f"/api/cases/{case['id']}", params={"cascade": "true"}, json={"confirm_title": case["title"]})
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert counts["sales_invoices"] == 1 and counts["sales_invoice_lines"] == len(inv["lines"]) and counts["purchase_invoices"] == 1
    assert counts["payment_allocations"] == 2 and counts["actual_costs"] == 1 and counts["deal_results"] == 1
    assert counts["party_ratings"] == 1 and counts["sales_orders"] == 1
    for table in ("sales_invoice", "purchase_invoice", "actual_cost", "deal_result", "party_rating"):
        assert db.execute(text(f"SELECT count(*) FROM ops.{table} WHERE case_id = :c"), {"c": case["id"]}).scalar() == 0


def test_audit_rows_and_events_for_every_new_table(client, db):
    case, party, sup, so, po, inv, pi = settled(client)
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "storage", "description": "انبار", "amount": "100",
                                                                "currency": "IRR"})
    client.post(f"/api/cases/{case['id']}/close", json={"reasons": {"costs_unpaid": "x"}, "confirm_cancel_open": True})
    client.post(f"/api/cases/{case['id']}/ratings", json={"party_id": sup["id"], "role": "supplier", "quality": 4})
    for table in ("invoice_sequence", "sales_invoice", "sales_invoice_line", "purchase_invoice", "purchase_invoice_line",
                  "actual_cost", "payment_allocation", "deal_result", "party_rating"):
        n = db.execute(text("SELECT count(*) FROM core.audit WHERE table_name = :t"), {"t": f"ops.{table}"}).scalar()
        assert n > 0, table
    assert db.execute(text("SELECT count(*) FROM core.audit WHERE table_name = 'core.task'")).scalar() > 0
    for entity in ("sales_invoice", "purchase_invoice", "actual_cost", "payment_allocation", "party_rating", "task"):
        assert db.execute(text("SELECT count(*) FROM core.event WHERE entity_type = :e"), {"e": entity}).scalar() > 0, entity


def test_unknown_fields_and_constraint_errors_persist_nothing(client, db):
    case, party, sup, so, po = import_deal(client)
    for path, body in ((f"/api/cases/{case['id']}/actual-costs", {"kind": "other", "description": "x", "amount": "1",
                                                                  "currency": "IRR", "bogus": 1}),
                       (f"/api/cases/{case['id']}/close", {"bogus": 1}),
                       (f"/api/cases/{case['id']}/ratings", {"party_id": sup["id"], "role": "supplier", "bogus": 1}),
                       ("/api/payment-records/00000000-0000-0000-0000-000000000000/allocations", {"allocations": [], "x": 1})):
        assert client.post(path, json=body).status_code == 422, path
    before = db.execute(text("SELECT count(*) FROM ops.actual_cost WHERE case_id = :c"), {"c": case["id"]}).scalar()
    r = client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "other", "description": "   ", "amount": "1",
                                                                    "currency": "IRR"})
    assert r.status_code == 422 and r.json()["error"]["details"]["constraint"] == "actual_cost_description_check"
    db.expire_all()
    assert db.execute(text("SELECT count(*) FROM ops.actual_cost WHERE case_id = :c"), {"c": case["id"]}).scalar() == before


def test_migrations_0014_0015_up_down_up_with_phase8_data():
    from alembic import command

    from app.cli import alembic_config
    from app.core import dbadmin
    from app.core.config import get_config
    from tests.conftest import create_empty_database, superuser_conninfo

    name = "boms_test_p9_finance_migrations"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    new_tables = {"ops.sales_invoice", "ops.purchase_invoice", "ops.payment_allocation", "ops.actual_cost", "ops.deal_result",
                  "ops.party_rating", "ops.invoice_sequence", "core.task"}

    def tables():
        with engine.connect() as conn:
            return set(conn.execute(text("SELECT schemaname || '.' || tablename FROM pg_tables "
                                         "WHERE schemaname IN ('ops', 'core')")).scalars())

    def p8_rows():
        with engine.connect() as conn:
            return conn.execute(text("SELECT (SELECT count(*) FROM ops.sales_order), (SELECT count(*) FROM ops.payment_record), "
                                     "(SELECT sum(amount) FROM ops.payment_record)")).one()

    try:
        command.upgrade(cfg, "0013")
        with engine.begin() as conn:      # Phase 8 data: a confirmed sales order with a milestone and a payment
            conn.execute(text("INSERT INTO sys.currency (code, name_fa, name_en, minor_units) VALUES ('IRR', 'ریال', 'Rial', 0)"))
            party = conn.execute(text("INSERT INTO core.party (name_fa) VALUES ('مشتری') RETURNING id")).scalar()
            case = conn.execute(text("INSERT INTO ops.\"case\" (title, party_id) VALUES ('Deal', :p) RETURNING id"), {"p": party}).scalar()
            so = conn.execute(text("INSERT INTO ops.sales_order (case_id, number, customer_party_id, source, currency, status, "
                                   "no_document_reason) VALUES (:c, 'SO-1405-0001', :p, 'manual', 'IRR', 'confirmed', 'x') "
                                   "RETURNING id"),
                              {"c": case, "p": party}).scalar()
            ms = conn.execute(text("INSERT INTO ops.payment_milestone (case_id, direction, sales_order_id, party_id, kind, amount, "
                                   "amount_currency) VALUES (:c, 'in', :s, :p, 'prepayment', 100, 'IRR') RETURNING id"),
                              {"c": case, "s": so, "p": party}).scalar()
            conn.execute(text("INSERT INTO ops.payment_record (milestone_id, amount, amount_currency, paid_on) "
                              "VALUES (:m, 100, 'IRR', current_date)"), {"m": ms})
        before = p8_rows()
        assert not (new_tables & tables())
        command.upgrade(cfg, "head")
        assert new_tables <= tables() and p8_rows() == before
        with engine.connect() as conn:
            assert conn.execute(text("SELECT fx_rate_to_base, base_amount FROM ops.payment_record")).one() == (None, None)
        command.downgrade(cfg, "0013")
        assert not (new_tables & tables()) and p8_rows() == before
        command.upgrade(cfg, "head")
        assert new_tables <= tables() and p8_rows() == before
    finally:
        engine.dispose()
        dbadmin.drop_database(superuser_conninfo(), name)


def test_backup_and_restore_test_cover_every_table_with_finance_data(client):
    from app.core.db import get_engine
    from app.modules.system import backup

    case, party, sup, so, po, inv, pi = settled(client)
    client.post(f"/api/cases/{case['id']}/actual-costs", json={"kind": "storage", "description": "انبار", "amount": "100",
                                                                "currency": "IRR"})
    client.post(f"/api/cases/{case['id']}/close", json={"reasons": {"costs_unpaid": "x"}, "confirm_cancel_open": True})
    client.post(f"/api/cases/{case['id']}/ratings", json={"party_id": sup["id"], "role": "supplier", "quality": 4})
    run_id = backup.run_backup("manual", source="script")
    result = backup.restore_test(run_id, source="script")
    with get_engine().connect() as conn:
        counts = backup.table_counts(conn)
    assert result["status"] == "passed", result
    assert result["details"]["tables_checked"] == len(counts) and result["details"]["row_count_mismatches"] == {}
    for table in ("ops.sales_invoice", "ops.sales_invoice_line", "ops.purchase_invoice", "ops.payment_allocation",
                  "ops.actual_cost", "ops.deal_result", "ops.party_rating", "ops.invoice_sequence", "core.task"):
        assert counts[table] > 0, table

