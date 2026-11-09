"""v0.9.0 milestone 4: the AI tasks (item extraction from a text PDF, a scanned page, an Excel sheet, a pasted e-mail
and a supplier offer; party parse; drafting) with recorded fake responses (no network), numbers rechecked by code, and
the noun-modifier templates (validation, canonical descriptions fa/en, overrides, outputs)."""
import io
import json

import httpx
import pytest
from sqlalchemy import text

from tests.conftest import make_pdf, upload
from tests.test_parties import make_party, tag
from tests.test_v090_m3 import _reset, route, setup_provider


class Recorder:
    def __init__(self):
        self.bodies: list[dict] = []
        self.answers: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        answer = self.answers.pop(0)
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}, "prompt_eval_count": 900,
                                         "eval_count": 200})


@pytest.fixture
def ai(client, db):
    from app.modules.ai import adapters, builtin, tasks

    _reset(db)
    db.commit()
    rec = Recorder()
    adapters.set_transport(httpx.MockTransport(rec))
    local = setup_provider(client, "ollama", "qwen2.5-vl", price=None)
    for task in ("extraction", "party_parse", "drafting"):
        route(client, task, local, "qwen2.5-vl", privacy="cloud_redacted")
    if "extract_items" not in tasks.TASKS:
        builtin.register()
    yield rec
    adapters.set_transport(None)
    _reset(db)
    db.commit()


def run_draft(db, draft_json) -> dict:
    from app.modules.ai import tasks

    job = db.execute(text("SELECT payload FROM sys.job WHERE id = (SELECT job_id FROM ai.draft WHERE id = :d)"),
                     {"d": draft_json["id"]}).scalar()
    tasks.run_job(db, job)
    db.commit()
    return job


def fields(client, draft_id) -> dict:
    d = client.get(f"/api/ai/drafts/{draft_id}").json()
    return {f["path"]: f for f in d["fields"]} | {"_draft": d}


def accept_all(client, draft_id):
    d = client.get(f"/api/ai/drafts/{draft_id}").json()
    for f in d["fields"]:
        client.patch(f"/api/ai/drafts/{draft_id}/fields/{f['id']}", json={"decision": "accepted"})


ITEM = {"original": "Centrifugal pump API 610, Q=120 m3/h, H=85 m — 2 sets", "noun": "PUMP", "template": "pump",
        "attributes": {"type": "centrifugal", "standard": "API 610", "flow": "120", "head": "85"},
        "description_en": None, "description_fa": None, "quantity": 2, "unit": "SET", "unit_text": None,
        "specs": [{"key": "Seal", "value": "Plan 53B"}], "hs_code": "84137010", "hs_reason": "centrifugal pumps for liquids",
        "standards": ["API 610"], "page": 1, "confidence": "high"}


def test_text_pdf_extraction_review_and_commit(client, db, ai):
    case = client.post("/api/cases", json={"title": f"Pumps {tag()}"}).json()
    doc = upload(client, f"rfq-{tag()}.pdf", make_pdf("Request: centrifugal pump API 610 Q=120 m3/h H=85 m, 2 sets. "
                                                      "Delivery CFR Bandar Abbas.")).json()
    ai.answers.append({"items": [ITEM], "terms": {"incoterm": "CFR", "incoterm_place": "Bandar Abbas"}, "column_mapping": None})
    r = client.post("/api/ai/extract", json={"target_type": "case", "target_id": case["id"], "document_ids": [doc["id"]]})
    assert r.status_code == 202 and r.json()["status"] == "pending"
    run_draft(db, r.json())
    sent = json.dumps(ai.bodies[-1], ensure_ascii=False)
    assert "centrifugal pump API 610" in sent and "page 1" in sent and "- pump: PUMP" in sent      # the PDF text layer
    f = fields(client, r.json()["id"])
    assert f["_draft"]["status"] == "ready" and f["_draft"]["sources"][0]["kind"] == "pdf"
    assert f["items[0].canonical_en"]["proposed"] == "PUMP, CENTRIFUGAL, API 610, 120 m3/h, 85 m"
    assert f["items[0].canonical_fa"]["proposed"] == "پمپ، گریز از مرکز، API 610، ۱۲۰ مترمکعب بر ساعت، ۸۵ متر"
    assert f["items[0].hs_code"]["confidence"] == "medium" and f["items[0].unit_code"]["proposed"] == "set"
    assert f["items[0].name"]["source"] == {"page": 1, "original": ITEM["original"]}
    assert client.get(f"/api/cases/{case['id']}").json().get("items", []) == [] or \
        db.execute(text("SELECT count(*) FROM ops.line_item WHERE case_id = :c"), {"c": case["id"]}).scalar() == 0
    client.post(f"/api/ai/drafts/{r.json()['id']}/accept-confident")
    r2 = client.post(f"/api/ai/drafts/{r.json()['id']}/commit")
    assert r2.status_code == 200, r2.text
    item_id = r2.json()["result"]["line_item_ids"][0]
    item = client.get(f"/api/line-items/{item_id}").json()
    assert item["canonical_en"] == "PUMP, CENTRIFUGAL, API 610, 120 m3/h, 85 m" and item["attributes"]["flow"] == "120"
    assert item["quantity"] == "2" or float(item["quantity"]) == 2
    ev = db.execute(text("SELECT source FROM core.event WHERE entity_type = 'line_item' AND entity_id = :i"),
                    {"i": item_id}).scalar()
    assert ev == "ai_draft"
    call = db.execute(text("SELECT input::text, status FROM ai.call ORDER BY created_at DESC LIMIT 1")).one()
    assert "centrifugal" not in call.input and call.status == "ok" and '"pages": 1' in call.input


def test_scanned_page_goes_as_an_image(client, db, ai):
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 40), 0)
    pix.clear_with(200)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    data = pdf.tobytes()
    case = client.post("/api/cases", json={"title": f"Scan {tag()}"}).json()
    doc = upload(client, f"scan-{tag()}.pdf", data).json()
    ai.answers.append({"items": [{**ITEM, "confidence": "low", "page": 1}], "terms": None, "column_mapping": None})
    r = client.post("/api/ai/extract", json={"target_type": "case", "target_id": case["id"], "document_ids": [doc["id"]]})
    run_draft(db, r.json())
    body = ai.bodies[-1]
    assert body["messages"][1]["images"] and "scanned" in body["messages"][1]["content"]
    assert fields(client, r.json()["id"])["items[0].name"]["confidence"] == "low"


def test_excel_sheet_with_column_mapping(client, db, ai):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Item", "Qty", "Unit", "HS"])
    ws.append(["Gate valve 6\" class 300 WCB", 4, "pcs", "848180"])
    buffer = io.BytesIO()
    wb.save(buffer)
    case = client.post("/api/cases", json={"title": f"Sheet {tag()}"}).json()
    doc = upload(client, f"list-{tag()}.xlsx", buffer.getvalue()).json()
    ai.answers.append({"items": [{"original": "Gate valve 6\" class 300 WCB", "noun": "VALVE", "template": "valve",
                                  "attributes": {"type": "gate", "size": "6", "rating": "300", "material": "cs"},
                                  "quantity": 4, "unit": "H87", "page": 2, "confidence": "high"}],
                       "terms": None, "column_mapping": ["name", "quantity", "unit", "hs_code"]})
    r = client.post("/api/ai/extract", json={"target_type": "case", "target_id": case["id"], "document_ids": [doc["id"]]})
    run_draft(db, r.json())
    assert "row 2: [0] Gate valve" in ai.bodies[-1]["messages"][1]["content"]
    f = fields(client, r.json()["id"])
    assert f["column_mapping"]["proposed"] == ["name", "quantity", "unit", "hs_code"]
    assert f["items[0].canonical_en"]["proposed"] == 'VALVE, GATE, 6", CLASS 300, CARBON STEEL'
    assert f["_draft"]["sources"][0]["kind"] == "sheet" and f["_draft"]["sources"][0]["rows"] == 2


def test_pasted_email_is_read(client, db, ai):
    """A local model runs on the owner's PC: the text goes as written (cloud routes are redacted, see milestone 3)."""
    party = make_party(client, name_en=f"Pars Oil {tag()}", roles=["buyer"])
    case = client.post("/api/cases", json={"title": f"Mail {tag()}", "party_id": party["id"]}).json()
    mail = f"Dear supplier,\n{party['name_en']} needs 10 ball valves 2\" class 150.\nali@parsoil.ir, +98 21 8888 7777"
    ai.answers.append({"items": [{"original": "10 ball valves 2\" class 150 for ⟦PARTY_1⟧", "noun": "VALVE",
                                  "template": "valve", "attributes": {"type": "ball", "size": "2", "rating": "150"},
                                  "quantity": 10, "unit": "H87", "page": None, "confidence": "high"}],
                       "terms": None, "column_mapping": None})
    r = client.post("/api/ai/extract", json={"target_type": "case", "target_id": case["id"], "text": mail})
    run_draft(db, r.json())
    sent = json.dumps(ai.bodies[-1], ensure_ascii=False)
    assert party["name_en"] in sent and "--- pasted text ---" in sent
    call = db.execute(text("SELECT redactions FROM ai.call ORDER BY created_at DESC LIMIT 1")).scalar()
    assert call == {}
    f = fields(client, r.json()["id"])
    assert f["items[0].quantity"]["proposed"] == "10"
    assert f["_draft"]["sources"][0]["kind"] == "pasted"


def test_supplier_offer_numbers_rechecked_and_committed(client, db, ai):
    from tests.test_sourcing_rfq import make_case

    case, items = make_case(client, [{"name": "Valve", "quantity": "10"}, {"name": "Pump", "quantity": "2"}])
    sup = make_party(client, name_en=f"Shanghai Valve {tag()}", roles=["supplier"])
    ai.answers.append({"items": [
        {"original": "Valve DN150", "noun": "VALVE", "template": None, "attributes": {}, "quantity": 10, "unit": "H87",
         "line_item": 1, "unit_price": "120.50", "total": "1205.00", "page": 1, "confidence": "high"},
        {"original": "Pump", "noun": "PUMP", "template": None, "attributes": {}, "quantity": 2, "unit": "H87",
         "line_item": 2, "unit_price": "900", "total": "1900", "page": 1, "confidence": "high"}],
        "terms": {"currency": "USD", "incoterm": "FOB", "incoterm_place": "Shanghai", "valid_until": "2027-01-31",
                  "payment_terms": "30% advance"}, "column_mapping": None})
    r = client.post("/api/ai/extract", json={"target_type": "offer", "target_id": case["id"], "party_id": sup["id"],
                                             "text": "Our offer: Valve DN150 10 pcs @120.50 = 1205; Pump 2 @900 = 1900"})
    run_draft(db, r.json())
    f = fields(client, r.json()["id"])
    assert f["_draft"]["checks"] == [{"item": 1, "kind": "total_differs", "stated": "1900", "computed": "1800.00"}]
    assert f["items[1].unit_price"]["confidence"] == "low" and f["items[0].unit_price"]["confidence"] == "high"
    assert f["items[0].line_item"]["proposed"] == items[0]["id"]
    accept_all(client, r.json()["id"])
    r2 = client.post(f"/api/ai/drafts/{r.json()['id']}/commit")
    assert r2.status_code == 200, r2.text
    offer = client.get(f"/api/offers/{r2.json()['result']['offer_id']}").json()
    assert offer["currency"] == "USD" and offer["incoterm"] == "FOB" and len(offer["items"]) == 2


def test_party_parse_creates_party_and_contact(client, db, ai):
    name = f"Ningbo Flow {tag()}"
    ai.answers.append({"company": {"name": f"{name} Co., Ltd.", "legal_form": "Co., Ltd.", "country_iso2": "cn",
                                   "website": "https://flow.example", "phones": None, "emails": None},
                       "person": {"name": "Wang Wei", "title": "Sales manager", "phones": ["+86 574 8888 1234"],
                                  "emails": ["wang@flow.example"]}})
    r = client.post("/api/ai/parse-party", json={"text": f"Wang Wei | Sales manager\n{name} Co., Ltd.", "roles": ["supplier"]})
    run_draft(db, r.json())
    accept_all(client, r.json()["id"])
    r2 = client.post(f"/api/ai/drafts/{r.json()['id']}/commit")
    assert r2.status_code == 200, r2.text
    party = client.get(f"/api/parties/{r2.json()['result']['party_id']}").json()
    assert party["country_iso2"] == "CN" and party["code"].startswith("SUP-CN-")
    assert party.get("legal_form_id")


def test_drafting_rfq_message_with_back_translation(client, db, ai):
    from tests.test_sourcing_rfq import make_case, new_rfq, supplier

    case, items = make_case(client, [{"name": "Valve", "quantity": "2"}])
    body = new_rfq(client, case, items, [{"party_id": supplier(client)["id"]}])
    rec_id = body["recipients"][0]["id"]
    ai.answers.append({"subject": f"[{body['code']}] Request for Quotation – Valve", "body": "Dear Sir, please quote 2 valves.",
                       "back_translation_fa": "با سلام، لطفاً برای ۲ شیر قیمت بدهید."})
    r = client.post("/api/ai/draft-message", json={"target_type": "rfq_recipient", "target_id": rec_id})
    run_draft(db, r.json())
    assert "Valve: 2" in ai.bodies[-1]["messages"][1]["content"]
    f = fields(client, r.json()["id"])
    assert f["back_translation_fa"]["proposed"].startswith("با سلام")
    for key in ("subject", "body"):
        client.patch(f"/api/ai/drafts/{r.json()['id']}/fields/{f[key]['id']}", json={"decision": "accepted"})
    client.post(f"/api/ai/drafts/{r.json()['id']}/commit")
    recipient = client.get(f"/api/rfqs/{body['id']}").json()["recipients"][0]
    assert recipient["subject"].startswith(f"[{body['code']}]") and recipient["message_text"].startswith("Dear Sir")


def test_extraction_without_a_provider_says_how_to_connect(client, db):
    _reset(db)
    db.commit()
    case = client.post("/api/cases", json={"title": f"None {tag()}"}).json()
    r = client.post("/api/ai/extract", json={"target_type": "case", "target_id": case["id"], "text": "2 pumps"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "ai_not_configured"
    assert client.get("/api/line-items/extractor").json()["configured"] is False


# ---- noun-modifier --------------------------------------------------------------------------------------------------

def test_templates_validation_canonical_and_overrides(client):
    templates = {t["key"]: t for t in client.get("/api/product-templates").json()}
    assert set(templates) >= {"pump", "valve", "pipe", "flange", "gasket", "mechanical_seal", "electric_motor",
                              "resin_chemical"}
    pump = templates["pump"]
    prev = client.post(f"/api/product-templates/{pump['id']}/preview", json={"attributes": {
        "type": "centrifugal", "standard": "API 610", "flow": "120", "head": "85", "material": "ss316"}}).json()
    assert prev["canonical_en"] == "PUMP, CENTRIFUGAL, API 610, 120 m3/h, 85 m"
    assert prev["canonical_fa"] == "پمپ، گریز از مرکز، API 610، ۱۲۰ مترمکعب بر ساعت، ۸۵ متر"
    assert prev["long_en"].endswith("SS 316")
    bad = client.post(f"/api/product-templates/{pump['id']}/preview", json={"attributes": {"type": "rotary", "flow": "x"}})
    assert bad.status_code == 422 and {p["reason"] for p in bad.json()["error"]["details"]["problems"]} == {"not_allowed", "not_a_number"}
    # product with template; then an override that sticks through attribute changes
    p = client.post("/api/products", json={"name_en": f"Pump {tag()}", "template_id": pump["id"], "confirm_duplicate": True,
                                           "attributes": {"type": "gear", "flow": "5"}}).json()["product"]
    assert p["canonical_en"] == "PUMP, GEAR, 5 m3/h" and p["code"].startswith("PRD-")
    p = client.patch(f"/api/products/{p['id']}", json={"canonical_override": True, "canonical_en": "GEAR PUMP 5 M3/H"}).json()
    p = client.patch(f"/api/products/{p['id']}", json={"attributes": {"type": "gear", "flow": "6"}}).json()
    assert p["canonical_en"] == "GEAR PUMP 5 M3/H" and p["attributes"]["flow"] == "6"
    p = client.patch(f"/api/products/{p['id']}", json={"canonical_override": False}).json()
    assert p["canonical_en"] == "PUMP, GEAR, 6 m3/h"
    r = client.patch(f"/api/products/{p['id']}", json={"attributes": {"colour": "red"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "attribute_invalid"
    # template definitions are checked
    bad = client.post("/api/product-templates", json={"key": f"t_{tag()}", "noun_fa": "x", "noun_en": "X",
                                                      "attributes": [{"key": "a", "type": "choice"}]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "template_invalid"
    new = client.post("/api/product-templates", json={"key": f"t_{tag()}", "noun_fa": "شیلنگ", "noun_en": "HOSE",
                                                      "attributes": [{"key": "size", "type": "number", "unit": "INH",
                                                                      "label_fa": "سایز", "label_en": "Size"}]})
    assert new.status_code == 201


def test_quote_output_uses_the_canonical_description(client):
    from tests.test_quotes import new_quote, ready_case

    case, items, party, sheet = ready_case(client)
    pump = next(t for t in client.get("/api/product-templates").json() if t["key"] == "pump")
    client.patch(f"/api/line-items/{items[0]['id']}", json={"template_id": pump["id"],
                                                             "attributes": {"type": "centrifugal", "flow": "120"}})
    quote = new_quote(client, case)
    client.patch(f"/api/quotes/{quote['id']}", json={"language": "en"})
    html = client.get(f"/api/quotes/{quote['id']}/print").text
    assert "PUMP, CENTRIFUGAL, 120 m3/h" in html
    client.patch(f"/api/quotes/{quote['id']}", json={"language": "fa"})
    html = client.get(f"/api/quotes/{quote['id']}/print").text
    assert "پمپ، گریز از مرکز، ۱۲۰ مترمکعب بر ساعت" in html


def test_migration_0020_down_up_keeps_attributes():
    from alembic import command
    from sqlalchemy import create_engine

    from app.cli import alembic_config
    from app.core.config import get_config
    from tests.conftest import create_empty_database

    name = "boms_test_v090_nounmod_migration"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO core.product (name_en, template_id, attributes, canonical_en) SELECT 'P', id, "
                              "'{\"type\": \"gear\"}', 'PUMP, GEAR' FROM core.product_template WHERE key = 'pump'"))
        command.downgrade(cfg, "0019")
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            row = conn.execute(text("SELECT t.key, p.attributes, p.canonical_en FROM core.product p "
                                    "JOIN core.product_template t ON t.id = p.template_id")).one()
            assert tuple(row) == ("pump", {"type": "gear"}, "PUMP, GEAR")
    finally:
        engine.dispose()

