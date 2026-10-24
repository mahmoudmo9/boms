import os
import stat
import zipfile
from io import BytesIO

from sqlalchemy import func, select, text

from app.core.config import get_config
from app.modules.documents.models import Document
from app.worker import runner
from app.worker.registry import load_handlers
from tests.conftest import make_pdf, unique_bytes, upload


def test_upload_stores_content_addressed_read_only_file(client):
    content = unique_bytes("hello")
    r = upload(client, "note.txt", content, title="My note")
    assert r.status_code == 201, r.text
    doc = r.json()
    sha = doc["sha256"]
    path = get_config().files_dir / sha[:2] / sha[2:4] / sha
    assert path.read_bytes() == content
    assert path.suffix == ""
    assert not os.stat(path).st_mode & stat.S_IWUSR
    assert doc["title"] == "My note" and doc["mime_type"] == "text/plain" and doc["size_bytes"] == len(content)


def test_same_file_twice_stores_one_copy_and_returns_409(client, db):
    content = unique_bytes("dup")
    first = upload(client, "a.txt", content, title="Original")
    assert first.status_code == 201
    second = upload(client, "b-renamed.txt", content)
    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "duplicate_document"
    assert error["details"] == {"id": first.json()["id"], "title": "Original"}
    sha = first.json()["sha256"]
    assert db.scalar(select(func.count()).select_from(Document).where(Document.sha256 == sha)) == 1
    assert len(list((get_config().files_dir / sha[:2] / sha[2:4]).iterdir())) == 1


def test_executables_rejected_by_extension(client):
    for name in ("setup.exe", "run.ps1", "x.BAT", "a.js", "app.msi", "link.lnk", "page.hta", "lib.jar"):
        r = upload(client, name, unique_bytes(name))
        assert r.status_code == 415, name
        assert r.json()["error"]["code"] == "blocked_file_type"


def _jar() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        zf.writestr("a/Main.class", b"\xca\xfe\xba\xbe")
    return buf.getvalue()


def _msi() -> bytes:
    sector = 512
    header = bytearray(sector)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    header[30:32] = (9).to_bytes(2, "little")
    header[48:52] = (0).to_bytes(4, "little")
    root = bytearray(sector)
    root[80:96] = bytes.fromhex("84100c0000000000c000000000000046")
    return bytes(header + root)


def test_executables_rejected_by_content(client):
    cases = {
        "invoice.pdf": b"MZ\x90\x00" + os.urandom(64),
        "readme.txt": b"#!/bin/sh\nrm -rf /\n" + os.urandom(8),
        "shortcut.dat": bytes.fromhex("4c0000000114020000000000c000000000000046") + os.urandom(32),
        "archive.zip": _jar(),
        "installer.doc": _msi(),
        "page.html": b"<html><HTA:APPLICATION id=x></html>" + os.urandom(8),
        "run.txt": b"@echo off\r\ndel *.*\r\n" + os.urandom(8),
    }
    for name, content in cases.items():
        r = upload(client, name, content)
        assert r.status_code == 415, (name, r.text)


def test_office_zip_is_allowed(client):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", f"<doc>{os.urandom(8).hex()}</doc>")
    assert upload(client, "report.docx", buf.getvalue()).status_code == 201


def test_max_size_enforced(client):
    assert client.patch("/api/settings", json={"upload.max_mb": 1}).status_code == 200
    try:
        r = upload(client, "big.bin", os.urandom(1024 * 1024 + 10))
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "file_too_large"
    finally:
        client.patch("/api/settings", json={"upload.max_mb": 100})
    assert not list((get_config().files_dir / ".incoming").iterdir())


def test_metadata_edit_list_download_preview(client):
    content = unique_bytes("download")
    doc = upload(client, "گزارش ماهانه.txt", content).json()
    assert doc["title"] == "گزارش ماهانه"

    r = client.patch(f"/api/documents/{doc['id']}", json={"title": "Monthly report", "notes": "for review"})
    assert r.status_code == 200 and r.json()["notes"] == "for review"

    r = client.get(f"/api/documents/{doc['id']}/download")
    assert r.status_code == 200 and r.content == content
    assert "attachment" in r.headers["content-disposition"]
    assert "filename*=utf-8''" in r.headers["content-disposition"].lower()

    assert client.get(f"/api/documents/{doc['id']}/preview").status_code == 415

    listing = client.get("/api/documents", params={"sort": "title", "order": "asc", "page_size": 200}).json()
    titles = [d["title"] for d in listing["items"]]
    assert titles == sorted(titles)
    assert listing["total"] >= 1
    events = client.get("/api/events", params={"entity_type": "document", "entity_id": doc["id"]}).json()["items"]
    assert [e["action"] for e in events] == ["update", "create"]


def test_pdf_preview_inline_and_text_extraction(client, db):
    load_handlers()
    marker = "zebracrossing" + os.urandom(3).hex()
    r = upload(client, "spec.pdf", make_pdf(f"Technical sheet {marker}"))
    assert r.status_code == 201
    doc = r.json()
    assert doc["mime_type"] == "application/pdf" and doc["text_status"] == "pending" and doc["previewable"]

    preview = client.get(f"/api/documents/{doc['id']}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.headers["content-disposition"].startswith("inline")

    runner.run_until_idle()
    db.expire_all()
    row = db.get(Document, doc["id"])
    assert row.text_status == "done"
    assert marker in db.execute(text("SELECT text_content FROM core.document WHERE id = :i"), {"i": doc["id"]}).scalar()
    found = client.get("/api/documents", params={"q": marker}).json()["items"]
    assert [d["id"] for d in found] == [doc["id"]]


def test_link_and_unlink(client):
    doc = upload(client, "contract.txt", unique_bytes("contract")).json()
    r = client.post(f"/api/documents/{doc['id']}/links", json={"entity_type": "country", "entity_id": "IR"})
    assert r.status_code == 201
    link_id = r.json()["id"]
    again = client.post(f"/api/documents/{doc['id']}/links", json={"entity_type": "country", "entity_id": "IR"})
    assert again.json()["id"] == link_id
    linked = client.get("/api/documents", params={"entity_type": "country", "entity_id": "IR"}).json()["items"]
    assert doc["id"] in [d["id"] for d in linked]
    assert len(client.get(f"/api/documents/{doc['id']}").json()["links"]) == 1
    assert client.delete(f"/api/documents/{doc['id']}/links/{link_id}").status_code == 204
    assert client.get(f"/api/documents/{doc['id']}").json()["links"] == []
    actions = [e["action"] for e in client.get("/api/events", params={"entity_id": doc["id"]}).json()["items"]]
    assert actions[:2] == ["unlink", "link"]


def test_no_hard_delete(client):
    doc = upload(client, "keep.txt", unique_bytes("keep")).json()
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 405


def test_document_requires_login(anon_client):
    assert anon_client.get("/api/documents").status_code == 401
