"""v0.5.0 sections 5-7: convert a Setad listing to an inquiry, the deadline-change banner, the inquiry cascade, the
Setad proforma (template, validity gate, total in words, file name), command center and search."""
import hashlib
import io
import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.connectors.setad.eproc_storage import need_folder, record_attachment_total, record_download
from app.connectors.setad.pipeline import number_words
from app.connectors.setad.rows import SOURCE_PURCHASE, TEHRAN
from app.core.db import new_session
from app.modules.listings.store import ListingStore
from app.modules.quotes.output import total_in_words

from tests.test_listings_store import needs, tag
from tests.test_quotes import new_quote, ready_case
from tests.test_sourcing_inquiries import events

DETAIL_FIELDS = [["مهلت ارسال پاسخ", "1405/08/20 ساعت 14:00"], ["حداقل تاریخ اعتبار قیمت", "1405/09/10 ساعت 11:00"],
                 ["استان محل تحویل", "یزد"], ["شهر محل تحویل", "تفت"], ["تلفن تماس خریدار", "035-31234567"]]


@pytest.fixture
def files_dir(client, tmp_path):
    root = tmp_path / "setad-files"
    root.mkdir()
    assert client.patch("/api/settings", json={"setad.files_dir": str(root)}).status_code == 200
    yield root
    client.patch("/api/settings", json={"setad.files_dir": None})


def make_listing(db, root, *, organization="بیمارستان نمونه", items=None, files=("شرایط.pdf",), download=True,
                 fields=None):
    """A purchase call with a fetched detail page and (optionally) downloaded attachments; returns its id."""
    p = tag()
    store = ListingStore(new_session)
    store.start_run(SOURCE_PURCHASE, "full")
    need = needs(p, 1)[0]
    need = need.__class__(**{**need.as_dict(), "organization": organization})
    store.upsert_needs([need])
    store.save_need_detail(f"{p}0", {"info": {
        "fields": fields if fields is not None else DETAIL_FIELDS, "buyer_note": "پیش فاکتور با مهر و امضا",
        "items": items if items is not None else {
            "headers": ["ردیف", "کد کالا", "نام کالا", "واحد شمارش", "تعداد / مقدار", "تاریخ نیاز"],
            "rows": [["1", "123456", "پمپ سانتریفیوژ", "عدد", "4", "1405/08/25"],
                     ["2", "--", "شیر فلکه برنجی", "عدد", "12", ""]]}},
        "attachments": list(files)})
    if download and files:
        folder = need_folder(root, need.need_no)
        record_attachment_total(folder, len(files))
        manifest: dict = {}
        for i, name in enumerate(files):
            (folder / name).write_bytes(b"%PDF-1.4 " + p.encode() + name.encode())
            record_download(folder, manifest, str(60 + i), name, name)
        store.record_need_files(f"{p}0", folder)
    store.finish_run("done")
    return db.execute(text("SELECT id FROM ext.listing WHERE external_id = :e"), {"e": f"{p}0"}).scalar_one()


def star(client, listing_id):
    assert client.post(f"/api/listings/{listing_id}/screen", json={"action": "star"}).status_code == 200


def convert(client, listing_id, **body):
    return client.post(f"/api/listings/{listing_id}/convert", json=body)


def new_buyer(client, name):
    r = client.post("/api/parties", json={"name_fa": name, "kind": "company", "country_iso2": "IR", "roles": ["buyer"],
                                          "confirm_duplicate": True})
    assert r.status_code == 201, r.text
    return r.json()["party"]


# ---- conversion -----------------------------------------------------------------------------------------------

def test_convert_creates_inquiry_with_buyer_items_files_and_dates(client, db, files_dir):
    org = f"دانشگاه علوم پزشکی {tag()}"
    lid = make_listing(db, files_dir, organization=org, files=("شرایط.pdf", "نقشه.pdf"))
    party = new_buyer(client, org.replace("ی", "ي"))           # Arabic yeh: still the exact normalized match
    r = convert(client, lid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_screened"
    star(client, lid)
    preview = client.get(f"/api/listings/{lid}/convert").json()
    assert preview["buyer"]["match"]["id"] == party["id"]
    assert [i["name"] for i in preview["items"]] == ["پمپ سانتریفیوژ", "شیر فلکه برنجی"]
    assert preview["required_price_validity"] == "2026-12-01" and preview["files"]["downloaded"] == 2
    r = convert(client, lid)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["party_id"] == party["id"] and out["items"] == 2 and out["documents"] == 2
    inquiry = client.get(f"/api/inquiries/{out['inquiry_id']}").json()
    inq = inquiry.get("inquiry", inquiry)
    assert inq["source_channel"] == "setad" and inq["kind"] == "rfq" and inq["listing_id"] == str(lid)
    assert inq["external_no"].startswith("11050") and inq["external_url"].startswith("https://eproc.setadiran.ir")
    assert inq["required_price_validity"] == "2026-12-01"
    assert datetime.fromisoformat(inq["response_due_at"]).astimezone(TEHRAN).isoformat().startswith("2026-11-11T14:00")
    assert inq["response_due_on"] == "2026-11-11"
    assert inq["delivery_province"] == "یزد" and inq["delivery_city"] == "تفت"
    assert "پیش فاکتور با مهر و امضا" in inq["raw_text"]
    rows = db.execute(text("SELECT name, quantity, unit_text, required_by, specs FROM ops.line_item WHERE inquiry_id = :i "
                           "ORDER BY position"), {"i": out["inquiry_id"]}).all()
    assert [(r[0], float(r[1]), r[2]) for r in rows] == [("پمپ سانتریفیوژ", 4.0, "عدد"), ("شیر فلکه برنجی", 12.0, "عدد")]
    assert rows[0][3] == date(2026, 11, 16) and rows[0][4] == [{"key": "کد کالای ستاد", "value": "123456"}]
    assert rows[1][4] in (None, [])                                  # "--" is no code
    # files: copied into the document store, hashed, linked to the inquiry and to the listing file row
    docs = db.execute(text("SELECT d.sha256, d.storage_relpath FROM core.document d JOIN core.document_link k "
                           "ON k.document_id = d.id WHERE k.entity_type = 'inquiry' AND k.entity_id = :i"),
                      {"i": out["inquiry_id"]}).all()
    on_disk = sorted(hashlib.sha256(f.read_bytes()).hexdigest() for f in files_dir.rglob("*.pdf"))
    assert sorted(d[0] for d in docs) == [h for h in on_disk if h in {d[0] for d in docs}] and len(docs) == 2
    linked = db.execute(text("SELECT count(*) FROM ext.listing_file WHERE listing_id = :l AND document_id IS NOT NULL"),
                        {"l": lid}).scalar_one()
    assert linked == 2
    # buyer contact info went to the party notes; the listing shows converted
    notes = client.get(f"/api/parties/{party['id']}").json()
    assert "035-31234567" in (notes.get("party", notes).get("notes") or "")
    detail = client.get(f"/api/listings/{lid}").json()
    assert detail["screening"]["status"] == "converted" and detail["screening"]["inquiry_id"] == out["inquiry_id"]
    origin = client.get(f"/api/listings/by-inquiry/{out['inquiry_id']}").json()
    assert origin["number"] == inq["external_no"] and origin["deadline_change"] is None
    # twice: refused with a link to the inquiry
    r = convert(client, lid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_converted"
    assert r.json()["error"]["details"]["inquiry_id"] == out["inquiry_id"]
    assert [e["action"] for e in events(client, "listing", str(lid), "convert")] == ["convert"]


def test_buyer_suggest_and_create_with_duplicate_warning(client, db, files_dir):
    t = tag()
    org = f"شرکت آب و فاضلاب استان {t}"
    lid = make_listing(db, files_dir, organization=org, files=())
    star(client, lid)
    similar = new_buyer(client, f"شرکت آب و فاضلاب {t}")
    r = convert(client, lid)                                         # no exact match: pick or create
    assert r.status_code == 422 and r.json()["error"]["code"] == "buyer_required"
    assert similar["id"] in [s["id"] for s in r.json()["error"]["details"]["suggestions"]]
    r = convert(client, lid, create_party=True)                      # similar party: the Phase 3 warning
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_party"
    r = convert(client, lid, create_party=True, confirm_duplicate=True)
    assert r.status_code == 201, r.text
    party = client.get(f"/api/parties/{r.json()['party_id']}").json()
    party = party.get("party", party)
    assert party["name_fa"] == org and r.json()["party_id"] != similar["id"]
    # picking an existing party works too (another listing of the same buyer)
    lid2 = make_listing(db, files_dir, organization=f"سازمان {tag()}", files=())
    star(client, lid2)
    r = convert(client, lid2, party_id=similar["id"])
    assert r.status_code == 201 and r.json()["party_id"] == similar["id"]


def test_one_item_fallback_missing_files_and_product_choice(client, db, files_dir):
    org = f"شهرداری {tag()}"
    party = new_buyer(client, org)
    lid = make_listing(db, files_dir, organization=org, items={}, files=("الف.pdf",), download=False)
    star(client, lid)
    preview = client.get(f"/api/listings/{lid}/convert").json()
    assert len(preview["items"]) == 1 and preview["items"][0]["name"].startswith("نیاز")
    assert preview["files"]["downloaded"] == 0 and len(preview["files"]["missing"]) == 1
    r = convert(client, lid)                                         # "Download, then convert"
    assert r.status_code == 409 and r.json()["error"]["code"] == "files_not_downloaded"
    product = client.post("/api/products", json={"name_fa": f"کالای {tag()}", "confirm_duplicate": True}).json()["product"]
    r = convert(client, lid, without_missing_files=True, products={"1": product["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["items"] == 1 and r.json()["documents"] == 0 and r.json()["party_id"] == party["id"]
    pid = db.execute(text("SELECT product_id FROM ops.line_item WHERE inquiry_id = :i"),
                     {"i": r.json()["inquiry_id"]}).scalar_one()
    assert str(pid) == product["id"]


def test_deadline_change_banner_apply_moves_followups(client, db, files_dir):
    org = f"اداره کل {tag()}"
    party = new_buyer(client, org)
    lid = make_listing(db, files_dir, organization=org, files=())
    star(client, lid)
    inquiry_id = convert(client, lid).json()["inquiry_id"]
    # a follow-up planned before the deadline (2026-11-11), and one after it
    before = client.post("/api/followups", json={"party_id": party["id"], "action": "آماده کردن پیش‌فاکتور",
                                                 "due_on": "2026-11-09"}).json()
    after = client.post("/api/followups", json={"party_id": party["id"], "action": "پیگیری نتیجه",
                                                "due_on": "2026-11-20"}).json()
    # a later fetch moves the deadline on Setad by three days
    external_id = db.execute(text("SELECT external_id FROM ext.listing WHERE id = :l"), {"l": lid}).scalar_one()
    ListingStore(new_session).save_need_detail(external_id, {"info": {
        "fields": [["مهلت ارسال پاسخ", "1405/08/23 ساعت 14:00"]] + DETAIL_FIELDS[1:]}, "attachments": []})
    origin = client.get(f"/api/listings/by-inquiry/{inquiry_id}").json()
    change = origin["deadline_change"]
    assert change and datetime.fromisoformat(change["new"]).astimezone(TEHRAN).date() == date(2026, 11, 14)
    # nothing applied silently
    inq = client.get(f"/api/inquiries/{inquiry_id}").json()
    assert inq.get("inquiry", inq)["response_due_on"] == "2026-11-11"
    cc = client.get("/api/command-center").json()["setad"]
    assert inquiry_id in [str(x["inquiry_id"]) for x in cc["deadline_changed"]]
    r = client.post(f"/api/listings/by-inquiry/{inquiry_id}/apply-deadline")
    assert r.status_code == 200, r.text
    assert [m["id"] for m in r.json()["followups_moved"]] == [before["id"]]
    inq = client.get(f"/api/inquiries/{inquiry_id}").json()
    assert inq.get("inquiry", inq)["response_due_on"] == "2026-11-14"
    due = dict(db.execute(text("SELECT id::text, due_on FROM core.followup WHERE id IN (:a, :b)"),
                          {"a": before["id"], "b": after["id"]}).all())
    assert due[before["id"]] == date(2026, 11, 12) and due[after["id"]] == date(2026, 11, 20)
    assert len(events(client, "inquiry", inquiry_id, "deadline_apply")) == 1
    assert client.get(f"/api/listings/by-inquiry/{inquiry_id}").json()["deadline_change"] is None
    r = client.post(f"/api/listings/by-inquiry/{inquiry_id}/apply-deadline")
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_deadline_change"


def test_inquiry_cascade_delete_resets_the_screening(client, db, files_dir):
    org = f"بنیاد {tag()}"
    new_buyer(client, org)
    lid = make_listing(db, files_dir, organization=org, files=("ب.pdf",))
    star(client, lid)
    inquiry_id = convert(client, lid).json()["inquiry_id"]
    subject = client.get(f"/api/inquiries/{inquiry_id}").json()
    subject = subject.get("inquiry", subject)["subject"]
    r = client.request("DELETE", f"/api/inquiries/{inquiry_id}", params={"cascade": "true"},
                       json={"confirm_subject": subject})
    assert r.status_code == 200, r.text
    s = client.get(f"/api/listings/{lid}").json()["screening"]
    assert s["status"] == "reviewing" and s["inquiry_id"] is None
    assert len(events(client, "listing", str(lid), "screen_reset")) == 1
    r = convert(client, lid)                                          # the listing stays and can be converted again
    assert r.status_code == 201, r.text


# ---- Setad proforma ---------------------------------------------------------------------------------------------

def setad_case(client, db, required: date):
    """A ready case (final sheet, offers valid 30 days) whose inquiry came from Setad."""
    case, items, party, sheet = ready_case(client, country="IR")
    inquiry_id = uuid.uuid4()
    db.execute(text("INSERT INTO ops.inquiry (id, party_id, source_channel, kind, received_at, subject, external_no, "
                    "external_url, required_price_validity) VALUES (:id, :p, 'setad', 'rfq', now(), 'Setad test', "
                    ":no, 'https://eproc.setadiran.ir/x', :req)"),
               {"id": inquiry_id, "p": party["id"], "no": f"1105091{tag()[:4]}", "req": required})
    db.execute(text("UPDATE ops.\"case\" SET inquiry_id = :i WHERE id = :c"), {"i": inquiry_id, "c": case["id"]})
    db.commit()
    number = db.execute(text("SELECT external_no FROM ops.inquiry WHERE id = :i"), {"i": inquiry_id}).scalar_one()
    return case, party, number


def test_setad_quote_template_validity_words_and_filename(client, db):
    client.patch("/api/settings", json={"company.national_id": "10320000000", "company.economic_code": "411111111111",
                                        "company.signer_name": {"fa": "علی رضایی", "en": "Ali Rezaei"},
                                        "company.signer_title": {"fa": "مدیرعامل", "en": "CEO"}})
    case, party, number = setad_case(client, db, date.today() + timedelta(days=60))
    limit = date.fromisoformat(new_quote(client, case)["approval"]["max_valid_until"])  # what offers / FX allow
    required = limit - timedelta(days=1)
    db.execute(text("UPDATE ops.inquiry SET required_price_validity = :r WHERE external_no = :n"),
               {"r": required, "n": number})
    db.commit()
    quote = new_quote(client, case)
    assert quote["language"] == "fa" and quote["valid_until"] == required.isoformat()   # defaults to the required one
    assert quote["setad"]["setad_number"] == number
    terms = quote["terms_text"]
    assert "مدیریت محترم امور تدارکات" in terms and "طبق شرایط اعلامی خریدار در سامانه ستاد" in terms
    assert "بر عهده فروشنده" in terms and "شماره نیاز در سامانه ستاد" in terms
    # shorter than required: the gate fails until overridden with a reason
    r = client.patch(f"/api/quotes/{quote['id']}", json={"valid_until": (required - timedelta(days=1)).isoformat()})
    approval = r.json()["approval"]
    codes = [f["code"] for f in approval["failures"]]
    assert "validity_shorter_than_required" in codes and approval["required_valid_until"] == required.isoformat()
    r = client.post(f"/api/quotes/{quote['id']}/approve")
    assert r.status_code == 409 and "validity_shorter_than_required" in r.text
    assert client.post(f"/api/quotes/{quote['id']}/validity-override", json={"reason": " "}).status_code == 422
    r = client.post(f"/api/quotes/{quote['id']}/validity-override", json={"reason": "خریدار تلفنی پذیرفت"})
    assert r.status_code == 200 and r.json()["approval"]["ok"] is True
    assert len(events(client, "quote", quote["id"], "gate_override")) == 1
    html = client.get(f"/api/quotes/{quote['id']}/print").text
    assert number in html and "شناسه ملی" in html and "10320000000" in html and "411111111111" in html
    assert "مبلغ به حروف" in html and "علی رضایی" in html and "مدیرعامل" in html
    r = client.post(f"/api/quotes/{quote['id']}/outputs", json={"format": "docx"})
    assert r.status_code in (200, 201), r.text
    assert number in r.json()["filename"] and r.json()["filename"].endswith("-DRAFT.docx")


def test_required_validity_beyond_the_offers_shows_both_dates(client, db):
    required = date.today() + timedelta(days=90)                     # offers / FX allow ~30 days
    case, party, number = setad_case(client, db, required)
    quote = new_quote(client, case)
    assert quote["valid_until"] < required.isoformat()
    shorter = next(f for f in quote["approval"]["failures"] if f["code"] == "validity_shorter_than_required")
    assert shorter["required_valid_until"] == required.isoformat() and shorter["max_valid_until"]
    assert shorter["valid_until"] == quote["valid_until"]


def test_non_setad_quotes_keep_the_default_template(client):
    case, items, party, sheet = ready_case(client, country="IR")
    quote = new_quote(client, case)
    assert quote["setad"] is None and "مدیریت محترم امور تدارکات" not in quote["terms_text"]
    assert all(f["code"] != "validity_shorter_than_required" for f in quote["approval"]["failures"])


def test_setad_placeholders_are_valid_in_quote_terms_only(client):
    body = {"kind": "quote_terms", "language": "fa", "channel": "letter", "name": f"t {tag()}",
            "subject_template": "", "body_template": "{addressee}\n{setad_number}"}
    assert client.post("/api/message-templates", json=body).status_code == 201
    r = client.post("/api/message-templates", json={**body, "kind": "rfq", "name": f"r {tag()}"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_placeholder"


@pytest.mark.parametrize("amount,words", [
    (0, "صفر"), (1000, "یک هزار"),
    (3001878000, "سه میلیارد و یک میلیون و هشتصد و هفتاد و هشت هزار"),
    (1000000000000, "یک هزار میلیارد"),
])
def test_total_in_persian_words(amount, words):
    assert number_words(amount) == words
    assert total_in_words(__import__("decimal").Decimal(amount), "IRR") == f"{words} ریال"


# ---- command center and search ------------------------------------------------------------------------------

def test_command_center_setad_section_and_search(client, db, files_dir):
    org = f"دانشکده {tag()}"
    lid = make_listing(db, files_dir, organization=org, files=())
    star(client, lid)
    db.execute(text("UPDATE ext.listing SET response_deadline = now() + interval '1 day' WHERE id = :l"), {"l": lid})
    db.commit()
    client.patch("/api/settings", json={"setad.warn_keywords": ["سانتریفیوژ"]})
    cc = client.get("/api/command-center").json()
    assert "sourcing" in cc and "setad" in cc
    assert str(lid) in [str(x["id"]) for x in cc["setad"]["due"]]
    assert {r["source"] for r in cc["setad"]["runs"]} == {"setad_purchase", "setad_tender"}
    number = db.execute(text("SELECT external_no FROM ext.listing WHERE id = :l"), {"l": lid}).scalar_one()
    hits = client.get("/api/search", params={"q": number}).json()
    groups = hits.get("groups", hits) if isinstance(hits, dict) else hits
    flat = str(groups)
    assert str(lid) in flat and "/tenders?" in flat
    _ = io
