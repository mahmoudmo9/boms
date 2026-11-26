"""v0.10.1 section 0.4: the owner's findings from using v0.10.0 on Windows."""
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
