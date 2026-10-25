"""Phase 5 milestone 1: migration 0006, inquiries, decisions, cases, line items, item import."""

import io
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
from alembic import command
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError

from app.cli import alembic_config
from app.core import dbadmin
from app.core.config import get_config
from app.modules.sourcing.models import Case, Inquiry, LineItem
from tests.conftest import create_empty_database, superuser_conninfo, unique_bytes, upload
from tests.test_parties import make_party, tag


def inquiry(client, items=(), **extra):
    body = {"source_channel": "email", "subject": f"Inquiry {tag()}", "items": list(items), **extra}
    r = client.post("/api/inquiries", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def decide(client, inquiry_id, light="green", **extra):
    body = {"light": light, "reason": "looks fine", "feasible_sourcing": "yes", "exposure_acceptable": "yes",
            "requirements_ok": "yes", **extra}
    return client.put(f"/api/inquiries/{inquiry_id}/decision", json=body)


def events(client, entity_type, entity_id, action=None):
    params = {"entity_type": entity_type, "entity_id": entity_id, "page_size": 200}
    if action:
        params["action"] = action
    return client.get("/api/events", params=params).json()["items"]


def audit_ops(db, table, row_id) -> list[str]:
    return list(db.execute(text("SELECT op FROM core.audit WHERE table_name = :t AND row_id = :r ORDER BY id"),
                           {"t": table, "r": str(row_id)}).scalars())


# ---- migration ---------------------------------------------------------------------------------

def test_migration_0006_up_down_up():
    db_name = "boms_test_sourcing_migration"
    create_empty_database(db_name)
    url = get_config().db_url(db_name)
    cfg = alembic_config(url)
    engine = create_engine(url)

    def tables():
        with engine.connect() as conn:
            return set(conn.execute(text(
                "SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname IN ('ops', 'core', 'ref')"
            )).scalars())

    new = {"ops.inquiry", "ops.decision", "ops.case", "ops.line_item", "ops.rfq", "ops.rfq_item", "ops.rfq_recipient",
           "ops.message_template", "ops.supplier_offer", "ops.offer_item", "ops.payment_term", "ops.item_status",
           "core.product", "core.product_alias", "core.product_category", "core.party_capability", "ref.hs_code",
           "ref.isic_code"}
    try:
        command.upgrade(cfg, "head")
        assert new <= tables()
        command.downgrade(cfg, "0005")
        assert not (new & tables()) and "core.party" in tables()
        command.upgrade(cfg, "head")
        assert new <= tables()
        with engine.connect() as conn:
            counts = dict(conn.execute(text("SELECT level::text, count(*) FROM ref.hs_code GROUP BY 1")).all())
            assert counts == {"2": 96, "4": 1228}
            assert conn.execute(text("SELECT count(*) FROM ops.message_template WHERE is_default")).scalar() == 4
    finally:
        engine.dispose()
        dbadmin.drop_database(superuser_conninfo(), db_name)


# ---- inquiry -> decision -> case gate -------------------------------------------------------------

def test_green_decision_converts_and_items_move_without_copies(client, db):
    party = make_party(client, roles=["buyer"])
    inq = inquiry(client, party_id=party["id"], items=[
        {"name": "Polyethylene HD", "quantity": "20", "unit_code": "t", "specs": [{"key": "Grade", "value": "PE100"}]},
        {"name": "Sulphuric acid 98%", "quantity": "5000", "unit_code": "kg"},
        {"name": "Ball valve DN50", "quantity": "12", "unit_code": "pc"}])
    assert len(inq["items"]) == 3 and inq["gate"]["code"] == "decision_required"
    item_ids = [i["id"] for i in inq["items"]]
    r = client.post(f"/api/inquiries/{inq['id']}/convert", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "decision_required"
    assert decide(client, inq["id"]).json()["gate"]["ok"] is True
    before = db.scalar(select(func.count()).select_from(LineItem))
    r = client.post(f"/api/inquiries/{inq['id']}/convert", json={"title": "PE and acid"})
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["title"] == "PE and acid" and case["party_id"] == party["id"] and case["inquiry_id"] == inq["id"]
    assert [i["id"] for i in case["items"]] == item_ids  # the same rows
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(LineItem)) == before  # no copies
    detail = client.get(f"/api/inquiries/{inq['id']}").json()
    assert detail["status"] == "converted" and detail["case_id"] == case["id"]
    assert {i["case_id"] for i in detail["items"]} == {case["id"]}
    r = client.post(f"/api/inquiries/{inq['id']}/convert", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_converted"
    assert events(client, "case", case["id"], "create")
    assert audit_ops(db, "ops.case", case["id"])[0] == "I"


def test_yellow_needs_confirmation(client):
    inq = inquiry(client)
    assert decide(client, inq["id"], light="yellow").json()["gate"]["code"] == "confirmation_required"
    r = client.post(f"/api/inquiries/{inq['id']}/convert", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirmation_required"
    assert decide(client, inq["id"], light="yellow", confirmed=True).json()["gate"]["ok"] is True
    assert client.post(f"/api/inquiries/{inq['id']}/convert", json={}).status_code == 201


@pytest.mark.parametrize("check", ["feasible_sourcing", "exposure_acceptable", "requirements_ok"])
def test_any_hard_check_no_blocks(client, check):
    inq = inquiry(client)
    decide(client, inq["id"], **{check: "no", f"{check}_note": "not possible"})
    r = client.post(f"/api/inquiries/{inq['id']}/convert", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "hard_check_failed" and r.json()["error"]["details"]["checks"] == [check]


def test_red_rejects_with_reason(client):
    inq = inquiry(client)
    r = client.put(f"/api/inquiries/{inq['id']}/decision", json={"light": "red", "reason": " "})
    assert r.status_code == 422
    r = decide(client, inq["id"], light="red", reason="sanctioned end user")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected" and body["reject_reason"] == "sanctioned end user"
    assert client.post(f"/api/inquiries/{inq['id']}/convert", json={}).json()["error"]["code"] == "decision_red"
    history = events(client, "inquiry", inq["id"], "decision")
    assert history[0]["data"]["after"]["light"] == "red"


def test_order_before_payment_requires_reason_and_copies_to_case(client):
    inq = inquiry(client)
    r = decide(client, inq["id"], payment_term="order_before_payment")
    assert r.status_code == 422 and r.json()["error"]["code"] == "ordering_before_payment_reason_required"
    r = decide(client, inq["id"], payment_term="order_before_payment",
               ordering_before_payment_reason="Long-time buyer, approved by me", exposure_estimate="12500.50",
               exposure_currency="EUR")
    assert r.status_code == 200
    case = client.post(f"/api/inquiries/{inq['id']}/convert", json={}).json()
    assert case["payment_term"] == "order_before_payment"
    assert case["ordering_before_payment_reason"] == "Long-time buyer, approved by me"
    assert Decimal(case["exposure_estimate"]) == Decimal("12500.5") and case["exposure_currency"] == "EUR"
    r = client.patch(f"/api/cases/{case['id']}", json={"ordering_before_payment_reason": None})
    assert r.status_code == 422
    r = client.patch(f"/api/cases/{case['id']}", json={"exposure_estimate": "9000", "payment_term": "lc_or_guarantee"})
    assert r.status_code == 200
    ev = events(client, "case", case["id"], "update")[0]["data"]["changes"]
    assert ev["payment_term"] == {"old": "order_before_payment", "new": "lc_or_guarantee"}
    assert decide(client, inquiry(client)["id"], payment_term="nope").status_code == 422


def test_case_without_inquiry_and_delete_rules(client, db):
    case = client.post("/api/cases", json={"title": f"Walk-in {tag()}"}).json()
    assert case["inquiry_id"] is None
    assert client.delete(f"/api/cases/{case['id']}").status_code == 204
    assert client.get(f"/api/cases/{case['id']}").status_code == 404
    assert events(client, "case", case["id"], "delete")[0]["data"]["deleted"]["title"] == case["title"]
    assert audit_ops(db, "ops.case", case["id"]) == ["I", "D"]
    case = client.post("/api/cases", json={"title": f"With items {tag()}"}).json()
    client.post("/api/line-items", json={"case_id": case["id"], "name": "Copper cathode"})
    r = client.delete(f"/api/cases/{case['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"] == {"items": 1, "rfqs": 0, "offers": 0, "documents": 0}
    r = client.patch(f"/api/cases/{case['id']}", json={"status": "cancelled"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_inquiry_delete_rules(client, db):
    inq = inquiry(client, items=[{"name": "Item A"}])
    assert client.delete(f"/api/inquiries/{inq['id']}").status_code == 204
    snap = events(client, "inquiry", inq["id"], "delete")[0]["data"]["deleted"]
    assert snap["items"][0]["name"] == "Item A"
    assert audit_ops(db, "ops.line_item", inq["items"][0]["id"]) == ["I", "D"]
    inq = inquiry(client)
    decide(client, inq["id"])
    client.post(f"/api/inquiries/{inq['id']}/convert", json={})
    r = client.delete(f"/api/inquiries/{inq['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"]["cases"] == 1


def test_quick_create_from_interaction(client):
    party = make_party(client)
    row = client.post("/api/interactions", json={"party_id": party["id"], "channel": "call", "direction": "in",
                                                 "subject": "Need valves", "body": "10 x DN50 ball valves",
                                                 "no_followup_reason": "inquiry follows"}).json()
    pre = client.get("/api/inquiries/prefill", params={"interaction_id": row["id"]}).json()
    assert pre["party_id"] == party["id"] and pre["source_channel"] == "phone"
    assert pre["raw_text"] == "10 x DN50 ball valves" and pre["source_interaction_id"] == row["id"]
    inq = client.post("/api/inquiries", json={k: v for k, v in pre.items()}).json()
    assert inq["source_interaction_id"] == row["id"] and inq["raw_text"] == "10 x DN50 ball valves"


def test_raw_text_is_never_altered(client):
    raw = "  سلام\n\nلطفاً قیمت:\n- لوله ۲ اینچ\t۱۲۰ متر  \n"
    inq = inquiry(client, raw_text=raw)
    assert inq["raw_text"] == raw
    r = client.patch(f"/api/inquiries/{inq['id']}", json={"raw_text": "changed"})
    assert r.status_code == 422  # not a patchable field


def test_inquiry_status_and_reject(client):
    inq = inquiry(client)
    assert client.patch(f"/api/inquiries/{inq['id']}", json={"status": "needs_info"}).json()["status"] == "needs_info"
    assert client.patch(f"/api/inquiries/{inq['id']}", json={"status": "converted"}).status_code == 422
    assert client.post(f"/api/inquiries/{inq['id']}/reject", json={"reason": ""}).status_code == 422
    r = client.post(f"/api/inquiries/{inq['id']}/reject", json={"reason": "no reply from buyer"})
    assert r.json()["status"] == "rejected"


# ---- line items ------------------------------------------------------------------------------------

def test_specs_roundtrip_and_key_suggestions(client):
    key = f"Purity{tag()}"
    inq = inquiry(client, items=[{"name": "Caustic soda", "specs": [
        {"key": key, "value": "99%"}, {"key": "CAS", "value": "1310-73-2"}, {"key": " ", "value": "dropped"},
        {"key": "Voltage", "value": "380", "unit": "V"}]}])
    specs = inq["items"][0]["specs"]
    assert specs == [{"key": key, "value": "99%"}, {"key": "CAS", "value": "1310-73-2"},
                     {"key": "Voltage", "value": "380", "unit": "V"}]
    inquiry(client, items=[{"name": "Other", "specs": [{"key": key.upper(), "value": "98%"}]}])
    suggestions = client.get("/api/line-items/spec-keys", params={"q": key.lower()[:-2]}).json()
    assert suggestions == [key]  # grouped case-insensitively, first spelling kept
    item_id = inq["items"][0]["id"]
    r = client.patch(f"/api/line-items/{item_id}", json={"specs": [{"key": "CAS", "value": "1310-73-2"}]})
    assert r.json()["specs"] == [{"key": "CAS", "value": "1310-73-2"}]
    ev = events(client, "line_item", item_id, "update")[0]
    assert "specs" in ev["data"]["changes"]


def test_duplicate_item_names_warn(client):
    inq = inquiry(client, items=[{"name": "Steel pipe"}, {"name": "steel  pipe"}])
    assert {w["code"] for w in inq["warnings"]} == {"duplicate_name"} and len(inq["warnings"]) == 2


def test_item_validation_and_unknown_references(client):
    inq = inquiry(client)
    base = {"inquiry_id": inq["id"], "name": "X"}
    assert client.post("/api/line-items", json={**base, "unit_code": "parsec"}).json()["error"]["code"] == "unknown_unit"
    r = client.post("/api/line-items", json={**base, "target_price": "10"})
    assert r.status_code == 422  # price needs a currency
    assert client.post("/api/line-items", json={**base, "quantity": "-1"}).status_code == 422
    assert client.post("/api/line-items", json={**base, "incoterm": "XYZ"}).status_code == 422
    assert client.post("/api/line-items", json={"name": "orphan"}).json()["error"]["code"] == "owner_required"
    r = client.post("/api/line-items", json={**base, "quantity": "1.5", "unit_text": "barrels of 200 l",
                                             "target_price": "10", "target_currency": "USD", "incoterm": "CIF",
                                             "incoterm_place": "Bandar Abbas", "destination_country_iso2": "ir",
                                             "route": "foreign", "hs_code": "3901"})
    assert r.status_code == 201, r.text
    assert r.json()["destination_country_iso2"] == "IR" and Decimal(r.json()["quantity"]) == Decimal("1.5")


def test_item_delete_and_cancel(client, db):
    inq = inquiry(client, items=[{"name": "A"}])
    item = inq["items"][0]
    doc = upload(client, "drawing.txt", unique_bytes("drawing")).json()
    assert client.post(f"/api/line-items/{item['id']}/documents", json={"document_id": doc["id"]}).status_code == 201
    r = client.delete(f"/api/line-items/{item['id']}")
    assert r.status_code == 409 and r.json()["error"]["details"] == {"rfqs": 0, "offers": 0, "documents": 1}
    r = client.post(f"/api/line-items/{item['id']}/cancel", json={"reason": "buyer dropped it"})
    assert r.json()["status"] == "cancelled"
    other = client.post("/api/line-items", json={"inquiry_id": inq["id"], "name": "B"}).json()
    assert client.delete(f"/api/line-items/{other['id']}").status_code == 204
    assert audit_ops(db, "ops.line_item", other["id"]) == ["I", "D"]


def test_no_coverage_mark_requires_reason(client):
    inq = inquiry(client, items=[{"name": "Rare part"}])
    item_id = inq["items"][0]["id"]
    assert client.post(f"/api/line-items/{item_id}/no-coverage", json={"reason": ""}).status_code == 422
    r = client.post(f"/api/line-items/{item_id}/no-coverage", json={"reason": "obsolete model"})
    assert r.json()["no_coverage_confirmed"] is True and r.json()["no_coverage_reason"] == "obsolete model"
    r = client.delete(f"/api/line-items/{item_id}/no-coverage")
    assert r.json()["no_coverage_confirmed"] is False


# ---- import -----------------------------------------------------------------------------------------

def test_import_pasted_table_with_bad_row(client):
    text_table = "Item\tQty\tUnit\tPrice\nSteel pipe 2\"\t1,200\tm\t\nGate valve\tabc\tpcs\t\n\tfive\tkg\t12\nCable\t۳۰۰\tمتر\t"
    parsed = client.post("/api/line-items/import/parse", json={"text": text_table}).json()
    assert parsed["has_header"] is True
    assert parsed["mapping"] == [{"column": 0, "field": "name"}, {"column": 1, "field": "quantity"},
                                 {"column": 2, "field": "unit"}, {"column": 3, "field": "target_price"}]
    preview = client.post("/api/line-items/import/preview", json={
        "rows": parsed["rows"], "mapping": parsed["mapping"], "skip_header": True}).json()
    rows = preview["rows"]
    assert rows[0]["item"] == {"name": 'Steel pipe 2"', "quantity": "1200", "unit_code": "m", "specs": []}
    assert rows[1]["errors"] == [{"field": "quantity", "code": "invalid_number", "value": "abc"}]
    assert {e["code"] for e in rows[2]["errors"]} == {"invalid_number", "name_required"}
    assert rows[3]["item"]["quantity"] == "300" and rows[3]["item"]["unit_code"] == "m"
    assert preview["errors"] == 2
    good = [r["item"] for r in rows if not r["errors"]]
    inq = inquiry(client)
    r = client.post("/api/line-items/bulk", json={"inquiry_id": inq["id"], "items": good})
    assert r.status_code == 201 and len(r.json()["items"]) == 2


def test_import_text_list_and_spec_column(client):
    parsed = client.post("/api/line-items/import/parse", json={"text": "1. پلی‌اتیلن سنگین\n2. اسید سولفوریک"}).json()
    assert parsed["rows"] == [["پلی‌اتیلن سنگین"], ["اسید سولفوریک"]] and parsed["has_header"] is False
    rows = [["Pump", "3", "Grundfos"]]
    preview = client.post("/api/line-items/import/preview", json={"rows": rows, "mapping": [
        {"column": 0, "field": "name"}, {"column": 1, "field": "quantity"},
        {"column": 2, "field": "spec", "spec_key": "Brand"}]}).json()
    assert preview["rows"][0]["item"]["specs"] == [{"key": "Brand", "value": "Grundfos"}]


def test_import_xlsx_and_csv_upload(client):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Quantity", "Unit", "HS code"])
    ws.append(["Copper cathode", 25, "t", "7403"])
    ws.append(["Zinc ingot", "n/a", "t", "7901"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/line-items/import/upload",
                    files={"file": ("items.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    parsed = r.json()
    assert parsed["rows"][1] == ["Copper cathode", "25", "t", "7403"]
    preview = client.post("/api/line-items/import/preview", json={
        "rows": parsed["rows"], "mapping": parsed["mapping"], "skip_header": True}).json()
    assert preview["rows"][0]["item"]["hs_code"] == "7403" and preview["rows"][0]["errors"] == []
    assert preview["rows"][1]["errors"][0]["code"] == "invalid_number"
    csv_data = "name;qty\nBolt M8;100\n".encode()
    r = client.post("/api/line-items/import/upload", files={"file": ("items.csv", csv_data, "text/csv")})
    assert r.json()["rows"] == [["name", "qty"], ["Bolt M8", "100"]]
    r = client.post("/api/line-items/import/upload", files={"file": ("x.xlsx", b"not a zip", "application/zip")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unreadable_file"


def test_pdf_text_beside_item_form_and_extractor_disabled(client):
    from tests.conftest import make_pdf

    doc = upload(client, "rfq.pdf", make_pdf(f"Item 1: Gear pump 5 pcs {tag()}")).json()
    from app.worker import runner
    from app.worker.registry import load_handlers

    load_handlers()
    runner.run_until_idle(backoff_base=0)
    r = client.get(f"/api/line-items/document-text/{doc['id']}").json()
    assert "Gear pump 5 pcs" in r["text"]
    assert client.get("/api/line-items/extractor").json() == {"name": "disabled", "configured": False}
    r = client.post("/api/line-items/extract", json={"text": "anything"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "extractor_not_configured"


# ---- hardening ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("path,body", [
    ("/api/inquiries", {"source_channel": "email", "bogus": 1}),
    ("/api/cases", {"title": "x", "bogus": 1}),
    ("/api/line-items", {"name": "x", "case_id": None, "bogus": 1}),
    ("/api/line-items/import/parse", {"text": "x", "bogus": 1}),
])
def test_unknown_fields_rejected(client, path, body):
    r = client.post(path, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_failed_create_persists_nothing(client, db):
    before = (db.scalar(select(func.count()).select_from(Inquiry)), db.scalar(select(func.count()).select_from(LineItem)),
              db.execute(text("SELECT count(*) FROM core.event")).scalar())
    r = client.post("/api/inquiries", json={"source_channel": "email", "items": [{"name": "ok"},
                                                                                 {"name": "bad", "unit_code": "zz"}]})
    assert r.status_code == 422
    db.expire_all()
    after = (db.scalar(select(func.count()).select_from(Inquiry)), db.scalar(select(func.count()).select_from(LineItem)),
             db.execute(text("SELECT count(*) FROM core.event")).scalar())
    assert after == before


def test_line_item_needs_an_owner_in_database(db):
    with pytest.raises(DBAPIError) as info:
        db.execute(text("INSERT INTO ops.line_item (name) VALUES ('x')"))
    assert isinstance(info.value.orig, psycopg.errors.CheckViolation)
    db.rollback()


def test_case_party_and_received_at_defaults(client, db):
    inq = inquiry(client, response_due_on=(date.today() + timedelta(days=3)).isoformat())
    assert inq["received_at"] and inq["status"] == "new"
    decide(client, inq["id"])
    assert client.get(f"/api/inquiries/{inq['id']}").json()["status"] == "ready_for_screening"
    case = client.post(f"/api/inquiries/{inq['id']}/convert", json={}).json()
    assert case["title"] == inq["subject"]
    assert db.get(Case, case["id"]) is not None
