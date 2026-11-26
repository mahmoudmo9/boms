"""v0.10.1 section 0.4: the owner's findings from using v0.10.0 on Windows."""
import uuid

from sqlalchemy import text

from tests.test_parties import make_party, tag
from tests.test_v090_m4 import ai, fields, run_draft  # noqa: F401


# ---- 0.4.1 AI drafting: the chosen draft reaches the e-mail; the owner instructs the AI ------------------------------

def _rfq(client):
    from tests.test_sourcing_rfq import make_case, new_rfq, supplier

    case, items = make_case(client, [{"name": "Valve", "quantity": "2"}])
    sup = supplier(client)
    client.post("/api/contacts", json={"party_id": sup["id"], "name_en": "Wang Lei",
                                       "methods": [{"type": "email", "value": f"w{tag()}@valves.example"}]})
    body = new_rfq(client, case, items, [{"party_id": sup["id"], "channel": "email"}])
    return body, body["recipients"][0]["id"]


def _recipient(client, rfq_id):
    return client.get(f"/api/rfqs/{rfq_id}").json()["recipients"][0]


def _draft(client, db, ai, target_id, answer, target_type="rfq_recipient", **extra):  # noqa: F811
    ai.answers.append(answer)
    r = client.post("/api/ai/draft-message", json={"target_type": target_type, "target_id": target_id, **extra})
    assert r.status_code == 202, r.text
    run_draft(db, r.json())
    return r.json()["id"]


def test_choosing_a_draft_fills_subject_with_code_body_and_mailto(client, db, ai):  # noqa: F811
    rfq, rec_id = _rfq(client)
    assert _recipient(client, rfq["id"])["text_edited"] is False          # the template's own text
    draft_id = _draft(client, db, ai, rec_id, {"subject": "Request for Quotation – Valve", "body": "Dear Sir, please quote 2 valves.",
                                               "back_translation_fa": "لطفاً قیمت بدهید."})
    r = client.post(f"/api/ai/drafts/{draft_id}/choose", json={"mode": "replace"})
    assert r.status_code == 200, r.text
    rec = _recipient(client, rfq["id"])
    assert rec["subject"] == f"[{rfq['code']}] Request for Quotation – Valve"           # the code prefix is kept
    assert rec["message_text"] == "Dear Sir, please quote 2 valves."
    assert "please%20quote%202%20valves" in rec["mailto"] and rfq["code"] in rec["mailto"]
    assert r.json()["result"]["recipient"]["message_text"] == rec["message_text"]          # the editor gets it at once
    assert rec["text_edited"] is True                                                      # the next draft asks


def test_a_model_echoing_a_code_does_not_double_it(client, db, ai):  # noqa: F811
    rfq, rec_id = _rfq(client)
    draft_id = _draft(client, db, ai, rec_id, {"subject": "[RFQ-1405-9999] Quotation request", "body": "Hello",
                                               "back_translation_fa": "سلام"})
    client.post(f"/api/ai/drafts/{draft_id}/choose", json={"mode": "replace"})
    assert _recipient(client, rfq["id"])["subject"] == f"[{rfq['code']}] Quotation request"


def test_append_keeps_the_owners_text_and_subject(client, db, ai):  # noqa: F811
    rfq, rec_id = _rfq(client)
    client.patch(f"/api/rfqs/recipients/{rec_id}", json={"subject": f"[{rfq['code']}] My subject", "message_text": "My own text."})
    assert _recipient(client, rfq["id"])["text_edited"] is True
    draft_id = _draft(client, db, ai, rec_id, {"subject": "AI subject", "body": "Please add MOQ and lead time.",
                                               "back_translation_fa": "حداقل سفارش"})
    client.post(f"/api/ai/drafts/{draft_id}/choose", json={"mode": "append"})
    rec = _recipient(client, rfq["id"])
    assert rec["message_text"] == "My own text.\n\nPlease add MOQ and lead time."
    assert rec["subject"] == f"[{rfq['code']}] My subject"


def test_instruction_reaches_the_model_is_logged_and_regenerate_keeps_earlier_drafts(client, db, ai):  # noqa: F811
    rfq, rec_id = _rfq(client)
    answer = {"subject": "RFQ", "body": "Short formal text.", "back_translation_fa": "متن"}
    first = _draft(client, db, ai, rec_id, answer, instruction="رسمی‌تر و کوتاه، زمان تحویل و MOQ را هم بپرس")
    prompt = ai.bodies[-1]["messages"][1]["content"]
    assert "Owner's instruction: رسمی‌تر و کوتاه، زمان تحویل و MOQ را هم بپرس" in prompt
    logged = db.execute(text("SELECT c.input FROM ai.call c JOIN ai.draft d ON d.created_by_call_id = c.id WHERE d.id = :d"),
                        {"d": first}).scalar()
    assert logged["instruction"] == "رسمی‌تر و کوتاه، زمان تحویل و MOQ را هم بپرس"
    second = _draft(client, db, ai, rec_id, {**answer, "body": "Another text."})               # «ساخت دوباره»
    assert "Owner's instruction: none" in ai.bodies[-1]["messages"][1]["content"]                 # no instruction: the default
    listed = {d["id"]: d["status"] for d in client.get("/api/ai/drafts", params={"target_type": "rfq_recipient", "target_id": rec_id}).json()}
    assert listed == {first: "ready", second: "ready"}                                            # both still selectable
    assert client.get(f"/api/ai/drafts/{first}").json()["payload"]["instruction"].startswith("رسمی‌تر")
    client.post(f"/api/ai/drafts/{first}/choose", json={"mode": "replace"})                       # the earlier one is chosen
    assert _recipient(client, rfq["id"])["message_text"] == "Short formal text."


def test_instruction_is_bounded(client, db, ai):  # noqa: F811
    _rfq_body, rec_id = _rfq(client)
    r = client.post("/api/ai/draft-message", json={"target_type": "rfq_recipient", "target_id": rec_id, "instruction": "x" * 1001})
    assert r.status_code == 422


def test_quote_cover_and_inquiry_reply_are_drafts_for_the_mail_client(client, db, ai):  # noqa: F811
    from tests.test_quotes import sent_quote
    from tests.test_sourcing_inquiries import inquiry

    *_rest, quote = sent_quote(client)
    draft_id = _draft(client, db, ai, quote["id"], {"subject": "Proforma", "body": "Please find our proforma.", "back_translation_fa": "پیش‌فاکتور"},
                      target_type="quote", instruction="دوستانه")
    assert quote["number"] in ai.bodies[-1]["messages"][1]["content"]
    r = client.post(f"/api/ai/drafts/{draft_id}/choose", json={"mode": "replace"})
    assert r.status_code == 200 and r.json()["result"]["mailto"].startswith("mailto:?subject=Proforma")
    buyer = make_party(client, name_en=f"Buyer {tag()}", roles=["buyer"])
    inq = inquiry(client, [{"name": "Pump", "quantity": "3"}], party_id=buyer["id"])
    draft_id = _draft(client, db, ai, inq["id"], {"subject": "Your inquiry", "body": "Thank you, we will quote.", "back_translation_fa": "سپاس"},
                      target_type="inquiry_reply")
    assert "Pump: 3" in ai.bodies[-1]["messages"][1]["content"]
    assert client.post(f"/api/ai/drafts/{draft_id}/choose", json={}).json()["result"]["body"] == "Thank you, we will quote."
    # an extraction draft for the same inquiry still commits items (its committer is not replaced)
    from app.modules.ai.drafts import COMMITTERS
    from app.modules.ai.builtin import commit_items
    assert COMMITTERS["inquiry"] is commit_items


# ---- 0.4.2 roles manufacturer and carrier, supplier type -------------------------------------------------------------

def test_manufacturer_is_on_the_supplier_side_and_keeps_a_sup_code(client):
    from tests.test_sourcing_rfq import make_case

    m = make_party(client, name_en=f"Factory {tag()}", roles=["manufacturer"], country_iso2="CN", supplier_type="manufacturer")
    assert m["code"].startswith("SUP-CN-") and m["supplier_type"] == "manufacturer"
    assert [(r["role"], r["stage"]) for r in m["roles"]] == [("manufacturer", "identified")]   # the supplier stages
    both = make_party(client, name_en=f"Trader {tag()}", roles=["supplier", "manufacturer"], country_iso2="TR")
    assert both["code"].startswith("SUP-TR-")
    found = client.get("/api/rfqs/suppliers", params={"q": m["name_en"]}).json()                 # RFQ selection
    assert [(s["party_id"], s["supplier_type"], s["supplier_stage"]) for s in found] == [(m["id"], "manufacturer", "identified")]
    case, items = make_case(client, [{"name": "Valve", "quantity": "1"}])
    r = client.post("/api/rfqs", json={"case_id": case["id"], "items": [{"line_item_id": items[0]["id"]}],
                                       "recipients": [{"party_id": m["id"]}]})
    assert r.status_code == 201, r.text


def test_carrier_has_its_own_stages_and_a_bp_code(client):
    c = make_party(client, name_en=f"Caspian Lines {tag()}", roles=["carrier"], country_iso2="IR",
                   tracking_url_template="https://track.example/?bl={number}")
    assert c["code"].startswith("BP-IR-") and [(r["role"], r["stage"]) for r in c["roles"]] == [("carrier", "active")]
    stages = {s["code"] for s in client.get("/api/parties/stages", params={"role": "carrier"}).json()}
    assert stages == {"active", "dormant"}
    assert client.post(f"/api/parties/{c['id']}/roles/carrier/stage", json={"stage": "dormant"}).status_code == 200
    assert client.post(f"/api/parties/{c['id']}/roles/carrier/stage", json={"stage": "won"}).status_code == 422


def test_supplier_type_is_checked_and_patchable(client):
    p = make_party(client, name_en=f"Dist {tag()}", roles=["supplier"])
    assert p["supplier_type"] is None
    assert client.patch(f"/api/parties/{p['id']}", json={"supplier_type": "distributor"}).json()["supplier_type"] == "distributor"
    assert client.patch(f"/api/parties/{p['id']}", json={"supplier_type": "wholesaler"}).status_code == 422


def test_migration_0024_keeps_roles_on_downgrade_and_back():
    from alembic import command
    from sqlalchemy import create_engine

    from app.cli import alembic_config
    from app.core import dbadmin
    from app.core.config import get_config
    from tests.conftest import create_empty_database, superuser_conninfo

    name = "boms_test_mig_0024"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    try:
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        with engine.begin() as conn:
            ids = [conn.execute(text("INSERT INTO core.party (name_en, supplier_type) VALUES (:n, 'manufacturer') RETURNING id"),
                                {"n": n}).scalar() for n in ("Factory", "Lines", "Both")]
            for pid, role, stage in ((ids[0], "manufacturer", "qualified"), (ids[1], "carrier", "dormant"),
                                     (ids[2], "supplier", "in_use"), (ids[2], "manufacturer", "contacted")):
                conn.execute(text("INSERT INTO core.party_role (party_id, role, stage) VALUES (:p, :r, :s)"), {"p": pid, "r": role, "s": stage})
        command.downgrade(cfg, "0023")
        with engine.connect() as conn:
            roles = sorted(conn.execute(text("SELECT p.name_en, r.role, r.stage FROM core.party_role r JOIN core.party p ON p.id = r.party_id")).all())
        assert roles == [("Both", "supplier", "in_use"), ("Factory", "supplier", "qualified"), ("Lines", "other", "dormant")]
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM core.funnel_stage WHERE role IN ('manufacturer', 'carrier')")).scalar() == 9
            assert conn.execute(text("SELECT count(*) FROM core.party WHERE name_en = 'Factory'")).scalar() == 1
        engine.dispose()
    finally:
        dbadmin.drop_database(superuser_conninfo(), name)


# ---- 0.4.3 automatic roles and stages ---------------------------------------------------------------------------------

def _roles(client, party_id):
    return {r["role"]: (r["stage"], r["stage_set_by"]) for r in client.get(f"/api/parties/{party_id}").json()["roles"]}


def _auto(client, party_id):
    return client.get(f"/api/parties/{party_id}/automatic-changes").json()["changes"]


def _rules_on(client, **flags):
    client.patch("/api/settings", json={f"parties.rules.{k}": v for k, v in flags.items()})


def test_an_inquiry_adds_the_buyer_role_and_moves_its_stage_with_a_cause(client):
    from tests.test_sourcing_inquiries import inquiry

    _rules_on(client, roles=True, buyer_inquiry=True)
    p = make_party(client, name_en=f"New buyer {tag()}")                       # no role yet
    inq = inquiry(client, party_id=p["id"])
    assert _roles(client, p["id"])["buyer"] == ("inquiry_received", "auto")
    changes = _auto(client, p["id"])
    assert [c["action"] for c in changes] == ["stage_auto", "role_auto"]
    assert changes[0]["cause"] == {"entity": "inquiry", "id": inq["id"], "code": inq["code"], "kind": "inquiry"}
    assert changes[0]["old_stage"] == "new_lead" and changes[0]["revertible"] is True


def test_stages_move_forward_only_and_never_out_of_terminal_or_manual(client):
    from tests.test_sourcing_inquiries import inquiry

    _rules_on(client, roles=True, buyer_inquiry=True, buyer_contacted=True, buyer_in_conversation=True)
    p = make_party(client, name_en=f"Forward {tag()}", roles=["buyer"])
    inquiry(client, party_id=p["id"])                                           # -> inquiry_received
    client.post("/api/interactions", json={"party_id": p["id"], "channel": "email", "direction": "out", "body": "Hello", "no_followup_reason": "test"})
    assert _roles(client, p["id"])["buyer"][0] == "inquiry_received"           # not back to «contacted»
    manual = make_party(client, name_en=f"Manual {tag()}", roles=["buyer"])
    client.post(f"/api/parties/{manual['id']}/roles/buyer/stage", json={"stage": "contacted"})
    inquiry(client, party_id=manual["id"])
    assert _roles(client, manual["id"])["buyer"] == ("contacted", "manual")    # the owner's stage stays
    lost = make_party(client, name_en=f"Lost {tag()}", roles=["supplier"])
    client.post(f"/api/parties/{lost['id']}/roles/supplier/stage", json={"stage": "blacklisted", "reason": "fraud"})
    from app.modules.parties.models import PartyRole  # noqa: F401  (the row is terminal and manual)
    from tests.test_sourcing_rfq import make_case, offer_body
    case, items = make_case(client, [{"name": "Pump", "quantity": "1"}])
    client.post("/api/offers", json=offer_body(case, lost, [{"line_item_id": items[0]["id"], "unit_price": "10"}]))
    assert _roles(client, lost["id"])["supplier"][0] == "blacklisted"


def test_supplier_side_rules_and_the_switch_per_rule(client):
    from tests.test_sourcing_rfq import make_case, new_rfq, offer_body

    _rules_on(client, roles=True, supplier_contacted=True, supplier_responded=False)
    m = make_party(client, name_en=f"Factory {tag()}", roles=["manufacturer"], supplier_type="manufacturer")
    case, items = make_case(client, [{"name": "Valve", "quantity": "2"}])
    rfq = new_rfq(client, case, items, [{"party_id": m["id"]}])
    client.post(f"/api/rfqs/recipients/{rfq['recipients'][0]['id']}/mark-sent", json={"no_followup_reason": "test"})
    roles = _roles(client, m["id"])
    assert roles == {"manufacturer": ("contacted", "auto")}                     # no extra «supplier» role on a factory
    client.post("/api/offers", json=offer_body(case, m, [{"line_item_id": items[0]["id"], "unit_price": "10"}]))
    assert _roles(client, m["id"])["manufacturer"][0] == "contacted"           # the rule is switched off
    _rules_on(client, supplier_responded=True)
    client.post("/api/offers", json=offer_body(case, m, [{"line_item_id": items[0]["id"], "unit_price": "9"}]))
    assert _roles(client, m["id"])["manufacturer"][0] == "responded"
    fresh = make_party(client, name_en=f"Unknown {tag()}")                      # used as a supplier: gets the role
    client.post("/api/offers", json=offer_body(case, fresh, [{"line_item_id": items[0]["id"], "unit_price": "8"}]))
    assert _roles(client, fresh["id"])["supplier"] == ("responded", "auto")


def test_revert_restores_the_stage_once_and_counts_as_the_owners(client):
    from tests.test_sourcing_inquiries import inquiry

    _rules_on(client, roles=True, buyer_inquiry=True)
    p = make_party(client, name_en=f"Revert {tag()}", roles=["buyer"])
    inquiry(client, party_id=p["id"])
    stage_event = _auto(client, p["id"])[0]
    r = client.post(f"/api/parties/{p['id']}/automatic-changes/{stage_event['event_id']}/revert")
    assert r.status_code == 200, r.text
    assert _roles(client, p["id"])["buyer"] == ("new_lead", "manual")
    assert client.post(f"/api/parties/{p['id']}/automatic-changes/{stage_event['event_id']}/revert").status_code == 409
    inquiry(client, party_id=p["id"])                                           # the rule does not redo it
    assert _roles(client, p["id"])["buyer"][0] == "new_lead"
    q = make_party(client, name_en=f"Role revert {tag()}")
    inquiry(client, party_id=q["id"])
    role_event = next(c for c in _auto(client, q["id"]) if c["action"] == "role_auto")
    stage = next(c for c in _auto(client, q["id"]) if c["action"] == "stage_auto")
    client.post(f"/api/parties/{q['id']}/automatic-changes/{stage['event_id']}/revert")
    assert client.post(f"/api/parties/{q['id']}/automatic-changes/{role_event['event_id']}/revert").status_code == 200
    assert "buyer" not in _roles(client, q["id"])


def test_dormant_job_and_the_next_activity_moves_it_back(client, db):
    from datetime import timedelta

    from app.modules.parties import clock, rules
    from tests.test_sourcing_inquiries import inquiry

    _rules_on(client, roles=True, buyer_inquiry=True, dormant=True, buyer_contacted=True)
    client.patch("/api/settings", json={"parties.dormant_days": 30})
    p = make_party(client, name_en=f"Sleepy {tag()}", roles=["buyer"])
    inquiry(client, party_id=p["id"])
    changes = rules.make_dormant(db, now=clock.now() + timedelta(days=31), party_ids={uuid.UUID(p["id"])})
    db.commit()
    assert any(c.party_id == uuid.UUID(p["id"]) for c in changes)
    assert _roles(client, p["id"])["buyer"] == ("dormant", "auto")
    client.post("/api/interactions", json={"party_id": p["id"], "channel": "email", "direction": "out", "body": "Back", "no_followup_reason": "test"})
    assert _roles(client, p["id"])["buyer"][0] == "inquiry_received"           # back where it was (not «contacted»)
    client.patch("/api/settings", json={"parties.dormant_days": 180})


def test_recompute_preview_changes_nothing_until_confirmed(client, db):
    from tests.test_sourcing_inquiries import inquiry

    _rules_on(client, roles=False, buyer_inquiry=False)                       # history made with the rules off
    p = make_party(client, name_en=f"History {tag()}")
    inquiry(client, party_id=p["id"])
    assert _roles(client, p["id"]) == {}
    _rules_on(client, roles=True, buyer_inquiry=True)
    preview = client.get("/api/parties/rules/recompute").json()
    mine = [x for x in preview["proposed"] if x["party_id"] == p["id"]]
    assert mine == [{"party_id": p["id"], "party_name_fa": None, "party_name_en": p["name_en"], "role": "buyer", "from": None,
                     "to": "inquiry_received", "added": True, "cause": mine[0]["cause"]}]
    assert mine[0]["cause"]["kind"] == "inquiry"
    assert _roles(client, p["id"]) == {}                                        # the preview changed nothing
    out = client.post("/api/parties/rules/recompute").json()
    assert out["confirmed"] is True and out["applied"] >= 1
    assert _roles(client, p["id"])["buyer"] == ("inquiry_received", "auto")
    assert {c["action"] for c in _auto(client, p["id"])} == {"role_auto", "stage_auto"}


def test_carrier_and_forwarder_of_a_shipment_get_their_role(client):
    lines = make_party(client, name_en=f"Lines {tag()}")
    fwd = make_party(client, name_en=f"Fwd {tag()}")
    _rules_on(client, roles=True)
    case = client.post("/api/cases", json={"title": f"Ship {tag()}"}).json()
    r = client.post("/api/shipments", json={"case_id": case["id"], "mode": "sea", "carrier_party_id": lines["id"],
                                            "forwarder_party_id": fwd["id"]})
    assert r.status_code == 201, r.text
    assert _roles(client, lines["id"]) == {"carrier": ("active", "initial")}
    assert _roles(client, fwd["id"]) == {"forwarder": ("active", "initial")}


def test_lost_is_suggested_when_every_quote_was_rejected(client):
    from tests.test_quotes import sent_quote

    case, items, party, _sheet, quote = sent_quote(client)
    assert client.get(f"/api/parties/{party['id']}/automatic-changes").json()["suggest_lost"] is None
    reason = client.get("/api/quotes/outcome-reasons").json()[0]["code"]
    r = client.put(f"/api/quotes/{quote['id']}/outcomes", json={"items": [{"quote_item_id": i["id"], "outcome": "rejected", "outcome_reason": reason}
                                                                          for i in quote["items"]]})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/parties/{party['id']}/automatic-changes").json()["suggest_lost"] == {"quotes": 1}


# ---- 0.4.6 case correspondence, .eml intake, reply and chase ----------------------------------------------------------

def _eml(subject="[X] Re: RFQ", sender="Wang Lei <wang@valves.example>", body="We will quote next week.", html=None,
         attachments=(), charset="utf-8"):
    from email.message import EmailMessage
    from email.utils import format_datetime
    from datetime import datetime, timezone

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Cc"] = sender, "owner@trading.example", "boss@valves.example"
    msg["Subject"] = subject
    msg["Date"] = format_datetime(datetime(2026, 11, 20, 9, 30, tzinfo=timezone.utc))
    if html and body is None:
        msg.set_content(html, subtype="html", charset=charset)
    else:
        msg.set_content(body, charset=charset)
        if html:
            msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


def _upload(client, data, name="reply.eml"):
    r = client.post("/api/documents", files={"file": (name, data + f"\n{tag()}".encode() if name.endswith(".eml") else data, "message/rfc822")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_eml_parse_plain_html_attachments_and_encoded_headers():
    from app.modules.parties import eml

    p = eml.parse(_eml(subject="[RFQ-1405-0012] پاسخ استعلام شیر", attachments=[("offer.pdf", b"%PDF-1.4 x", "application/pdf")]))
    assert p["subject"] == "[RFQ-1405-0012] پاسخ استعلام شیر" and p["codes"] == ["RFQ-1405-0012"]
    assert p["from_address"] == "wang@valves.example" and p["from_name"] == "Wang Lei"
    assert p["to"] == ["owner@trading.example"] and p["cc"] == ["boss@valves.example"]
    assert p["body"] == "We will quote next week." and p["body_kind"] == "plain"
    assert [(a["filename"], a["size"]) for a in p["attachments"]] == [("offer.pdf", 10)]
    assert p["date"].isoformat() == "2026-11-20T09:30:00+00:00"
    only_html = eml.parse(_eml(body=None, html="<html><head><style>x{}</style></head><body><p>Dear Sir,</p><p>Price: <b>1&nbsp;200</b> USD</p></body></html>"))
    assert only_html["body_kind"] == "html" and only_html["body"] == "Dear Sir,\n\nPrice: 1 200 USD"
    both = eml.parse(_eml(body="plain wins", html="<p>html</p>"))
    assert both["body"] == "plain wins"                                              # plain text preferred
    # windows-1256 has the Persian پ گ but not «ی» or Persian digits: the Arabic yeh, Latin digits
    arabic = eml.parse(_eml(subject="پاسخ قيمت گرد", body="قيمت 1200 دلار", charset="windows-1256"))
    assert arabic["subject"] == "پاسخ قيمت گرد" and arabic["body"] == "قيمت 1200 دلار"   # another charset


def test_msg_and_non_mail_are_refused():
    import pytest

    from app.core.errors import AppError
    from app.modules.parties import eml

    with pytest.raises(AppError) as e:
        eml.parse(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "reply.msg")
    assert e.value.code == "msg_not_supported" and "Download message" in e.value.details["gmail"]
    with pytest.raises(AppError) as e:
        eml.parse(b"just text", "note.eml")
    assert e.value.code == "not_an_email"


def _sent_rfq(client):
    from tests.test_sourcing_rfq import make_case, new_rfq, supplier

    case, items = make_case(client, [{"name": "Valve", "quantity": "2"}])
    sup = supplier(client)
    address = f"w{tag()}@valves.example"
    person = client.post("/api/contacts", json={"party_id": sup["id"], "name_en": "Wang Lei", "methods": [{"type": "email", "value": address}]}).json()
    rfq = new_rfq(client, case, items, [{"party_id": sup["id"], "channel": "email", "contact_id": person["id"]}])
    rec = rfq["recipients"][0]
    client.post(f"/api/rfqs/recipients/{rec['id']}/mark-sent", json={"followup": {"action": "Chase RFQ response", "due_on": "2099-01-05"}})
    return case, items, sup, person, address, rfq, rec


def _open_chases(client, party_id):
    return [f for f in client.get("/api/followups", params={"party_id": party_id, "status": "open"}).json()["items"]]


def test_eml_preview_matches_code_and_sender_and_records_on_the_case(client):
    case, _items, sup, person, address, rfq, rec = _sent_rfq(client)
    doc = _upload(client, _eml(subject=f"Re: [{rfq['code']}] Request for Quotation", sender=f"Wang Lei <{address}>",
                               attachments=[("price.pdf", b"%PDF-1.4 " + tag().encode(), "application/pdf")]))
    pre = client.post("/api/interactions/eml/preview", json={"document_id": doc}).json()
    m = pre["match"]
    assert (m["case_id"], m["ref_type"], m["ref_id"], m["party_id"], m["contact_id"], m["known_sender"]) == (
        case["id"], "rfq_recipient", rec["id"], sup["id"], person["id"], True)
    assert [a["filename"] for a in pre["attachments"]] == ["price.pdf"]
    r = client.post("/api/interactions/eml", json={"document_id": doc, "party_id": sup["id"], "contact_id": person["id"],
                                                   "case_id": m["case_id"], "ref_type": m["ref_type"], "ref_id": m["ref_id"],
                                                   "no_followup_reason": "offer follows"})
    assert r.status_code == 201, r.text
    thread = client.get(f"/api/interactions/case/{case['id']}").json()
    mine = next(i for i in thread["items"] if i["id"] == r.json()["interaction"]["id"])
    assert mine["direction"] == "in" and mine["ref_code"] == rfq["code"] and mine["raw_document_id"] == doc
    assert {f["role"] for f in mine["files"]} == {"source", "attachment"}            # the .eml and its attachment
    assert any(i["direction"] == "out" and i["ref_type"] == "rfq_recipient" for i in thread["items"])   # the RFQ itself
    assert [p["id"] for p in thread["parties"]] == [sup["id"]]


def test_unknown_sender_is_added_to_the_party_contacts(client):
    case, _items, sup, _person, _address, rfq, _rec = _sent_rfq(client)
    stranger = f"sales{tag()}@valves.example"
    doc = _upload(client, _eml(subject=f"[{rfq['code']}] question", sender=f"Li Na <{stranger}>"))
    pre = client.post("/api/interactions/eml/preview", json={"document_id": doc}).json()
    assert pre["match"]["known_sender"] is False and pre["match"]["case_id"] == case["id"]
    r = client.post("/api/interactions/eml", json={"document_id": doc, "party_id": sup["id"], "add_contact": True,
                                                   "case_id": case["id"], "no_followup_reason": "noted"})
    assert r.status_code == 201, r.text
    contacts = client.get(f"/api/parties/{sup['id']}").json()["contacts"]
    added = next(c for c in contacts if c["id"] == r.json()["contact_id"])
    assert added["name_en"] == "Li Na" and added["methods"][0]["value"] == stranger
    assert client.post("/api/interactions/eml/preview", json={"document_id": doc}).json()["match"]["known_sender"] is True


def test_msg_upload_is_refused_with_the_steps(client):
    doc = _upload(client, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + tag().encode() + b"\0" * 600, "reply.msg")
    r = client.post("/api/interactions/eml/preview", json={"document_id": doc})
    assert r.status_code == 415 and r.json()["error"]["code"] == "msg_not_supported"


def test_reply_without_price_closes_the_chase_and_sets_the_status(client):
    case, _items, sup, _person, _address, _rfq, rec = _sent_rfq(client)
    assert len(_open_chases(client, sup["id"])) == 1
    r = client.post(f"/api/rfqs/recipients/{rec['id']}/reply", json={"kind": "question", "body": "Which material?", "next_due_on": "2099-02-01"})
    assert r.status_code == 200, r.text
    assert r.json()["recipient"]["status"] == "question" and len(r.json()["closed_followups"]) == 1
    open_now = _open_chases(client, sup["id"])
    assert [f["due_on"] for f in open_now] == ["2099-02-01"]                         # a question: a new due date
    r = client.post(f"/api/rfqs/recipients/{rec['id']}/reply", json={"kind": "declined", "body": "No stock."})
    assert r.json()["recipient"]["status"] == "declined" and _open_chases(client, sup["id"]) == []   # a decline: none
    thread = client.get(f"/api/interactions/case/{case['id']}").json()["items"]
    assert [i["excerpt"] for i in thread if i["direction"] == "in"] == ["No stock.", "Which material?"]


def test_an_offer_closes_the_open_chase(client):
    from tests.test_sourcing_rfq import offer_body

    case, items, sup, _person, _address, _rfq, rec = _sent_rfq(client)
    client.post("/api/offers", json=offer_body(case, sup, [{"line_item_id": items[0]["id"], "unit_price": "10"}], rfq_recipient_id=rec["id"]))
    assert _open_chases(client, sup["id"]) == []


def test_chase_records_the_interaction_reschedules_and_counts(client):
    case, _items, sup, _person, _address, _rfq, rec = _sent_rfq(client)
    r = client.post(f"/api/rfqs/recipients/{rec['id']}/chase", json={"subject": "Reminder", "body": "Any news?", "next_due_on": "2099-01-20"})
    assert r.status_code == 200, r.text
    assert r.json()["recipient"]["chase_count"] == 1 and r.json()["recipient"]["last_chased_at"]
    assert [f["due_on"] for f in _open_chases(client, sup["id"])] == ["2099-01-20"]  # rescheduled, not added
    client.post(f"/api/rfqs/recipients/{rec['id']}/chase", json={"body": "Again", "next_due_on": "2099-01-27"})
    assert _recipient(client, _rfq["id"])["chase_count"] == 2
    outs = [i for i in client.get(f"/api/interactions/case/{case['id']}").json()["items"] if i["direction"] == "out"]
    assert [i["excerpt"] for i in outs][:2] == ["Again", "Any news?"]


def test_quote_chase_is_recorded_on_the_case(client):
    from tests.test_quotes import sent_quote

    case, _items, party, _sheet, quote = sent_quote(client)
    r = client.post(f"/api/quotes/{quote['id']}/chase", json={"body": "Did you review our proforma?", "next_due_on": "2099-03-01"})
    assert r.status_code == 200, r.text
    items = client.get(f"/api/interactions/case/{case['id']}").json()["items"]
    assert items[0]["ref_type"] == "quote" and items[0]["ref_code"] == quote["number"] and items[0]["direction"] == "out"


def test_ai_chase_draft_knows_what_was_sent(client, db, ai):  # noqa: F811
    _case, _items, _sup, _person, address, rfq, rec = _sent_rfq(client)
    draft_id = _draft(client, db, ai, rec["id"], {"subject": "Reminder", "body": "Kindly reply.", "back_translation_fa": "لطفاً پاسخ دهید"},
                      target_type="rfq_chase", instruction="کوتاه")
    prompt = ai.bodies[-1]["messages"][1]["content"]
    assert "Sent on" in prompt and "Chases sent before: 0" in prompt and "Owner's instruction: کوتاه" in prompt
    out = client.post(f"/api/ai/drafts/{draft_id}/choose", json={}).json()["result"]
    assert out["subject"] == f"[{rfq['code']}] Reminder" and out["mailto"].startswith(f"mailto:{address}?")


def test_migration_0026_backfills_the_case_of_interactions():
    from alembic import command
    from sqlalchemy import create_engine

    from app.cli import alembic_config
    from app.core import dbadmin
    from app.core.config import get_config
    from tests.conftest import create_empty_database, superuser_conninfo

    name = "boms_test_mig_0026"
    create_empty_database(name)
    url = get_config().db_url(name)
    cfg = alembic_config(url)
    try:
        command.upgrade(cfg, "0025")
        engine = create_engine(url)
        with engine.begin() as conn:
            q = lambda sql, **p: conn.execute(text(sql), p).scalar()   # noqa: E731
            party = q("INSERT INTO core.party (name_en) VALUES ('S') RETURNING id")
            case = q("INSERT INTO ops.case (title) VALUES ('C') RETURNING id")
            i1 = q("INSERT INTO core.interaction (party_id, channel, direction, occurred_at, no_followup_reason) VALUES (:p, 'email', 'out', now(), 'x') RETURNING id", p=party)
            i2 = q("INSERT INTO core.interaction (party_id, channel, direction, occurred_at, no_followup_reason) VALUES (:p, 'email', 'in', now(), 'x') RETURNING id", p=party)
            rfq = q("INSERT INTO ops.rfq (case_id, title) VALUES (:c, 'R') RETURNING id", c=case)
            rec = q("INSERT INTO ops.rfq_recipient (rfq_id, party_id, channel, language, status, sent_at, interaction_id) "
                    "VALUES (:r, :p, 'email', 'en', 'sent', now(), :i) RETURNING id", r=rfq, p=party, i=i1)
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            rows = {r.id: (r.case_id, r.ref_type, r.ref_id) for r in conn.execute(text("SELECT id, case_id, ref_type, ref_id FROM core.interaction"))}
        assert rows[i1] == (case, "rfq_recipient", rec) and rows[i2] == (None, None, None)
        command.downgrade(cfg, "0025")
        command.upgrade(cfg, "head")
        engine.dispose()
    finally:
        dbadmin.drop_database(superuser_conninfo(), name)


def test_a_malformed_compound_file_is_not_a_500(client, tmp_path):
    """v0.10.1: the Windows Installer check read a garbage sector shift and crashed the upload (a broken .msg/.doc)."""
    from app.modules.documents.filetypes import _is_msi

    bad = tmp_path / "x.msg"
    bad.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\xff" * 600)
    assert _is_msi(bad) is False
    r = client.post("/api/documents", files={"file": (f"broken{tag()}.msg", bad.read_bytes() + tag().encode(), "application/vnd.ms-outlook")})
    assert r.status_code == 201, r.text


def test_party_timeline_has_the_correspondence_not_the_closed_chase(client):
    _case, _items, sup, _person, _address, _rfq, rec = _sent_rfq(client)
    client.post(f"/api/rfqs/recipients/{rec['id']}/reply", json={"kind": "replied", "body": "We are checking", "subject": "Re: prices"})
    kinds = [(t["kind"], t["ref"]) for t in client.get(f"/api/parties/{sup['id']}/scorecard").json()["story"]["timeline"]]
    assert ("mail_in", "Re: prices") in kinds
    assert not any(k == "followup_done" for k, _ in kinds)                     # the chase BOMS closed is not repeated
    assert not any(k == "mail_out" for k, _ in kinds)                          # the RFQ itself is on the line as «rfq_sent»
