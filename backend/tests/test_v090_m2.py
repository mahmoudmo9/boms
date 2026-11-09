"""v0.9.0 milestone 2: the readable folder view (build, update on link changes, rename, delete, rebuild, copies when hard
links fail, Windows names, not backed up), output and subject naming, and document control (stamps per status, footer,
QR payload with HMAC verification, superseded detection)."""
import io
import os
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import unique_bytes, upload
from tests.test_parties import tag
from tests.test_quotes import new_quote, ready_case, sent_quote


def _sync(client):
    r = client.post("/api/folders/sync")
    assert r.status_code == 200, r.text
    return r.json()


def _case_dir(client, db, case_id) -> Path:
    from app.modules.documents import folders

    return folders.case_folder(db, case_id)


# ---- folder view --------------------------------------------------------------------------------------------------------

def test_folder_view_build_link_changes_rename_delete_and_rebuild(client, db):
    from app.core.config import get_config
    from app.core.files import store_relpath
    from app.modules.documents import folders

    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case)
    out = client.post(f"/api/quotes/{quote['id']}/outputs", json={"format": "docx"}).json()
    doc = upload(client, f"spec-{tag()}.txt", unique_bytes("spec")).json()
    link = client.post(f"/api/documents/{doc['id']}/links", json={"entity_type": "case", "entity_id": case["id"]}).json()
    queued = db.execute(text("SELECT count(*) FROM sys.job WHERE type = 'folders.sync' AND status = 'queued'")).scalar()
    assert queued == 1                                              # a link change queues one sync
    report = _sync(client)
    assert report["linked"] >= 2 and report["copied"] == 0
    root = folders.view_root(db)
    case_dir = _case_dir(client, db, case["id"])
    assert case_dir.parent == root and case_dir.name.startswith(case["code"] + " ")
    subs = sorted(p.name for p in case_dir.iterdir())
    assert subs[0] == "۰۱ درخواست" and "۰۳ پیش‌فاکتور" in subs and not any(s.startswith("۰۹") for s in subs)
    quote_file = case_dir / "۰۳ پیش‌فاکتور" / out["filename"]
    sha = db.execute(text("SELECT sha256 FROM core.document WHERE id = :i"), {"i": out["document_id"]}).scalar()
    store = get_config().files_dir / store_relpath(sha)
    assert quote_file.exists() and os.path.samefile(quote_file, store)          # a hard link, no copy
    assert quote_file.stat().st_mode & 0o222 == 0                               # read-only
    uploaded = list((case_dir / "۰۱ درخواست").iterdir())
    assert [p.name for p in uploaded] == [f"{doc['uploaded_at'][:10]}_{doc['original_filename']}"]
    # unlink -> gone; the store keeps the file
    assert client.delete(f"/api/documents/{doc['id']}/links/{link['id']}").status_code == 204
    _sync(client)
    assert list((case_dir / "۰۱ درخواست").iterdir()) == []
    assert store.exists()
    # rename the case -> the folder follows
    client.patch(f"/api/cases/{case['id']}", json={"title": f"Renamed {tag()}"})
    _sync(client)
    assert not case_dir.exists()
    renamed = _case_dir(client, db, case["id"])
    assert renamed.exists() and (renamed / "۰۳ پیش‌فاکتور" / out["filename"]).exists()
    # rebuild from scratch gives the same view
    report = folders.rebuild_all(db)
    db.commit()
    assert (renamed / "۰۳ پیش‌فاکتور" / out["filename"]).exists() and report["linked"] >= 1
    # a deleted case leaves the view
    empty = client.post("/api/cases", json={"title": f"Empty {tag()}"}).json()
    _sync(client)
    empty_dir = _case_dir(client, db, empty["id"])
    assert empty_dir.exists()
    assert client.delete(f"/api/cases/{empty['id']}").status_code == 204
    _sync(client)
    assert not empty_dir.exists()


def test_folder_view_falls_back_to_copies(client, db, monkeypatch):
    from app.modules.documents import folders

    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case)
    out = client.post(f"/api/quotes/{quote['id']}/outputs", json={"format": "docx"}).json()

    def no_links(*_a, **_k):
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(folders.os, "link", no_links)
    folders.rebuild_all(db)
    db.commit()
    target = _case_dir(client, db, case["id"]) / "۰۳ پیش‌فاکتور" / out["filename"]
    assert target.exists() and target.stat().st_nlink == 1 and target.stat().st_mode & 0o222 == 0
    status = client.get("/api/folders/status").json()
    assert status["mode"] == "copy" and status["copied"] >= 1
    monkeypatch.undo()
    folders.rebuild_all(db)
    db.commit()
    assert client.get("/api/folders/status").json()["mode"] == "hardlink"


def test_windows_name_sanitising():
    from app.modules.documents.folders import case_folder_name, sanitize

    assert sanitize('a<b>c:d"e/f\\g|h?i*j.pdf') == "a_b_c_d_e_f_g_h_i_j.pdf"
    assert sanitize("CON.txt") == "_CON.txt" and sanitize("lpt1") == "_lpt1"
    assert sanitize("report. . .") == "report" and sanitize("  ") == "_"
    long = sanitize("x" * 300 + ".pdf")
    assert len(long) == 120 and long.endswith(".pdf")
    assert case_folder_name("CS-1405-0012", "پمپ صنعتی", "نفت و گاز پارس") == "CS-1405-0012 پمپ صنعتی - نفت و گاز پارس"


def test_folder_view_is_not_backed_up(client, db):
    from app.core.config import get_config
    from app.modules.documents import folders
    from app.modules.system import backup

    case, items, party, sheet = ready_case(client)
    doc = upload(client, f"b-{tag()}.txt", unique_bytes("b")).json()
    client.post(f"/api/documents/{doc['id']}/links", json={"entity_type": "case", "entity_id": case["id"]})
    _sync(client)
    root = folders.view_root(db)
    assert any(root.rglob("*.txt"))
    backup.run_backup("manual", source="script")
    backups = get_config().backups_dir
    assert not any(folders.ROOT_NAME in str(p) for p in backups.rglob("*"))
    assert not str(root).startswith(str(get_config().files_dir))


def test_open_folder_is_local_and_returns_the_path(client, db):
    case, items, party, sheet = ready_case(client)
    r = client.post(f"/api/cases/{case['id']}/folder/open")
    assert r.status_code == 200 and r.json()["path"].endswith(Path(_case_dir(client, db, case["id"])).name)
    assert r.json()["opened"] is False                     # not Windows here: the path is returned instead


# ---- naming --------------------------------------------------------------------------------------------------------------

def test_output_names_fa_and_en(db):
    from datetime import date

    from app.modules.documents import naming

    assert naming.party_short("نفت و گاز پارس", "fa") == "نفت‌وگازپارس"
    assert naming.party_short("Shanghai Valve Co., Ltd.", "en", ["Co., Ltd.", "Ltd"]) == "ShanghaiValve"
    fa = naming.output_name(db, kind="quote", code="PI-1405-0005", party="نفت و گاز پارس", on=date(2026, 11, 1),
                            lang="fa", ext="pdf", version=2)
    assert fa == "PI-1405-0005_پیش‌فاکتور_نفت‌وگازپارس_14050810_v2.pdf"
    en = naming.output_name(db, kind="purchase_order", code="PO-1405-0007", party="Shanghai Valve Co., Ltd.",
                            on=date(2026, 11, 1), lang="en", ext="pdf")
    assert en == "PO-1405-0007_PurchaseOrder_ShanghaiValve_20261101.pdf"
    assert naming.output_name(db, kind="sales_invoice", code="INV-1405-0001", party=None, on=date(2026, 11, 1), lang="en",
                              ext="docx", draft=True) == "INV-1405-0001_Invoice_20261101_DRAFT.docx"
    with pytest.raises(ValueError):
        naming.check("{type}_{date}")


def test_rfq_excel_name_and_subject_with_code(client):
    from tests.test_sourcing_rfq import make_case, new_rfq, supplier

    case, items = make_case(client, [{"name": "Valve", "quantity": "2"}])
    body = new_rfq(client, case, items, [{"party_id": supplier(client)["id"]}])
    assert body["code"].startswith("RFQ-")
    r = client.get(f"/api/rfqs/{body['id']}/export.xlsx")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert f'{body["code"]}_RFQ_' in cd and "rfq-" not in cd.split(";")[1]
    preview = client.post("/api/message-templates/preview", json={"kind": "rfq", "language": "en",
                                                                  "subject_template": "[{code}] RFQ – {case_title}",
                                                                  "body_template": "x"}).json()
    assert preview["subject"] == "[RFQ-1405-0009] RFQ – Sample case"


def test_letters_carry_number_and_date(client):
    from tests.test_sourcing_rfq import make_case, new_rfq, supplier

    case, items = make_case(client, [{"name": "Valve", "quantity": "2"}])
    sup = supplier(client)
    client.post("/api/message-templates", json={"kind": "rfq", "language": "fa", "channel": "letter",
                                                "name": f"نامه {tag()}", "subject_template": "",
                                                "body_template": "با سلام\n{items_table}", "is_default": True})
    body = new_rfq(client, case, items, [{"party_id": sup["id"], "channel": "letter", "language": "fa"}])
    text_ = body["recipients"][0]["message_text"]
    assert text_.startswith(f"شماره: {body['code']}\nتاریخ: ")


# ---- document control -------------------------------------------------------------------------------------------------

def test_stamps_footer_and_qr_per_status(client):
    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case)
    html = client.get(f"/api/quotes/{quote['id']}/print").text
    assert "data-status='draft'" in html and "DRAFT" in html or "پیش‌نویس" in html
    assert "counter(pages" in html and "data-payload='BOMS|" in html
    client.post(f"/api/quotes/{quote['id']}/approve")
    html = client.get(f"/api/quotes/{quote['id']}/print").text
    assert "data-status='issued'" in html
    m = re.search(r"data-payload='(BOMS\|[^']+)'", html)
    payload = m.group(1)
    assert payload.startswith(f"BOMS|{quote['number']}|v1|")
    r = client.post("/api/verify-document", json={"text": payload}).json()
    assert r["valid"] is True and r["kind"] == "quote" and r["status"] == "issued"
    tampered = payload.replace("|v1|", "|v2|")
    assert client.post("/api/verify-document", json={"text": tampered}).json() == {
        "valid": False, "reason": "signature_mismatch", "code": quote["number"], "version": 2,
        "issue_date": payload.split("|")[3]}
    vc = payload.rsplit("|", 1)[1]
    typed = client.post("/api/verify-document", json={"code": quote["number"], "verification_code": vc.lower()}).json()
    assert typed["valid"] is True
    assert client.post("/api/verify-document", json={"text": "hello"}).json() == {"valid": False, "reason": "unreadable"}


def test_superseded_and_void(client):
    case, items, party, sheet, quote = sent_quote(client)
    html = client.get(f"/api/quotes/{quote['id']}/print").text
    payload = re.search(r"data-payload='(BOMS\|[^']+)'", html).group(1)
    new = client.post(f"/api/quotes/{quote['id']}/revise", json={}).json()
    r = client.post("/api/verify-document", json={"text": payload}).json()
    assert r["valid"] is True and r["status"] == "superseded"
    old_html = client.get(f"/api/quotes/{quote['id']}/print").text
    assert "data-status='superseded'" in old_html and "SUPERSEDED" in old_html or "جایگزین‌شده" in old_html
    assert client.get(f"/api/quotes/{new['id']}").json()["version"] == 2
    from app.modules.documents import control

    assert control._status("cancelled") == "void" and control.stamp_text("void", "fa") == "باطل"
    assert control.stamp_text("void", "en") == "VOID"


def test_word_output_has_stamp_footer_fields_and_qr(client):
    from docx import Document

    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case)
    out = client.post(f"/api/quotes/{quote['id']}/outputs", json={"format": "docx"}).json()
    doc = Document(io.BytesIO(client.get(f"/api/documents/{out['document_id']}/download").content))
    section = doc.sections[0]
    header = "\n".join(p.text for p in section.header.paragraphs)
    footer_xml = section.footer._element.xml
    assert ("DRAFT" in header or "پیش‌نویس" in header)
    assert "NUMPAGES" in footer_xml and "PAGE" in footer_xml and "graphicData" in footer_xml
    assert doc.core_properties.comments.startswith("BOMS|")


def test_hkdf_key_is_derived_not_the_session_key():
    from app.core.secrets import get_secret
    from app.modules.documents import control

    key = control._key()
    assert len(key) == 32 and key != get_secret("session_key").encode()[:32]
    # RFC 5869 test case 3 (empty salt and info) for the HKDF construction
    okm = control._hkdf(bytes.fromhex("0b" * 22), b"", 42)
    assert okm.hex().startswith("8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d")
