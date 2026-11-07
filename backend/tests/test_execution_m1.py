"""v0.7.0 Phase 8, milestone 1: sales orders (from a quote, a won tender, by hand), confirmation, amendments, the
order acknowledgement output, payment milestones with partial payments, the cash position and the ordering gate."""
import io
import re
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.errors import Conflict
from app.modules.execution import milestones as ms_service
from app.modules.sourcing.jalali import to_jalali
from tests.conftest import unique_bytes, upload
from tests.test_quotes import sent_quote
from tests.test_sourcing_inquiries import events
from tests.test_tenders_m3 import make_ready, new_proposal, tender_case


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def accepted_quote(client, partial: bool = True):
    case, items, party, sheet, quote = sent_quote(client)
    a, b = quote["items"]
    rows = [{"quote_item_id": a["id"], "outcome": "accepted"}]
    rows.append({"quote_item_id": b["id"], "outcome": "rejected", "outcome_reason": "price"} if partial
                else {"quote_item_id": b["id"], "outcome": "accepted"})
    r = client.put(f"/api/quotes/{quote['id']}/outcomes", json={"items": rows})
    assert r.status_code == 200, r.text
    return case, items, party, r.json()


def so_from_quote(client, quote, **body):
    r = client.post("/api/sales-orders/from-quote", json={"quote_id": quote["id"], **body})
    assert r.status_code == 201, r.text
    return r.json()


def a_document(client, name="contract.pdf"):
    r = upload(client, name, unique_bytes(name))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def confirmed_order(client, partial=False, **body):
    case, items, party, quote = accepted_quote(client, partial=partial)
    so = so_from_quote(client, quote, **body)
    r = client.post(f"/api/sales-orders/{so['id']}/confirm", json={"signed_document_id": a_document(client)})
    assert r.status_code == 200, r.text
    return case, items, party, quote, r.json()


# ---- creation ----------------------------------------------------------------------------------------------------

def test_from_a_partially_accepted_quote_only_the_accepted_items(client, db):
    case, items, party, quote = accepted_quote(client)
    detail = client.get(f"/api/cases/{case['id']}/execution").json()
    assert [c["quote_id"] for c in detail["candidates"]] == [quote["id"]]      # the «Create sales order» prompt
    so = so_from_quote(client, quote, customer_ref="PO-778", delivery_due_on=day(60))
    accepted = [i for i in quote["items"] if i["outcome"] == "accepted"]
    me = client.get("/api/me").json()
    year = to_jalali(date.today())[0] if me["calendar"] == "jalali" else date.today().year
    assert re.fullmatch(rf"SO-{year}-\d{{4}}", so["number"]) and so["status"] == "draft" and so["source"] == "quote"
    assert [i["line_item_id"] for i in so["items"]] == [accepted[0]["line_item_id"]]
    assert Decimal(so["items"][0]["unit_price"]) == Decimal(accepted[0]["unit_price"])
    assert Decimal(so["subtotal"]) == Decimal(accepted[0]["total"]) and so["currency"] == quote["currency"]
    assert so["customer_party_id"] == quote["buyer_party_id"] and so["customer_ref"] == "PO-778"
    assert so["payment_terms"] == quote["payment_terms"] and so["incoterm"] == quote["incoterm"]
    r = client.post("/api/sales-orders/from-quote", json={"quote_id": quote["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "order_exists"
    assert r.json()["error"]["details"]["sales_order_id"] == so["id"]
    assert client.get(f"/api/cases/{case['id']}/execution").json()["candidates"] == []
    assert events(client, "sales_order", so["id"], "create")


def test_a_quote_not_accepted_does_not_become_an_order(client):
    case, items, party, sheet, quote = sent_quote(client)
    r = client.post("/api/sales-orders/from-quote", json={"quote_id": quote["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_not_accepted"


def test_from_a_won_tender_with_the_organizer_and_performance_guarantee(client):
    case, items, party, sheet, t = tender_case(client)
    make_ready(client, t, case)
    proposal = [p for p in client.get(f"/api/tenders/{t['id']}").json()["proposals"] if p["status"] == "approved"][0]
    r = client.post("/api/sales-orders/from-proposal", json={"tender_proposal_id": proposal["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "tender_not_won"
    client.post(f"/api/tenders/{t['id']}/submit", json={})
    assert client.post(f"/api/tenders/{t['id']}/result", json={"result": "won"}).status_code == 200
    perf = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "performance"}).json()
    r = client.post("/api/sales-orders/from-proposal", json={"tender_proposal_id": proposal["id"]})
    assert r.status_code == 201, r.text
    so = r.json()
    assert so["source"] == "tender_proposal" and so["customer_party_id"] == t["organizer_party_id"]
    assert so["performance_guarantee_id"] == perf["id"] and so["customer_ref"] == t["tender_no"]
    assert len(so["items"]) == len(proposal["lines"]) and Decimal(so["total"]) == Decimal(proposal["total"])
    r = client.post("/api/sales-orders/from-proposal", json={"tender_proposal_id": proposal["id"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "order_exists"


def test_manual_order_from_the_sold_items(client):
    case, items, party, quote = accepted_quote(client, partial=False)
    r = client.post(f"/api/cases/{case['id']}/sales-orders", json={})
    assert r.status_code == 201, r.text
    so = r.json()
    assert so["source"] == "manual" and len(so["items"]) == 2 and so["currency"] == quote["currency"]
    assert {Decimal(i["unit_price"]) for i in so["items"]} == {Decimal(i["unit_price"]) for i in quote["items"]}
    case2 = client.post("/api/cases", json={"title": "No sold items"}).json()
    r = client.post(f"/api/cases/{case2['id']}/sales-orders", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_sold_items"


# ---- confirmation and amendments --------------------------------------------------------------------------------------

def test_confirm_needs_the_signed_document_or_a_reason(client):
    case, items, party, quote = accepted_quote(client)
    so = so_from_quote(client, quote)
    r = client.post(f"/api/sales-orders/{so['id']}/confirm", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "signed_document_required"
    r = client.post(f"/api/sales-orders/{so['id']}/confirm", json={"no_document_reason": "بدون سند امضاشده — تأیید تلفنی"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["confirmed_at"]
    ev = events(client, "sales_order", so["id"], "confirm")[0]["data"]
    assert ev["without_signed_document"] is True and "تأیید تلفنی" in ev["no_document_reason"]
    r = client.post(f"/api/sales-orders/{so['id']}/confirm", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "sales_order_not_draft"
    # with the signed contract
    case, items, party, quote, so2 = confirmed_order(client)
    assert so2["signed_document_id"] and so2["no_document_reason"] is None


def test_amendments_keep_their_history_and_no_silent_edit(client, db):
    case, items, party, quote, so = confirmed_order(client)
    r = client.patch(f"/api/sales-orders/{so['id']}", json={"delivery_due_on": day(90)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "amend_required"
    item = so["items"][0]
    r = client.patch(f"/api/sales-order-items/{item['id']}", json={"quantity": "3"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "amend_required"
    r = client.post(f"/api/sales-orders/{so['id']}/amend", json={"reason": "", "changes": {"delivery_due_on": day(90)}})
    assert r.status_code == 422
    doc = a_document(client, "amendment.pdf")
    r = client.post(f"/api/sales-orders/{so['id']}/amend", json={
        "reason": "الحاقیهٔ ۱ قرارداد", "document_id": doc, "changes": {"delivery_due_on": day(90)},
        "items": [{"sales_order_item_id": item["id"], "quantity": "5", "unit_price": "100"}]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["delivery_due_on"] == day(90)
    row = next(i for i in out["items"] if i["id"] == item["id"])
    assert Decimal(row["quantity"]) == 5 and Decimal(row["total"]) == Decimal("500")
    fields = sorted((c["field"], c["new_value"]) for c in out["changes"])
    assert fields == [("delivery_due_on", day(90)), ("quantity", "5"), ("unit_price", "100")]
    assert all(c["reason"] == "الحاقیهٔ ۱ قرارداد" and c["document_id"] == doc for c in out["changes"])
    assert Decimal(out["subtotal"]) == sum(Decimal(i["total"]) for i in out["items"])
    r = client.post(f"/api/sales-orders/{so['id']}/amend", json={"reason": "x", "changes": {"delivery_due_on": day(90)}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "nothing_to_amend"
    # free fields stay editable (customer ref, notes) and are recorded
    r = client.patch(f"/api/sales-orders/{so['id']}", json={"customer_ref": "C-1", "notes": "n"})
    assert r.status_code == 200 and r.json()["customer_ref"] == "C-1"
    assert db.execute(text("SELECT count(*) FROM core.audit WHERE table_name = 'ops.sales_order_change'")).scalar() >= 3


def test_cancel_and_delete_rules(client):
    case, items, party, quote = accepted_quote(client)
    so = so_from_quote(client, quote)
    assert client.delete(f"/api/sales-orders/{so['id']}").status_code == 204
    so = so_from_quote(client, quote)                     # the quote is free again
    client.post(f"/api/sales-orders/{so['id']}/confirm", json={"no_document_reason": "بدون سند امضاشده"})
    r = client.delete(f"/api/sales-orders/{so['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "sales_order_not_draft"
    r = client.post(f"/api/sales-orders/{so['id']}/cancel", json={"reason": "مشتری انصراف داد"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    so3 = so_from_quote(client, quote)                    # a cancelled order frees the quote
    assert so3["number"] != so["number"]


# ---- the acknowledgement output ------------------------------------------------------------------------------------------

def test_acknowledgement_fa_with_jalali_and_persian_digits_whatever_the_user_and_en(client):
    case, items, party, quote = accepted_quote(client)
    so = so_from_quote(client, quote, delivery_due_on=day(30), customer_ref="REF-9")
    client.patch("/api/me", json={"calendar": "gregorian", "digits": "latin"})
    page = client.get(f"/api/sales-orders/{so['id']}/print", params={"language": "fa"}).text
    y = str(to_jalali(date.today() + timedelta(days=30))[0]).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert "تأیید سفارش فروش" in page and y in page and "پیش‌نویس" in page and day(30) not in page
    assert "مبلغ به حروف" in page and so["number"] in page
    client.patch("/api/me", json={"calendar": "jalali", "digits": "fa"})
    try:
        page = client.get(f"/api/sales-orders/{so['id']}/print", params={"language": "en"}).text
    finally:
        client.patch("/api/me", json={"calendar": "gregorian", "digits": "latin"})
    assert "Order acknowledgement" in page and day(30) in page and "DRAFT" in page
    assert not re.search("[۰-۹]", re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", page, flags=re.S)))
    client.post(f"/api/sales-orders/{so['id']}/confirm", json={"no_document_reason": "بدون سند امضاشده"})
    page = client.get(f"/api/sales-orders/{so['id']}/print", params={"language": "en"}).text
    assert "class='watermark'" not in page
    r = client.post(f"/api/sales-orders/{so['id']}/outputs", json={"format": "docx", "language": "fa"})
    assert r.status_code == 201 and r.json()["filename"] == f"{so['number']}.docx"
    from docx import Document

    data = client.get(f"/api/documents/{r.json()['document_id']}/download").content
    text_all = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    assert "تأیید سفارش فروش" in text_all and "REF-9" in text_all
    assert client.get(f"/api/sales-orders/{so['id']}").json()["outputs"]


# ---- milestones ------------------------------------------------------------------------------------------------------------

def test_percent_resolves_and_partial_payments_derive_the_status(client):
    case, items, party, quote, so = confirmed_order(client)
    total = Decimal(so["total"])
    r = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "percent": "30",
                                                     "due_on": day(5)})
    assert r.status_code == 201, r.text
    ms = r.json()
    expected = (total * Decimal("0.3")).quantize(Decimal("0.0001"))
    assert ms["direction"] == "in" and ms["party_id"] == so["customer_party_id"] and ms["status"] == "expected"
    assert Decimal(ms["expected_amount"]) == expected and ms["expected_currency"] == so["currency"]
    r = client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": "1", "amount_currency": "XXX",
                                                                           "paid_on": day(0)})
    assert r.status_code == 422
    r = client.post(f"/api/payment-milestones/{ms['id']}/payments", json={
        "amount": str(expected / 2), "paid_on": day(0), "reference": "TRX-1", "method": "حواله"})
    assert r.status_code == 201 and r.json()["status"] == "partly"
    r = client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": str(expected / 2), "paid_on": day(1),
                                                                           "reference": "TRX-2"})
    out = r.json()
    assert out["status"] == "done" and Decimal(out["actual_amount"]) == expected and out["actual_on"] == day(1)
    assert out["reference"] == "TRX-2" and len(out["records"]) == 2
    r = client.post(f"/api/payment-records/{out['records'][1]['id']}/reverse", json={"reason": "ثبت اشتباه"})
    assert r.status_code == 200 and r.json()["status"] == "partly"
    assert client.delete(f"/api/payment-milestones/{ms['id']}").status_code == 409
    assert client.post(f"/api/payment-milestones/{ms['id']}/cancel", json={"reason": "x"}).status_code == 409
    # both a percent and an amount: refused; an amount without order takes the order currency
    r = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "balance", "percent": "10",
                                                     "amount": "5"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "amount_or_percent_only"
    r = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "on_delivery", "amount": "50"})
    assert r.status_code == 201 and r.json()["amount_currency"] == so["currency"]
    assert client.get("/api/payment-milestones/quick-add").json()["prepayment"]["label_fa"] == "پیش‌پرداخت ٪"


def test_cash_position_on_a_fixed_dataset(client):
    case, items, party, quote, so = confirmed_order(client)
    cur = so["currency"]
    m_in = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment",
                                                        "amount": "1000", "amount_currency": cur}).json()
    supplier = client.post("/api/parties", json={"name_en": "Paid supplier", "roles": ["supplier"],
                                                 "confirm_duplicate": True}).json()["party"]
    m_out = client.post("/api/payment-milestones", json={"case_id": case["id"], "direction": "out", "party_id": supplier["id"],
                                                         "kind": "prepayment", "amount": "1500", "amount_currency": cur}).json()
    client.post(f"/api/payment-milestones/{m_in['id']}/payments", json={"amount": "1000", "paid_on": day(0)})
    client.post(f"/api/payment-milestones/{m_out['id']}/payments", json={"amount": "600", "paid_on": day(0)})
    cash = client.get(f"/api/cases/{case['id']}/cash-position").json()
    assert cash["actual"] == {cur: {"received": "1000.0000", "paid": "600.0000", "net_tied_up": "-400.0000"}}
    assert cash["outstanding"] == {cur: {"in": "0.0000", "out": "900.0000"}}
    assert cash["plan"] and cash["plan"]["currency"]
    assert client.get(f"/api/cases/{case['id']}/execution").json()["cash"] == cash


def test_the_ordering_gate_needs_a_reason_while_the_prepayment_is_not_done(client, db):
    case, items, party, quote, so = confirmed_order(client)
    import uuid

    assert ms_service.check_ordering_gate(db, uuid.UUID(so["id"]), False, None) is None
    m_in = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "percent": "20"}).json()
    db.expire_all()
    with pytest.raises(Conflict) as exc:
        ms_service.check_ordering_gate(db, uuid.UUID(so["id"]), True, "  ")
    assert exc.value.code == "customer_prepayment_missing" and "explicit approval line" in exc.value.message
    assert ms_service.check_ordering_gate(db, uuid.UUID(so["id"]), True, "مشتری معتبر است") == "مشتری معتبر است"
    client.post(f"/api/payment-milestones/{m_in['id']}/payments", json={"amount": "1", "paid_on": day(0)})
    db.expire_all()
    with pytest.raises(Conflict) as exc:                                   # v0.8.0: partly still blocks
        ms_service.check_ordering_gate(db, uuid.UUID(so["id"]), False, None)
    assert exc.value.details["prepayments"][0]["status"] == "partly"


def test_unknown_fields_are_refused(client):
    case, items, party, quote = accepted_quote(client)
    for path, body in (("/api/sales-orders/from-quote", {"quote_id": quote["id"], "bogus": 1}),
                       ("/api/payment-milestones", {"kind": "prepayment", "amount": "1", "bogus": 1})):
        r = client.post(path, json=body)
        assert r.status_code == 422, path
