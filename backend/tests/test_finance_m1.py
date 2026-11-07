"""v0.8.0 milestone 1: sales invoices (numbering, lines from deliveries, issue rules, Moadian, notes, outputs) and
supplier invoices with matching."""
import io
import re
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.db import new_session
from tests.test_execution_m1 import day
from tests.test_execution_m3 import deal
from tests.test_listings_store import tag
from tests.test_quotes import CHROMIUM, _setup_letterhead
from tests.test_sourcing_inquiries import events

SELLER = {"company.name_fa": "شرکت بازرگانی کیمیا", "company.name_en": "Kimia Trading Co.",
          "company.national_id": "10101234567", "company.economic_code": "411111111111"}


@pytest.fixture
def seller(client):
    _setup_letterhead(client)
    client.patch("/api/settings", json=SELLER)
    yield
    client.patch("/api/settings", json={"company.national_id": "", "company.economic_code": ""})


def deliver(client, so, quantities: dict | None = None, on: int = 0):
    """Deliver ``quantities`` (sales order item id -> qty; default everything)."""
    items = [{"sales_order_item_id": i["id"], "quantity": str((quantities or {}).get(i["id"], i["quantity"]))}
             for i in so["items"] if (quantities is None or i["id"] in quantities)]
    r = client.post("/api/deliveries", json={"sales_order_id": so["id"], "delivered_on": day(on), "items": items})
    assert r.status_code == 201, r.text
    return r.json()


def domestic(client, party):
    r = client.patch(f"/api/parties/{party['id']}", json={"country_iso2": "IR", "national_id": "14000000000",
                                                         "economic_code": "411000000000"})
    assert r.status_code == 200, r.text


def by_desc(so):
    return {i["description"]: i for i in so["items"]}


# ---- numbering ------------------------------------------------------------------------------------------------------

def test_invoice_numbers_are_gap_free_under_concurrency(client):
    from app.modules.finance.sales_invoices import next_number

    year = 3000 + int(tag(), 16) % 5000
    first = new_session()
    n1 = next_number(first, "invoice", year)
    result = {}

    def other():
        with new_session() as s2:
            result["n2"] = next_number(s2, "invoice", year)
            s2.commit()

    thread = threading.Thread(target=other)
    thread.start()
    thread.join(timeout=1)
    assert thread.is_alive()                       # waits for the first transaction
    first.commit()
    first.close()
    thread.join(timeout=10)
    assert (n1, result["n2"]) == (f"INV-{year}-0001", f"INV-{year}-0002")
    with new_session() as s3:                      # a rolled-back issue gives its number back
        assert next_number(s3, "invoice", year) == f"INV-{year}-0003"
        s3.rollback()
    with new_session() as s4:
        assert next_number(s4, "invoice", year) == f"INV-{year}-0003"
        assert next_number(s4, "credit_note", year) == f"CN-{year}-0001"
        s4.commit()


def test_two_invoices_issued_in_parallel_get_consecutive_numbers(client, seller):
    from app.modules.finance import sales_invoices as service

    case, party, so, pos = deal(client)
    deliver(client, so)
    valve = by_desc(so)["Valve"]
    pump = next(i for i in so["items"] if i["id"] != valve["id"])
    a = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "lines": [
        {"sales_order_item_id": valve["id"], "quantity": "1"}]}).json()
    b = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "lines": [
        {"sales_order_item_id": pump["id"], "quantity": "1"}]}).json()
    barrier = threading.Barrier(2)
    numbers, errors = [], []

    def issue(invoice_id):
        try:
            with new_session() as s:
                barrier.wait()
                numbers.append(service.issue(s, invoice_id, {}, "gregorian", "script").number)
                s.commit()
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(repr(exc))

    import uuid

    threads = [threading.Thread(target=issue, args=(uuid.UUID(x["id"]),)) for x in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    seqs = sorted(int(n.rsplit("-", 1)[1]) for n in numbers)
    assert len(set(numbers)) == 2 and seqs[1] == seqs[0] + 1 and all(n.startswith(f"INV-{date.today().year}-") for n in numbers)


# ---- lines from deliveries ------------------------------------------------------------------------------------------

def test_lines_default_to_delivered_not_invoiced_over_delivered_needs_a_reason_over_ordered_refused(client, seller):
    case, party, so, pos = deal(client)
    valve = by_desc(so)["Valve"]                      # 10 ordered
    r = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "nothing_to_invoice"
    deliver(client, so, {valve["id"]: "6"})
    r = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "draft" and inv["number"] is None and inv["language"] == "en"
    assert [(ln["sales_order_item_id"], Decimal(ln["quantity"])) for ln in inv["lines"]] == [(valve["id"], 6)]
    assert Decimal(inv["subtotal"]) == 6 * Decimal(valve["unit_price"])
    state = {x["sales_order_item_id"]: x for x in client.get(f"/api/sales-orders/{so['id']}/invoicing").json()["items"]}
    assert Decimal(state[valve["id"]]["invoiced"]) == 6 and Decimal(state[valve["id"]]["to_invoice"]) == 0
    # more than delivered: a reason; more than ordered: refused
    body = {"sales_order_id": so["id"], "lines": [{"sales_order_item_id": valve["id"], "quantity": "3"}]}
    r = client.post("/api/sales-invoices", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_delivered_reason_required"
    r = client.post("/api/sales-invoices", json={**body, "over_delivered_reason": "پیش‌فاکتور به درخواست مشتری"})
    assert r.status_code == 201 and r.json()["over_delivered_reason"]
    ev = events(client, "sales_invoice", r.json()["id"], "create")[0]["data"]
    assert ev["over_delivered_reason"] == "پیش‌فاکتور به درخواست مشتری"
    r = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "over_delivered_reason": "x",
                                                 "lines": [{"sales_order_item_id": valve["id"], "quantity": "2"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "over_ordered"
    # «invoice the rest»: the remaining delivered quantity after more deliveries
    pump = next(i for i in so["items"] if i["id"] != valve["id"])
    deliver(client, so, {valve["id"]: "4", pump["id"]: pump["quantity"]})          # the rest of everything
    rest = client.post(f"/api/sales-orders/{so['id']}/invoice-rest")
    assert rest.status_code == 201
    got = {ln["sales_order_item_id"]: Decimal(ln["quantity"]) for ln in rest.json()["lines"]}
    assert valve["id"] in got and got[valve["id"]] == 1 and len(got) == 2      # 10 delivered − 9 invoiced; the pump


# ---- issue -------------------------------------------------------------------------------------------------------

def test_issue_needs_the_seller_and_buyer_ids_and_sets_moadian_by_country(client, monkeypatch):
    from app.modules.costing import service as costing

    real = costing.parameter_in_force

    class Vat:
        rate_percent = Decimal("10")

    monkeypatch.setattr(costing, "parameter_in_force",
                        lambda db, kind, deal_type, on: Vat() if kind == "vat" else real(db, kind, deal_type, on))
    _setup_letterhead(client)
    client.patch("/api/settings", json={"company.national_id": "", "company.economic_code": ""})
    case, party, so, pos = deal(client)
    deliver(client, so)
    client.patch(f"/api/parties/{party['id']}", json={"country_iso2": "IR"})
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]}).json()
    assert inv["language"] == "fa" and Decimal(inv["vat_rate"]) == 10                 # domestic: VAT in force
    assert Decimal(inv["vat_amount"]) == (Decimal(inv["subtotal"]) * Decimal("0.1")).quantize(Decimal(1))  # IRR: 0 decimals
    r = client.post(f"/api/sales-invoices/{inv['id']}/issue")
    assert r.status_code == 422 and r.json()["error"]["code"] == "issue_requirements_missing"
    assert r.json()["error"]["details"]["missing"] == ["company.national_id", "company.economic_code",
                                                       "customer.national_id", "customer.economic_code"]
    client.patch("/api/settings", json=SELLER)
    try:
        domestic(client, party)
        r = client.post(f"/api/sales-invoices/{inv['id']}/issue")
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["status"] == "issued" and out["number"].startswith("INV-") and out["moadian_status"] == "not_sent"
        assert out["issue_date"] == day(0) and out["due_date"] == day(30)                 # finance.payment_days
        # locked after issue: no edit, no delete
        r = client.patch(f"/api/sales-invoices/{inv['id']}", json={"notes": "x"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "invoice_locked"
        assert client.delete(f"/api/sales-invoices/{inv['id']}").status_code == 409
        # Moadian ID and status typed by the owner
        r = client.post(f"/api/sales-invoices/{inv['id']}/moadian", json={"moadian_status": "accepted"})
        assert r.status_code == 422 and r.json()["error"]["code"] == "moadian_tax_id_required"
        r = client.post(f"/api/sales-invoices/{inv['id']}/moadian", json={"moadian_status": "accepted",
                                                                          "moadian_tax_id": "A1B2C3D4E5F6G7H8I9J0K1"})
        assert r.status_code == 200 and r.json()["moadian_status"] == "accepted" and r.json()["moadian_on"] == day(0)
        assert events(client, "sales_invoice", inv["id"], "moadian")
        # export (en) to a foreign customer: not_required, no VAT
        case2, party2, so2, _ = deal(client)
        deliver(client, so2)
        inv2 = client.post("/api/sales-invoices", json={"sales_order_id": so2["id"]}).json()
        assert inv2["language"] == "en" and Decimal(inv2["vat_rate"]) == 0
        out2 = client.post(f"/api/sales-invoices/{inv2['id']}/issue").json()
        assert out2["moadian_status"] == "not_required"
    finally:
        client.patch("/api/settings", json={"company.national_id": "", "company.economic_code": ""})


def test_vat_percent_editable_on_the_draft_with_a_note(client, seller):
    case, party, so, pos = deal(client)
    deliver(client, so)
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]}).json()
    r = client.patch(f"/api/sales-invoices/{inv['id']}", json={"vat_rate": "9"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "vat_note_required"
    r = client.patch(f"/api/sales-invoices/{inv['id']}", json={"vat_rate": "9", "vat_note": "معافیت جزئی"})
    assert r.status_code == 200 and Decimal(r.json()["vat_rate"]) == 9
    sub = Decimal(r.json()["subtotal"])
    assert Decimal(r.json()["vat_amount"]) == (sub * Decimal("0.09")).quantize(Decimal(1)) and \
        Decimal(r.json()["total"]) == sub + Decimal(r.json()["vat_amount"])


def test_credit_and_debit_notes_adjust_the_balance_and_cancel_only_without_payments(client, seller, db):
    case, party, so, pos = deal(client)
    deliver(client, so)
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"]}).json()
    r = client.post(f"/api/sales-invoices/{inv['id']}/credit-note", json={"reason": "x", "lines": [
        {"description": "تخفیف", "quantity": "1", "unit_price": "100"}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invoice_not_issued"      # only an issued invoice
    inv = client.post(f"/api/sales-invoices/{inv['id']}/issue").json()
    total = Decimal(inv["total"])
    assert Decimal(inv["balance_due"]) == total and inv["payment_status"] == "unpaid"
    cn = client.post(f"/api/sales-invoices/{inv['id']}/credit-note", json={"reason": "برگشت ۱ عدد", "lines": [
        {"description": "Valve returned", "quantity": "1", "unit_price": "1000"}]})
    assert cn.status_code == 201, cn.text
    cn = cn.json()
    assert cn["kind"] == "credit_note" and cn["corrects_number"] == inv["number"] and cn["number"] is None
    assert Decimal(client.get(f"/api/sales-invoices/{inv['id']}").json()["balance_due"]) == total   # a draft note: no effect
    cn = client.post(f"/api/sales-invoices/{cn['id']}/issue").json()
    assert cn["number"].startswith("CN-")
    dn = client.post(f"/api/sales-invoices/{inv['id']}/debit-note", json={"reason": "هزینهٔ حمل", "lines": [
        {"description": "Freight", "quantity": "1", "unit_price": "250"}]}).json()
    dn = client.post(f"/api/sales-invoices/{dn['id']}/issue").json()
    assert dn["number"].startswith("DN-")
    after = client.get(f"/api/sales-invoices/{inv['id']}").json()
    assert Decimal(after["balance_due"]) == total - Decimal(cn["total"]) + Decimal(dn["total"])
    assert [n["kind"] for n in after["notes_list"]] == ["credit_note", "debit_note"]
    r = client.post(f"/api/sales-invoices/{inv['id']}/credit-note", json={"reason": "x", "lines": [
        {"description": "too much", "quantity": "1", "unit_price": str(total * 2)}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "credit_above_invoice"
    # cancel: a reason; not while notes are issued; not with payments (allocation added directly here)
    r = client.post(f"/api/sales-invoices/{inv['id']}/cancel", json={"reason": "اشتباه"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invoice_has_notes"
    other = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "over_delivered_reason": "x",
                                                     "lines": [{"description": "Service", "quantity": "1", "unit_price": "10"}]}).json()
    other = client.post(f"/api/sales-invoices/{other['id']}/issue").json()
    from sqlalchemy import text

    ms = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "balance", "amount": "10",
                                                      "amount_currency": so["currency"]}).json()
    rec = client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": "10", "paid_on": day(0)}).json()
    record_id = (rec.get("records") or [{}])[-1].get("id") or db.execute(text(
        "SELECT id FROM ops.payment_record WHERE milestone_id = :m"), {"m": ms["id"]}).scalar()
    db.execute(text("INSERT INTO ops.payment_allocation (payment_record_id, sales_invoice_id, amount, target_amount) "
                    "VALUES (:p, :i, 10, 10)"), {"p": record_id, "i": other["id"]})
    db.commit()
    r = client.post(f"/api/sales-invoices/{other['id']}/cancel", json={"reason": "اشتباه"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invoice_has_payments"
    assert client.get(f"/api/sales-invoices/{other['id']}").json()["payment_status"] == "paid"
    db.execute(text("DELETE FROM ops.payment_allocation WHERE sales_invoice_id = :i"), {"i": other["id"]})
    db.commit()
    r = client.post(f"/api/sales-invoices/{other['id']}/cancel", json={"reason": " "})
    assert r.status_code == 422
    r = client.post(f"/api/sales-invoices/{other['id']}/cancel", json={"reason": "اشتباه در ثبت"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["number"] == other["number"]


# ---- outputs -------------------------------------------------------------------------------------------------------

def _text(page: str) -> str:
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", page, flags=re.S))


def test_outputs_fa_jalali_persian_digits_words_and_en_gregorian_draft_mark(client, seller):
    case, party, so, pos = deal(client)
    deliver(client, so)
    domestic(client, party)
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "language": "fa"}).json()
    client.patch("/api/me", json={"calendar": "gregorian", "digits": "latin"})
    page = client.get(f"/api/sales-invoices/{inv['id']}/print").text
    assert "صورتحساب فروش کالا و خدمات" in page and "پیش‌نویس" in page and "class='watermark'" in page
    assert "مشخصات فروشنده" in page and "مشخصات خریدار" in page and "۱۰۱۰۱۲۳۴۵۶۷" in page   # IDs in Persian digits
    assert "مبلغ به حروف" in page and "ریال" in page
    inv = client.post(f"/api/sales-invoices/{inv['id']}/issue").json()
    page = client.get(f"/api/sales-invoices/{inv['id']}/print").text
    from app.modules.quotes.output import _fmt_date, _fmt_num

    assert "class='watermark'" not in page and _fmt_date(date.today(), "jalali", "fa") in page
    assert date.today().isoformat() not in _text(page)
    assert _fmt_num(Decimal(inv["total"]), 0, "fa") in page                      # amounts in Persian digits
    # en: Gregorian, Latin digits, HS code column, DRAFT before issue
    case2, party2, so2, _ = deal(client)
    deliver(client, so2)
    inv2 = client.post("/api/sales-invoices", json={"sales_order_id": so2["id"], "country_of_origin": "Iran",
                                                    "packages": "3 pallets"}).json()
    client.patch("/api/me", json={"calendar": "jalali", "digits": "fa"})
    try:
        page = client.get(f"/api/sales-invoices/{inv2['id']}/print").text
    finally:
        client.patch("/api/me", json={"calendar": "gregorian", "digits": "latin"})
    assert "Commercial invoice" in page and "DRAFT" in page and "HS code" in page and "3 pallets" in page
    assert not re.search("[۰-۹]", _text(page))
    # Word re-opens; DRAFT in the file name before issue
    r = client.post(f"/api/sales-invoices/{inv2['id']}/outputs", json={"format": "docx"})
    assert r.status_code == 201 and r.json()["filename"].endswith("-DRAFT.docx")
    from docx import Document

    data = client.get(f"/api/documents/{r.json()['document_id']}/download").content
    doc = Document(io.BytesIO(data))
    assert "Commercial invoice" in "\n".join(p.text for p in doc.paragraphs) and doc.tables
    r = client.post(f"/api/sales-invoices/{inv['id']}/outputs", json={"format": "docx"})
    assert r.json()["filename"] == f"{inv['number']}.docx"
    text_all = "\n".join(p.text for p in Document(io.BytesIO(client.get(
        f"/api/documents/{r.json()['document_id']}/download").content)).paragraphs)
    assert "صورتحساب فروش کالا و خدمات" in text_all and "مبلغ به حروف" in text_all


def test_total_in_persian_words():
    from app.modules.quotes.output import total_in_words

    assert total_in_words(Decimal("1250000"), "IRR") == "یک میلیون و دویست و پنجاه هزار ریال"


@pytest.mark.skipif(not Path(CHROMIUM).exists(), reason="no Chromium-family browser in this test environment")
def test_pdf_one_page_for_a_short_invoice(client, seller):
    case, party, so, pos = deal(client)
    deliver(client, so)
    domestic(client, party)
    inv = client.post("/api/sales-invoices", json={"sales_order_id": so["id"], "language": "fa"}).json()
    inv = client.post(f"/api/sales-invoices/{inv['id']}/issue").json()
    client.patch("/api/settings", json={"pdf.browser_path": CHROMIUM})
    try:
        r = client.post(f"/api/sales-invoices/{inv['id']}/outputs", json={"format": "pdf"})
    finally:
        client.patch("/api/settings", json={"pdf.browser_path": None})
    assert r.status_code == 201, r.text
    data = client.get(f"/api/documents/{r.json()['document_id']}/download").content
    import fitz

    with fitz.open(stream=data, filetype="pdf") as pdf:
        assert pdf.page_count == 1
        content = "".join(page.get_text() for page in pdf)
    assert "Valve" in content


# ---- supplier invoices ---------------------------------------------------------------------------------------------

def test_supplier_invoice_matching_approve_with_a_reason_and_dispute_with_a_claim(client):
    case, party, so, pos = deal(client)
    usd = pos["USD"]
    item = usd["items"][0]                                                        # Valve x10
    r = client.post("/api/purchase-invoices", json={"purchase_order_id": usd["id"], "supplier_invoice_no": "S-1",
                                                    "invoice_date": day(0)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_lines"       # nothing received yet
    client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(0), "items": [
        {"purchase_order_item_id": item["id"], "quantity": "8"}]})
    r = client.post("/api/purchase-invoices", json={"purchase_order_id": usd["id"], "supplier_invoice_no": "S-1",
                                                    "invoice_date": day(0)})
    assert r.status_code == 201, r.text
    pi = r.json()
    assert pi["supplier_party_id"] == usd["supplier_party_id"] and pi["currency"] == "USD" and pi["due_date"] == day(30)
    assert [Decimal(ln["quantity"]) for ln in pi["lines"]] == [8] and pi["matching"]["differences"] == []
    row = pi["matching"]["rows"][0]
    assert (Decimal(row["ordered"]), Decimal(row["received"]), Decimal(row["invoiced"])) == (10, 8, 8)
    assert client.post(f"/api/purchase-invoices/{pi['id']}/approve").json()["status"] == "approved"
    assert client.delete(f"/api/purchase-invoices/{pi['id']}").status_code == 409               # approved: never deleted
    # the same supplier invoice number twice: 409
    r = client.post("/api/purchase-invoices", json={"purchase_order_id": usd["id"], "supplier_invoice_no": "S-1",
                                                    "invoice_date": day(0), "lines": [{"purchase_order_item_id": item["id"], "quantity": "1"}]})
    assert r.status_code == 409
    # a second invoice: 2 more than received and a higher price
    price = Decimal(item["unit_price"]) + 1
    r = client.post("/api/purchase-invoices", json={"purchase_order_id": usd["id"], "supplier_invoice_no": "S-2",
                                                    "invoice_date": day(0), "vat_amount": "0",
                                                    "lines": [{"purchase_order_item_id": item["id"], "quantity": "4", "unit_price": str(price)}]})
    pi2 = r.json()
    flags = pi2["matching"]["differences"][0]["flags"]
    assert set(flags) == {"invoiced_above_received", "invoiced_above_ordered", "price_difference"}
    row = pi2["matching"]["rows"][0]
    assert Decimal(row["invoiced"]) == 12 and Decimal(row["price_difference"]) == 1
    r = client.post(f"/api/purchase-invoices/{pi2['id']}/approve", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invoice_differences"
    claim = client.post("/api/claims", json={"direction": "against_supplier", "kind": "other", "purchase_order_id": usd["id"]}).json()
    r = client.post(f"/api/purchase-invoices/{pi2['id']}/dispute", json={"reason": "مقدار و قیمت اشتباه", "claim_id": claim["id"]})
    assert r.status_code == 200 and r.json()["status"] == "disputed" and r.json()["claim_id"] == claim["id"]
    r = client.patch(f"/api/purchase-invoices/{pi2['id']}", json={"lines": [
        {"purchase_order_item_id": item["id"], "quantity": "2", "unit_price": str(price)}]})
    assert r.status_code == 200 and set(r.json()["matching"]["differences"][0]["flags"]) == {"invoiced_above_received",
                                                                                              "price_difference"}
    client.post("/api/receipts", json={"purchase_order_id": usd["id"], "received_on": day(1), "items": [
        {"purchase_order_item_id": item["id"], "quantity": "2"}]})
    flags = client.get(f"/api/purchase-invoices/{pi2['id']}").json()["matching"]["differences"][0]["flags"]
    assert flags == ["price_difference"]
    r = client.post(f"/api/purchase-invoices/{pi2['id']}/approve", json={"reason": "افزایش قیمت مواد اولیه پذیرفته شد"})
    assert r.status_code == 200 and r.json()["difference_reason"]
    assert events(client, "purchase_invoice", pi2["id"], "approve")[0]["data"]["differences"]


def test_supplier_invoice_without_po_for_a_service_party(client):
    case, party, so, pos = deal(client)
    broker = client.post("/api/parties", json={"name_en": f"Broker {tag()}", "roles": ["customs_broker"],
                                               "confirm_duplicate": True}).json()["party"]
    r = client.post("/api/purchase-invoices", json={"case_id": case["id"], "supplier_party_id": broker["id"], "currency": "IRR",
                                                    "supplier_invoice_no": "B-77", "invoice_date": day(0),
                                                    "lines": [{"description": "ترخیص", "quantity": "1", "unit_price": "5000000"}]})
    assert r.status_code == 201 and r.json()["purchase_order_id"] is None and Decimal(r.json()["total"]) == 5000000
    assert r.json()["matching"]["rows"] == []
    r = client.post("/api/purchase-invoices", json={"case_id": case["id"], "supplier_party_id": broker["id"],
                                                    "supplier_invoice_no": "B-78", "invoice_date": day(0),
                                                    "lines": [{"description": "x", "quantity": "1", "unit_price": "1"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "currency_required"
    r = client.post("/api/purchase-invoices", json={"case_id": case["id"], "supplier_party_id": broker["id"], "currency": "IRR",
                                                    "supplier_invoice_no": "B-79", "invoice_date": day(0), "due_date": day(-1),
                                                    "lines": [{"description": "x", "quantity": "1", "unit_price": "1"}]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "due_before_issue"


def test_unknown_fields_refused(client):
    for path, body in (("/api/sales-invoices", {"sales_order_id": "00000000-0000-0000-0000-000000000000", "bogus": 1}),
                       ("/api/purchase-invoices", {"supplier_invoice_no": "x", "invoice_date": day(0), "bogus": 1})):
        assert client.post(path, json=body).status_code == 422, path
