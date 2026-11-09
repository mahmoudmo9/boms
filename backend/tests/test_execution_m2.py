"""v0.7.0 Phase 8, milestone 2: purchase orders (grouping by supplier, numbering and revisions, approval with the
cost-sheet check, outputs, sending with the ordering gate, confirmation, ready tracking) and the process checklists
(template copy per deal type, due dates from offsets, the document rule, reminders, progress)."""
import io
import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.modules.sourcing.jalali import to_jalali
from tests.conftest import unique_bytes, upload
from tests.test_execution_m1 import a_document, accepted_quote, confirmed_order, day, so_from_quote
from tests.test_quotes import CHROMIUM
from tests.test_sourcing_inquiries import events
from tests.test_tenders_m3 import _pages


def create_pos(client, so):
    r = client.post(f"/api/sales-orders/{so['id']}/purchase-orders")
    assert r.status_code == 201, r.text
    return r.json()


def by_currency(pos):
    return {p["currency"]: p for p in pos}


def sent_po(client, po, **body):
    assert client.post(f"/api/purchase-orders/{po['id']}/approve").status_code == 200
    r = client.post(f"/api/purchase-orders/{po['id']}/mark-sent", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def followups_of(db, po_id, purpose=None, status="open"):
    q = ("SELECT f.action, f.due_on, f.status, l.purpose FROM ops.execution_followup l JOIN core.followup f ON f.id = l.followup_id "
         "WHERE l.ref_id = :r" + (" AND l.purpose = :p" if purpose else "") + (" AND f.status = :s" if status else ""))
    return db.execute(text(q), {"r": po_id, "p": purpose, "s": status}).all()


# ---- creation ---------------------------------------------------------------------------------------------------------

def test_create_pos_groups_by_supplier_and_lists_items_without_offer(client, db):
    case, items, party, quote, so = confirmed_order(client)
    out = create_pos(client, so)
    assert out["unresolved"] == [] and len(out["created"]) == 2
    pos = by_currency(out["created"])
    usd, eur = pos["USD"], pos["EUR"]
    assert usd["supplier_party_id"] != eur["supplier_party_id"] and usd["sales_order_id"] == so["id"]
    assert [Decimal(i["unit_price"]) for i in usd["items"]] == [Decimal("12.5")]
    assert [Decimal(i["unit_price"]) for i in eur["items"]] == [Decimal("300")]
    assert Decimal(usd["total"]) == Decimal("125") and usd["status"] == "draft" and usd["offer_id"]
    assert usd["terms_text"] and usd["language"] in ("fa", "en")
    # items already on a PO are not ordered twice
    assert create_pos(client, so) == {"created": [], "unresolved": []}
    # an order whose item has no selected offer: listed for the owner to resolve
    case2, items2, party2, quote2, so2 = confirmed_order(client)
    db.execute(text("UPDATE ops.line_item SET selected_offer_item_id = NULL WHERE id = :i"), {"i": so2["items"][0]["line_item_id"]})
    db.commit()
    out2 = create_pos(client, so2)
    assert len(out2["created"]) == 1 and [u["line_item_id"] for u in out2["unresolved"]] == [so2["items"][0]["line_item_id"]]
    # a draft order is not ordered yet
    c3, i3, p3, q3 = accepted_quote(client)
    so3 = so_from_quote(client, q3)
    r = client.post(f"/api/sales-orders/{so3['id']}/purchase-orders")
    assert r.status_code == 409 and r.json()["error"]["code"] == "sales_order_not_confirmed"


def test_numbering_and_revisions(client):
    case, items, party, quote, so = confirmed_order(client)
    pos = sorted(create_pos(client, so)["created"], key=lambda p: p["number"])
    a, b = pos
    year = a["number"].split("-")[1]
    assert re.fullmatch(rf"PO-{year}-\d{{4}}", a["number"]) and int(b["number"][-4:]) == int(a["number"][-4:]) + 1
    r = client.post(f"/api/purchase-orders/{a['id']}/revise")
    assert r.status_code == 409                                     # a draft is edited, not revised
    client.post(f"/api/purchase-orders/{a['id']}/approve")
    v2 = client.post(f"/api/purchase-orders/{a['id']}/revise").json()
    assert v2["number"] == f"{a['number']}-v2" and v2["version"] == 2 and v2["status"] == "draft"
    assert v2["supersedes_id"] == a["id"] and client.get(f"/api/purchase-orders/{a['id']}").json()["status"] == "superseded"
    client.post(f"/api/purchase-orders/{v2['id']}/approve")
    v3 = client.post(f"/api/purchase-orders/{v2['id']}/revise").json()
    assert v3["number"] == f"{a['number']}-v3"
    assert client.delete(f"/api/purchase-orders/{v3['id']}").status_code == 204
    assert client.delete(f"/api/purchase-orders/{b['id']}").status_code == 204


def test_approve_locks_and_checks_the_cost_sheet_price_with_tolerance_and_override(client):
    case, items, party, quote, so = confirmed_order(client)
    usd = by_currency(create_pos(client, so)["created"])["USD"]
    item = usd["items"][0]
    client.patch(f"/api/purchase-order-items/{item['id']}", json={"unit_price": "13"})
    r = client.post(f"/api/purchase-orders/{usd['id']}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "po_above_cost_sheet"
    assert r.json()["error"]["details"]["items"][0]["cost_sheet_price"].startswith("12.5")
    client.patch("/api/settings", json={"execution.po_price_tolerance_percent": 10})
    try:
        r = client.post(f"/api/purchase-orders/{usd['id']}/approve")       # 13 <= 12.5 + 10 %
        assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["price_override_reason"] is None
    finally:
        client.patch("/api/settings", json={"execution.po_price_tolerance_percent": 0})
    r = client.patch(f"/api/purchase-order-items/{item['id']}", json={"unit_price": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "purchase_order_not_draft"   # numbers locked
    v2 = client.post(f"/api/purchase-orders/{usd['id']}/revise").json()
    client.patch(f"/api/purchase-order-items/{v2['items'][0]['id']}", json={"unit_price": "20"})
    r = client.post(f"/api/purchase-orders/{v2['id']}/approve", json={"confirm_above_cost": True, "reason": ""})
    assert r.status_code == 409
    r = client.post(f"/api/purchase-orders/{v2['id']}/approve", json={"confirm_above_cost": True, "reason": "افزایش قیمت مواد"})
    assert r.status_code == 200 and r.json()["price_override_reason"] == "افزایش قیمت مواد"
    ev = events(client, "purchase_order", v2["id"], "approve")[0]["data"]
    assert ev["above_cost_sheet"] and ev["override_reason"] == "افزایش قیمت مواد"


def test_outputs_pdf_one_page_word_reopens_draft_mark_and_fa_jalali(client, db):
    from docx import Document

    client.patch("/api/settings", json={"company.name_fa": "بازرگانی نمونه", "company.name_en": "Sample Trading"})
    case, items, party, quote, so = confirmed_order(client)
    pos = by_currency(create_pos(client, so)["created"])
    eur = pos["EUR"]
    client.patch(f"/api/purchase-orders/{eur['id']}", json={"language": "fa", "ready_due_on": day(20)})
    client.patch("/api/me", json={"calendar": "gregorian", "digits": "latin"})
    page = client.get(f"/api/purchase-orders/{eur['id']}/print").text
    y = str(to_jalali(date.today() + timedelta(days=20))[0]).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert "سفارش خرید" in page and "پیش‌نویس" in page and y in page and day(20) not in page
    assert "مبلغ به حروف" in page and eur["number"] in page
    usd = pos["USD"]
    client.patch(f"/api/purchase-orders/{usd['id']}", json={"language": "en"})
    r = client.post(f"/api/purchase-orders/{usd['id']}/outputs", json={"format": "docx"})
    assert r.status_code == 201 and re.fullmatch(rf"{usd['number']}_PurchaseOrder_\w+_\d{{8}}_DRAFT\.docx", r.json()["filename"])
    doc = Document(io.BytesIO(client.get(f"/api/documents/{r.json()['document_id']}/download").content))
    body = "\n".join(p.text for p in doc.paragraphs)
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert "Purchase order" in body and "DRAFT" in body and any("Valve" in c for c in cells)
    client.post(f"/api/purchase-orders/{usd['id']}/approve")
    client.patch("/api/settings", json={"pdf.browser_path": CHROMIUM})
    try:
        r = client.post(f"/api/purchase-orders/{usd['id']}/outputs", json={"format": "pdf"})
    finally:
        client.patch("/api/settings", json={"pdf.browser_path": None})
    assert r.status_code == 201, r.text
    data = client.get(f"/api/documents/{r.json()['document_id']}/download").content
    assert data[:5] == b"%PDF-" and _pages(data) == 1 and r.json()["draft"] is False
    assert len(client.get(f"/api/purchase-orders/{usd['id']}").json()["outputs"]) == 2


# ---- sending, gate, confirmation, readiness -------------------------------------------------------------------------------

def test_mark_sent_interaction_followup_and_the_prepayment_gate(client, db):
    case, items, party, quote, so = confirmed_order(client)
    usd = by_currency(create_pos(client, so)["created"])["USD"]
    ms = client.post("/api/payment-milestones", json={"sales_order_id": so["id"], "kind": "prepayment", "percent": "30"}).json()
    client.post(f"/api/purchase-orders/{usd['id']}/approve")
    r = client.post(f"/api/purchase-orders/{usd['id']}/mark-sent", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "customer_prepayment_missing"
    r = client.post(f"/api/purchase-orders/{usd['id']}/mark-sent", json={"confirm_without_prepayment": True, "reason": "مشتری قدیمی"})
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["status"] == "sent" and po["interaction_id"] and po["prepayment_override_reason"] == "مشتری قدیمی"
    ev = events(client, "purchase_order", po["id"], "sent")[0]["data"]
    assert ev["without_prepayment"] is True
    f = followups_of(db, po["id"], "po_confirm")
    assert len(f) == 1 and f[0].action.startswith("پیگیری تأیید سفارش") and f[0].due_on == date.today() + timedelta(days=3)
    inter = db.execute(text("SELECT direction, party_id FROM core.interaction WHERE id = :i"), {"i": po["interaction_id"]}).one()
    assert inter.direction == "out" and str(inter.party_id) == po["supplier_party_id"]
    assert client.get(f"/api/sales-orders/{so['id']}").json()["status"] == "in_progress"
    # prepayment fully received (v0.8.0: partly is not enough): the second PO goes without a reason
    client.post(f"/api/payment-milestones/{ms['id']}/payments", json={"amount": ms["expected_amount"], "paid_on": day(0)})
    eur = by_currency(client.get(f"/api/cases/{case['id']}/execution").json()["purchase_orders"])["EUR"]
    sent = sent_po(client, eur)
    assert sent["prepayment_override_reason"] is None


def test_confirmation_closes_the_followup_creates_the_ready_one_and_keeps_ready_date_history(client, db):
    case, items, party, quote, so = confirmed_order(client)
    usd = by_currency(create_pos(client, so)["created"])["USD"]
    po = sent_po(client, usd)
    doc = a_document(client, "confirmation.pdf")
    r = client.post(f"/api/purchase-orders/{po['id']}/confirm", json={"supplier_ref": "SO-SUP-55", "confirmed_ready_on": day(30),
                                                                     "confirmation_document_id": doc})
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["status"] == "confirmed" and po["supplier_ref"] == "SO-SUP-55" and po["ready_due_on"] == day(30)
    assert followups_of(db, po["id"], "po_confirm") == [] and followups_of(db, po["id"], "po_confirm", "done")
    ready = followups_of(db, po["id"], "po_ready")
    assert len(ready) == 1 and ready[0].due_on == date.today() + timedelta(days=28) and "آماده شدن" in ready[0].action
    assert [(c["field"], c["new_value"]) for c in po["changes"]] == [("ready_due_on", day(30))]
    r = client.post(f"/api/purchase-orders/{po['id']}/ready-date", json={"ready_due_on": day(40), "reason": ""})
    assert r.status_code == 422
    r = client.post(f"/api/purchase-orders/{po['id']}/ready-date", json={"ready_due_on": day(40), "reason": "تأخیر در تولید"})
    assert r.status_code == 200 and len(r.json()["changes"]) == 2 and r.json()["changes"][1]["reason"] == "تأخیر در تولید"
    assert followups_of(db, po["id"], "po_ready")[0].due_on == date.today() + timedelta(days=38)
    r = client.post(f"/api/purchase-orders/{po['id']}/status", json={"status": "ready"})
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.json()["ready_on"] == day(0)
    assert followups_of(db, po["id"], "po_ready") == []
    r = client.post(f"/api/purchase-orders/{po['id']}/status", json={"status": "in_production"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    r = client.delete(f"/api/purchase-orders/{po['id']}")
    assert r.status_code == 409                                       # a sent PO is cancelled, never deleted


# ---- process checklists ------------------------------------------------------------------------------------------------------

def step(process, code):
    return next(s for s in process["steps"] if s["code"] == code)


def test_confirming_the_order_copies_the_template_of_the_deal_type_with_due_dates(client, db):
    case, items, party, quote, so = confirmed_order(client)
    procs = client.get(f"/api/cases/{case['id']}/execution").json()["processes"]
    assert len(procs) == 1 and procs[0]["deal_type"] == "import" and procs[0]["sales_order_id"] == so["id"]
    p = procs[0]
    assert len(p["steps"]) == 13 and p["progress"] == {"done": 0, "total": 13, "next": p["progress"]["next"]}
    reg = step(p, "order_registration")
    assert reg["due_on"] == day(7) and reg["reference_label"].startswith("شماره ثبت سفارش") and reg["requires_document"]
    assert sorted(r["due_on"] for r in reg["reminders"]) == [day(4), day(6)]
    # by hand: an export checklist; a second one of the same type is refused
    r = client.post(f"/api/cases/{case['id']}/processes", json={"deal_type": "export"})
    assert r.status_code == 201 and len(r.json()["steps"]) == 8
    r = client.post(f"/api/cases/{case['id']}/processes", json={"deal_type": "import"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "process_exists"
    r = client.post(f"/api/cases/{case['id']}/processes", json={"deal_type": "domestic"})
    assert r.status_code == 201 and [s["code"] for s in r.json()["steps"]][:2] == ["po_sent", "supplier_prepayment"]


def test_document_rule_reminders_and_progress(client, db):
    case, items, party, quote, so = confirmed_order(client)
    p = client.get(f"/api/cases/{case['id']}/execution").json()["processes"][0]
    reg = step(p, "order_registration")
    r = client.patch(f"/api/process-steps/{reg['id']}", json={"status": "done", "reference": "ثبت-۱۲۳۴۵"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "document_required"
    r = client.patch(f"/api/process-steps/{reg['id']}", json={"status": "in_progress", "reference": "12345678"})
    assert r.status_code == 200 and step(r.json(), "order_registration")["started_on"] == day(0)
    r = client.patch(f"/api/process-steps/{reg['id']}", json={"due_on": day(12)})
    assert sorted(x["due_on"] for x in step(r.json(), "order_registration")["reminders"]) == [day(9), day(11)]
    r = client.patch(f"/api/process-steps/{reg['id']}", json={"status": "done", "document_id": a_document(client, "reg.pdf")})
    s = step(r.json(), "order_registration")
    assert s["status"] == "done" and s["done_on"] == day(0) and s["reminders"] == []
    kotaj = step(r.json(), "declaration_kotaj")
    r = client.patch(f"/api/process-steps/{kotaj['id']}", json={"status": "done", "reference": "KTJ-998877",
                                                                "no_document_reason": "اظهارنامه نزد ترخیص‌کار"})
    assert r.status_code == 200
    proforma = step(r.json(), "supplier_proforma")
    r = client.patch(f"/api/process-steps/{proforma['id']}", json={"status": "not_applicable"})
    assert r.json()["progress"]["done"] == 3 and r.json()["progress"]["total"] == 13
    assert r.json()["progress"]["next"]["code"] == "currency_allocation"
    # the case closed: the remaining reminders are cancelled
    open_before = db.execute(text("SELECT count(*) FROM core.task WHERE case_id = :c AND source_kind = 'process_step' AND status = 'open'"), {"c": case["id"]}).scalar()
    assert open_before > 0
    client.patch(f"/api/cases/{case['id']}", json={"status": "cancelled"})
    db.expire_all()
    open_after = db.execute(text("SELECT count(*) FROM core.task WHERE case_id = :c AND source_kind = 'process_step' AND status = 'open'"), {"c": case["id"]}).scalar()
    assert open_after == 0


def test_templates_are_data_the_owner_edits(client):
    templates = client.get("/api/process-templates").json()
    assert {t["deal_type"] for t in templates if t["is_default"]} == {"import", "export", "domestic"}
    dom = next(t for t in templates if t["deal_type"] == "domestic" and t["is_default"])
    steps = [{k: s[k] for k in ("group", "code", "label_fa", "label_en", "reference_label", "requires_document",
                                "default_offset_days")} for s in dom["steps"]]
    steps[0]["label_fa"] = "ارسال سفارش به تأمین‌کننده"
    steps.append({"code": "quality_check", "label_fa": "کنترل کیفیت", "label_en": "Quality check", "default_offset_days": 17})
    r = client.patch(f"/api/process-templates/{dom['id']}", json={"steps": steps})
    assert r.status_code == 200 and len(r.json()["steps"]) == 7
    case = client.post("/api/cases", json={"title": "Domestic deal"}).json()
    r = client.post(f"/api/cases/{case['id']}/processes", json={"deal_type": "domestic", "base_date": day(0)})
    p = r.json()
    assert p["steps"][0]["label_fa"] == "ارسال سفارش به تأمین‌کننده" and step(p, "quality_check")["due_on"] == day(17)
    r = client.patch(f"/api/process-templates/{dom['id']}", json={"steps": steps + [dict(steps[0])]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "duplicate_step_code"
    assert client.delete(f"/api/process-templates/{dom['id']}").status_code == 409     # the default stays
    client.patch(f"/api/process-templates/{dom['id']}", json={"steps": steps[:-1]})


def test_domestic_po_events_tick_their_steps(client):
    case, items, party, quote, so = confirmed_order(client)
    p = client.post(f"/api/cases/{case['id']}/processes", json={"deal_type": "domestic"}).json()
    usd = by_currency(create_pos(client, so)["created"])["USD"]
    po = sent_po(client, usd)
    client.post(f"/api/purchase-orders/{po['id']}/confirm", json={})
    client.post(f"/api/purchase-orders/{po['id']}/status", json={"status": "ready"})
    p = client.get(f"/api/processes/{p['id']}").json()
    assert step(p, "po_sent")["status"] == "done" and step(p, "goods_ready")["status"] == "done"


def test_po_terms_templates_in_the_message_template_api(client):
    r = client.get("/api/message-templates", params={"kind": "po_terms"})
    assert r.status_code == 200 and "ready_due_on" in r.json()["placeholders"]
    assert {t["language"] for t in r.json()["items"]} == {"fa", "en"}
    r = client.post("/api/message-templates/preview", json={"kind": "po_terms", "language": "en",
                                                            "body_template": "Dear {supplier_name}, ready by {ready_due_on}"})
    assert r.status_code == 200 and "ACME Trading" in r.json()["body"]
    r = client.post("/api/message-templates", json={"kind": "po_terms", "language": "en", "channel": "letter", "name": "x",
                                                    "body_template": "{buyer_name}"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_placeholder"
    assert unique_bytes and upload
