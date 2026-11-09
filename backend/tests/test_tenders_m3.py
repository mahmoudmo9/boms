"""v0.6.0 Phase 7b, milestone 3: the financial proposal (summary and letterhead mode), submission with blockers, the
result, and the integrations (command center, product page, search, cascade delete, audit, migrations, backup)."""
import io
import os
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.connectors.setad.pipeline import number_words
from tests.conftest import unique_bytes, upload
from tests.test_listings_store import tag
from tests.test_quotes import ready_case
from tests.test_sourcing_inquiries import events
from tests.test_tenders import at, followups, tasks


def day(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def tender_case(client, **patch):
    """A case with a final, priced cost sheet (Phase 6), a buyer, and a tender part with a proposal deadline."""
    case, items, party, sheet = ready_case(client, country="IR")
    t = client.post(f"/api/cases/{case['id']}/tender").json()
    t = client.patch(f"/api/tenders/{t['id']}", json={"tender_no": f"T-{tag()}", "organizer_party_id": party["id"], **patch}).json()
    client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "proposal_deadline", "at": at(10)})
    return case, items, party, sheet, t


def new_proposal(client, t, **body):
    r = client.post(f"/api/tenders/{t['id']}/proposals", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---- financial proposal -----------------------------------------------------------------------------------------------

def test_summary_totals_vat_words_and_versions(client):
    case, items, party, sheet, t = tender_case(client)
    comp = client.get(f"/api/cost-sheets/{sheet['id']}").json()["computation"]
    p = new_proposal(client, t)
    assert p["version"] == 1 and p["status"] == "draft" and p["currency"] == "IRR" and len(p["lines"]) == 2
    subtotal = sum(Decimal(x["total"]) for x in p["lines"])
    vat = sum(Decimal(x["vat_amount"]) for x in p["lines"])
    assert Decimal(p["subtotal"]) == subtotal == sum(Decimal(r["total_price"]) for r in comp["items"])
    assert Decimal(p["vat_amount"]) == vat == sum(Decimal(r["vat"]) for r in comp["items"])
    assert Decimal(p["total"]) == subtotal + vat
    assert p["words"] == f"{number_words(int(Decimal(p['total'])))} ریال"
    # a manual unit price: line total and the totals follow (Decimal, rial without decimals)
    line = p["lines"][0]
    p2 = client.patch(f"/api/tender-proposal-lines/{line['id']}", json={"unit_price": "123456789"}).json()
    changed = next(x for x in p2["lines"] if x["id"] == line["id"])
    assert Decimal(changed["total"]) == (Decimal("123456789") * Decimal(changed["quantity"])).quantize(Decimal(1))
    assert Decimal(p2["total"]) == Decimal(p2["subtotal"]) + Decimal(p2["vat_amount"])
    # a new version supersedes the old one
    v2 = new_proposal(client, t)
    assert v2["version"] == 2 and v2["supersedes_id"] == p["id"]
    assert client.get(f"/api/tender-proposals/{p['id']}").json()["status"] == "superseded"


def test_approve_locks_and_checks_below_cost(client):
    case, items, party, sheet, t = tender_case(client)
    p = new_proposal(client, t)
    line = p["lines"][0]
    cheap = (Decimal(line["unit_cost"]) * Decimal("0.5")).quantize(Decimal(1))
    client.patch(f"/api/tender-proposal-lines/{line['id']}", json={"unit_price": str(cheap)})
    r = client.post(f"/api/tender-proposals/{p['id']}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "below_cost"
    r = client.post(f"/api/tender-proposals/{p['id']}/approve", json={"confirm_below_cost": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = client.post(f"/api/tender-proposals/{p['id']}/approve", json={"confirm_below_cost": True, "reason": "ورود به بازار"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["below_cost_reason"] == "ورود به بازار"
    r = client.patch(f"/api/tender-proposal-lines/{line['id']}", json={"unit_price": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "proposal_locked"
    assert [e["action"] for e in events(client, "tender", t["id"], "proposal_approve_below_cost")] == ["proposal_approve_below_cost"]


def _pages(data: bytes) -> int:
    import re

    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def test_outputs_pdf_one_page_word_reopens_and_draft_mark(client):
    from docx import Document

    from app.modules.quotes import output

    client.patch("/api/settings", json={"company.name_fa": "بازرگانی نمونه", "company.national_id": "10320000000",
                                        "company.economic_code": "411111111111"})
    case, items, party, sheet, t = tender_case(client)
    p = new_proposal(client, t)
    html = client.get(f"/api/tender-proposals/{p['id']}/print").text
    assert "خلاصهٔ پیشنهاد مالی" in html and t["tender_no"] in html and "10320000000" in html
    assert "مبلغ به حروف" in html and "این برگه برای تکمیل فرم پیشنهاد قیمت کارفرما تهیه شده است" in html
    assert "پیش‌نویس" in html
    r = client.post(f"/api/tender-proposals/{p['id']}/outputs", json={"format": "docx"})
    assert r.status_code == 201, r.text
    assert r.json()["draft"] is True and r.json()["filename"].endswith("_DRAFT.docx")
    doc = Document(io.BytesIO(client.get(f"/api/documents/{r.json()['document_id']}/download").content))
    body = "\n".join(x.text for x in doc.paragraphs)
    cells = [c.text for tb in doc.tables for row in tb.rows for c in row.cells]
    assert "خلاصهٔ پیشنهاد مالی" in body and "پیش‌نویس" in body and any("Valve" in c for c in cells)
    assert client.get(f"/api/tender-proposals/{p['id']}").json()["outputs"][0]["document_id"] == r.json()["document_id"]
    browser = os.environ.get("BOMS_TEST_PDF_BROWSER") or next(
        (x for x in output._candidates() + ["/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/"
                                             "chrome-headless-shell"] if os.path.isfile(x)), None)
    if browser is None:
        pytest.skip("no Chromium for PDF on this machine")
    client.patch("/api/settings", json={"pdf.browser_path": browser})
    try:
        client.post(f"/api/tender-proposals/{p['id']}/approve")
        r = client.post(f"/api/tender-proposals/{p['id']}/outputs", json={"format": "pdf"})
        assert r.status_code == 201, r.text
        assert r.json()["draft"] is False and "DRAFT" not in r.json()["filename"]
        data = client.get(f"/api/documents/{r.json()['document_id']}/download").content
        assert data[:5] == b"%PDF-" and _pages(data) == 1
    finally:
        client.patch("/api/settings", json={"pdf.browser_path": None})


def test_letterhead_mode_uses_the_tender_terms_template(client):
    case, items, party, sheet, t = tender_case(client, financial_mode="letterhead")
    r = client.post("/api/quotes", json={"case_id": case["id"]})
    assert r.status_code == 201, r.text
    terms = r.json()["terms_text"]
    assert "طبق اسناد مناقصه" in terms and t["tender_no"] in terms.replace("⁨", "")
    assert "مدیریت محترم امور تدارکات" in terms


# ---- submission and result ----------------------------------------------------------------------------------------------

def make_ready(client, t, case):
    """Everything the checklist needs: participation, envelopes ready, bid bond issued, proposal approved."""
    client.patch(f"/api/tenders/{t['id']}", json={"participation": "yes"})
    g = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "bid", "form": "bank",
                                             "amount": "100000000"}).json()
    client.post(f"/api/guarantees/{g['id']}/status", json={"status": "issued", "valid_until": day(200)})
    detail = client.get(f"/api/tenders/{t['id']}").json()
    for item in detail["envelope_items"]:
        if item["status"] not in ("ready", "submitted"):
            assert client.patch(f"/api/envelope-items/{item['id']}", json={"status": "ready"}).status_code == 200
    p = new_proposal(client, t)
    assert client.post(f"/api/tender-proposals/{p['id']}/approve").status_code == 200
    return g


def test_blockers_are_reported_together_and_can_be_overridden_with_a_reason(client, db):
    case, items, party, sheet, t = tender_case(client)
    codes = {b["code"] for b in client.get(f"/api/tenders/{t['id']}/blockers").json()["blockers"]}
    assert codes == {"participation", "envelopes_incomplete", "bid_bond_not_issued", "proposal_not_approved"}
    r = client.post(f"/api/tenders/{t['id']}/submit", json={})
    assert r.status_code == 422 and r.json()["error"]["code"] == "blockers_remain"
    assert len(r.json()["error"]["details"]["blockers"]) == 4
    client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "opening", "at": at(11)})
    r = client.post(f"/api/tenders/{t['id']}/submit", json={"channel": "setad", "override_reason": "ارسال با مدارک ناقص به‌ناچار"})
    assert r.status_code == 200, r.text
    t2 = r.json()
    assert t2["stage"] == "submitted" and t2["submit_override_reason"] == "ارسال با مدارک ناقص به‌ناچار"
    assert all(i["status"] == "submitted" for i in t2["envelope_items"])
    opening = [x for x in t2["other_reminders"] if x["purpose"] == "opening"]
    assert len(opening) == 1 and opening[0]["due_on"] == day(11)
    ev = events(client, "tender", t["id"], "submitted")[0]["data"]
    assert ev["override_reason"] and len(ev["blockers"]) == 4


def test_a_ready_tender_submits_without_override(client):
    case, items, party, sheet, t = tender_case(client)
    make_ready(client, t, case)
    assert client.get(f"/api/tenders/{t['id']}/blockers").json()["blockers"] == []
    assert client.post(f"/api/tenders/{t['id']}/submit", json={}).status_code == 200


def test_won_sells_items_and_wins_the_case_revising_clears_sold(client, db):
    case, items, party, sheet, t = tender_case(client)
    bid = make_ready(client, t, case)
    client.post(f"/api/tenders/{t['id']}/submit", json={})
    r = client.post(f"/api/tenders/{t['id']}/result", json={"result": "won", "our_rank": 1})
    assert r.status_code == 200, r.text
    statuses = {i["status"] for i in client.get(f"/api/cases/{case['id']}").json()["items"]}
    assert statuses == {"sold"} and client.get(f"/api/cases/{case['id']}").json()["status"] == "won"
    contract = [x for x in r.json()["other_reminders"] if x["purpose"] == "contract"]
    assert len(contract) == 1 and contract[0]["due_on"] == day(3)
    # the bid bond release waits for the performance guarantee
    assert not [g for g in r.json()["guarantees"] if g["id"] == bid["id"] and any(x["purpose"] == "guarantee_release" for x in g["reminders"])]
    perf = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "performance"}).json()
    for status in ("issued", "submitted"):
        client.post(f"/api/guarantees/{perf['id']}/status", json={"status": status, "valid_until": day(400)})
    bid_now = client.get(f"/api/guarantees/{bid['id']}").json()
    release = [x for x in bid_now["reminders"] if x["purpose"] == "guarantee_release"]
    assert len(release) == 1 and release[0]["due_on"] == day(7) and "آزادسازی" in release[0]["action"]
    # revised to lost: reason required, sold cleared, the case lost, the contract follow-up cancelled
    r = client.post(f"/api/tenders/{t['id']}/result", json={"result": "lost"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = client.post(f"/api/tenders/{t['id']}/result", json={"result": "lost", "result_reason": "price",
                                                           "winner_name": "شرکت رقیب", "winner_price": "900000000"})
    assert r.status_code == 200 and r.json()["winner_price_currency"] == "IRR"
    statuses = {i["status"] for i in client.get(f"/api/cases/{case['id']}").json()["items"]}
    assert "sold" not in statuses and client.get(f"/api/cases/{case['id']}").json()["status"] == "lost"
    assert [x for x in r.json()["other_reminders"] if x["purpose"] == "contract"] == []
    assert [e["action"] for e in events(client, "tender", t["id"]) if e["action"].startswith("result")] == ["result_revised", "result"]


def test_lost_or_cancelled_creates_the_bid_bond_release_followup(client, db):
    case, items, party, sheet, t = tender_case(client)
    bid = make_ready(client, t, case)
    assert len(tasks(db, party["id"])) >= 2                                           # date + guarantee reminders (tasks)
    r = client.post(f"/api/tenders/{t['id']}/result", json={"result": "cancelled", "case_status": "cancelled"})
    assert r.status_code == 200 and r.json()["stage"] == "result"
    assert client.get(f"/api/cases/{case['id']}").json()["status"] == "cancelled"
    actions = [f.action for f in followups(db, party["id"])]
    assert any("پیگیری آزادسازی تضمین" in a for a in actions)
    assert not any(a.startswith("یادآوری:") for a in actions)                        # never follow-ups
    assert not any(r.action.startswith("یادآوری:") for r in tasks(db, party["id"]))  # date reminder tasks cancelled
    g = client.get(f"/api/guarantees/{bid['id']}").json()
    assert {x["purpose"] for x in g["reminders"]} == {"guarantee_expiry", "guarantee_release"}
    # an addendum cancellation does the same through the result
    case2, items2, party2, sheet2, t2 = tender_case(client)
    r = client.post(f"/api/tenders/{t2['id']}/addenda", json={"received_on": day(0), "kind": "cancellation",
                                                              "summary": "لغو مناقصه توسط کارفرما", "confirm_cancellation": True})
    assert r.status_code == 201 and r.json()["result"] == "cancelled" and r.json()["result_reason"] == "cancelled_by_organizer"


def test_product_page_lists_approved_tender_proposals(client):
    case, items, party, sheet, t = tender_case(client)
    product = client.post("/api/products", json={"name_fa": f"شیر {tag()}", "confirm_duplicate": True}).json()["product"]
    client.patch(f"/api/line-items/{items[0]['id']}", json={"product_id": product["id"]})
    p = new_proposal(client, t)
    client.post(f"/api/tender-proposals/{p['id']}/approve")
    rows = client.get(f"/api/quotes/by-product/{product['id']}").json()["quotes"]
    assert any(r.get("kind") == "tender" and t["tender_no"] in r["number"] for r in rows)


# ---- integrations --------------------------------------------------------------------------------------------------------

def test_command_center_tenders_section(client, db):
    case, items, party, sheet, t = tender_case(client)
    client.post(f"/api/tenders/{t['id']}/dates", json={"kind": "briefing", "at": at(1)})
    client.patch(f"/api/tenders/{t['id']}", json={})
    g = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "bid"}).json()
    client.post(f"/api/guarantees/{g['id']}/status", json={"status": "issued", "valid_until": day(20)})
    cc = client.get("/api/command-center").json()
    assert "setad" in cc and "tenders" in cc
    s = cc["tenders"]
    assert t["id"] in [x["tender_id"] for x in s["dates_soon"]]
    assert g["id"] in [x["guarantee_id"] for x in s["guarantees_expiring"]]
    # a submitted tender past its opening date waits for a result
    case2, items2, party2, sheet2, t2 = tender_case(client)
    client.post(f"/api/tenders/{t2['id']}/dates", json={"kind": "opening", "at": at(-1)})
    client.post(f"/api/tenders/{t2['id']}/submit", json={"override_reason": "test"})
    assert t2["id"] in [x["tender_id"] for x in client.get("/api/command-center").json()["tenders"]["waiting_result"]]
    # envelopes incomplete with the deadline close
    case3, items3, party3, sheet3, t3 = tender_case(client)
    d = next(x for x in client.get(f"/api/tenders/{t3['id']}").json()["dates"] if x["kind"] == "proposal_deadline")
    client.patch(f"/api/tender-dates/{d['id']}", json={"at": at(2), "reason": "test"})
    assert t3["id"] in [x["tender_id"] for x in client.get("/api/command-center").json()["tenders"]["envelopes_incomplete"]]


def test_search_providers(client):
    case, items, party, sheet, t = tender_case(client)
    g = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "bid",
                                             "number": f"G-{tag()}", "bank_name": "بانک ملت"}).json()
    doc = client.post("/api/company-documents", json={"title": f"گواهی رتبه {tag()}"}).json()
    for q, kind, wanted in ((t["tender_no"], "tender", t["id"]), (g["number"], "guarantee", g["id"]),
                            (doc["title"], "company_document", doc["id"])):
        flat = str(client.get("/api/search", params={"q": q}).json())
        assert wanted in flat, (kind, q)


def test_cascade_delete_counts_and_cancels_followups(client, db):
    case, items, party, sheet, t = tender_case(client)
    g = client.post("/api/guarantees", json={"case_id": case["id"], "tender_id": t["id"], "purpose": "bid"}).json()
    client.post(f"/api/guarantees/{g['id']}/status", json={"status": "issued", "valid_until": day(60)})
    client.post(f"/api/tenders/{t['id']}/addenda", json={"received_on": day(0), "kind": "clarification", "summary": "توضیح"})
    client.post(f"/api/tenders/{t['id']}/costs", json={"kind": "travel", "amount": "1000"})
    new_proposal(client, t)
    open_before = len(followups(db, party["id"])) + len(tasks(db, party["id"]))
    assert open_before >= 4
    r = client.request("DELETE", f"/api/cases/{case['id']}", params={"cascade": "true"}, json={"confirm_title": case["title"]})
    assert r.status_code == 200, r.text
    counts = r.json()["counts"]
    assert counts["tenders"] == 1 and counts["guarantees"] == 1 and counts["tender_envelope_items"] == 14
    assert counts["tender_dates"] == 1 and counts["tender_addenda"] == 1 and counts["tender_costs"] == 1
    assert counts["tender_proposals"] == 1 and counts.get("followups_cancelled", 0) + counts["tasks"] >= open_before
    assert followups(db, party["id"]) == [] and tasks(db, party["id"]) == []
    assert db.execute(text("SELECT count(*) FROM ops.tender WHERE id = :i"), {"i": t["id"]}).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM ops.guarantee_event WHERE guarantee_id = :i"), {"i": g["id"]}).scalar() == 0


def test_audit_rows_and_events_for_every_new_table(client, db):
    case, items, party, sheet, t = tender_case(client)
    make_ready(client, t, case)
    client.post(f"/api/tenders/{t['id']}/addenda", json={"received_on": day(0), "kind": "change", "summary": "x",
                                                         "date_changes": [{"kind": "opening", "at": at(12)}]})
    client.post(f"/api/tenders/{t['id']}/costs", json={"kind": "travel", "amount": "1000"})
    client.post("/api/company-documents", json={"title": f"x {tag()}"})
    client.post("/api/envelope-templates", json={"name": f"t {tag()}", "lines": [{"envelope": "A", "title": "x"}]})
    d = next(x for x in client.get(f"/api/tenders/{t['id']}").json()["dates"] if x["kind"] == "proposal_deadline")
    client.patch(f"/api/tender-dates/{d['id']}", json={"at": at(13), "reason": "x"})
    audited = set(db.execute(text("SELECT DISTINCT table_name FROM core.audit")).scalars())
    for table in ("tender", "tender_date", "tender_date_change", "tender_addendum", "tender_followup", "company_document",
                  "envelope_template", "envelope_template_line", "envelope_item", "guarantee", "guarantee_event",
                  "tender_cost", "tender_proposal", "tender_proposal_line"):
        assert f"ops.{table}" in audited, table
    kinds = set(db.execute(text("SELECT DISTINCT entity_type FROM core.event")).scalars())
    assert {"tender", "guarantee", "company_document", "envelope_template"} <= kinds


def test_unknown_fields_are_refused_everywhere(client):
    z = "00000000-0000-0000-0000-000000000000"
    for method, path, body in (("post", f"/api/tenders/{z}/dates", {"kind": "opening", "at": "2026-12-01T10:00:00Z", "x": 1}),
                               ("post", "/api/guarantees", {"case_id": z, "purpose": "bid", "x": 1}),
                               ("post", "/api/company-documents", {"title": "a", "x": 1}),
                               ("post", f"/api/tenders/{z}/result", {"result": "won", "x": 1}),
                               ("post", f"/api/tenders/{z}/costs", {"kind": "other", "amount": "1", "x": 1})):
        assert getattr(client, method)(path, json=body).status_code == 422, path


# ---- migrations and backup -----------------------------------------------------------------------------------------------

def test_migrations_0011_0012_up_down_up_with_phase7a_data():
    from alembic import command

    from app.cli import alembic_config
    from app.core import dbadmin
    from app.core.config import get_config
    from tests.conftest import create_empty_database, superuser_conninfo

    name = "boms_test_p7b_migrations"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    new_tables = {"ops.tender", "ops.tender_date", "ops.guarantee", "ops.envelope_item", "ops.company_document",
                  "ops.tender_proposal", "ops.tender_result_reason"}

    def tables():
        with engine.connect() as conn:
            return set(conn.execute(text("SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname IN ('ops', 'ext')")).scalars())

    def p7a_rows():
        with engine.connect() as conn:
            return conn.execute(text(
                "SELECT (SELECT count(*) FROM ext.listing), (SELECT count(*) FROM ops.inquiry WHERE source_channel = 'setad'), "
                "(SELECT count(*) FROM ops.quote), (SELECT count(*) FROM ext.listing_screening WHERE status = 'converted')")).one()

    try:
        command.upgrade(cfg, "0010")
        with engine.begin() as conn:   # Phase 7a data: a listing converted to a Setad inquiry with a Setad quote
            conn.execute(text("INSERT INTO sys.currency (code, name_fa, name_en, minor_units) VALUES ('IRR', 'ریال', 'Rial', 0)"))
            party = conn.execute(text("INSERT INTO core.party (name_fa) VALUES ('خریدار') RETURNING id")).scalar()
            listing = conn.execute(text("INSERT INTO ext.listing (source, external_id, external_no, first_seen, last_seen) "
                                        "VALUES ('setad_tender', '77', '2005', now(), now()) RETURNING id")).scalar()
            inquiry = conn.execute(text("INSERT INTO ops.inquiry (party_id, source_channel, kind, received_at, listing_id, "
                                        "external_no) VALUES (:p, 'setad', 'tender', now(), :l, '2005') RETURNING id"),
                                   {"p": party, "l": listing}).scalar()
            conn.execute(text("INSERT INTO ext.listing_screening (listing_id, status, inquiry_id) VALUES (:l, 'converted', :i)"),
                         {"l": listing, "i": inquiry})
            case = conn.execute(text("INSERT INTO ops.\"case\" (title, party_id, inquiry_id) VALUES ('Setad case', :p, :i) "
                                     "RETURNING id"), {"p": party, "i": inquiry}).scalar()
            sheet = conn.execute(text("INSERT INTO ops.cost_sheet (case_id, version, deal_type, pricing_currency, status) "
                                      "VALUES (:c, 1, 'domestic', 'IRR', 'final') RETURNING id"), {"c": case}).scalar()
            conn.execute(text("INSERT INTO ops.quote (case_id, cost_sheet_id, version, number, language, currency, valid_until) "
                              "VALUES (:c, :s, 1, 'PI-1405-0009', 'fa', 'IRR', current_date + 9)"), {"c": case, "s": sheet})
        before = p7a_rows()
        assert not (new_tables & tables())
        command.upgrade(cfg, "head")
        assert new_tables <= tables() and p7a_rows() == before
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM ops.envelope_template_line")).scalar() == 14
            assert conn.execute(text("SELECT count(*) FROM ops.tender_result_reason")).scalar() == 8
            assert conn.execute(text("SELECT count(*) FROM ops.message_template WHERE name = 'Tender (fa)'")).scalar() == 1
        command.downgrade(cfg, "0010")
        assert not (new_tables & tables()) and p7a_rows() == before
        command.upgrade(cfg, "head")
        assert new_tables <= tables() and p7a_rows() == before
    finally:
        engine.dispose()
        dbadmin.drop_database(superuser_conninfo(), name)


def test_backup_and_restore_test_cover_every_table_with_tender_data(client):
    from app.core.db import get_engine
    from app.modules.system import backup

    case, items, party, sheet, t = tender_case(client)
    make_ready(client, t, case)
    doc = upload(client, f"lib-{tag()}.txt", unique_bytes("lib")).json()
    client.post("/api/company-documents", json={"title": f"x {tag()}", "document_id": doc["id"]})
    client.post(f"/api/tenders/{t['id']}/costs", json={"kind": "travel", "amount": "1000"})
    run_id = backup.run_backup("manual", source="script")
    result = backup.restore_test(run_id, source="script")
    with get_engine().connect() as conn:
        counts = backup.table_counts(conn)
    assert result["status"] == "passed", result
    assert result["details"]["tables_checked"] == len(counts) and result["details"]["row_count_mismatches"] == {}
    for table in ("ops.tender", "ops.tender_date", "ops.envelope_item", "ops.guarantee", "ops.guarantee_event",
                  "ops.tender_cost", "ops.tender_proposal", "ops.tender_proposal_line", "ops.company_document",
                  "ops.envelope_template", "ops.tender_result_reason", "ops.tender_followup"):
        assert counts[table] > 0, table
