"""Review fixes for v0.1.1: malformed input must give 4xx, never 500 or a dropped connection."""

import pytest

from tests.conftest import upload


def test_non_ascii_csrf_header_is_403_not_500(client):
    # sent as raw UTF-8 bytes, as a browser would; the server sees a non-ASCII str
    r = client.post("/api/auth/lock", headers={"X-CSRF-Token": "é".encode()})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


def test_non_ascii_csrf_cookie_and_session_cookie_are_not_500(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": "x"},
                         headers={"X-CSRF-Token": "é".encode(), "Cookie": "boms_csrf=ü".encode()})
    assert r.status_code == 403
    r = anon_client.get("/api/me", headers={"Cookie": "boms_session=x.é".encode()})
    assert r.status_code == 401


@pytest.mark.parametrize("q", ["a\x00b", "a\x01b", "\x1b[0m"])
def test_control_characters_in_query_rejected(client, q):
    r = client.get("/api/search", params={"q": q})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


def test_nul_in_raw_query_string_rejected(client):
    r = client.get("/api/search?q=a%00b")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"
    # the connection still works afterwards
    assert client.get("/api/search", params={"q": "iran"}).status_code == 200


def test_tab_and_newline_still_allowed(client):
    assert client.get("/api/search", params={"q": "a\tb\nc"}).status_code == 200
    r = client.patch("/api/basedata/countries/IR", json={"name_en": "Iran"})
    assert r.status_code == 200


def test_nul_in_path_rejected(client):
    r = client.patch("/api/basedata/countries/I%00R", json={"active": True})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


@pytest.mark.parametrize("payload", [
    {"name_en": "Ir\u0000an"},
    {"name_en": "ok", "nested": ["fine", {"deep": "bad\u0007"}]},
])
def test_control_characters_in_json_rejected(client, payload):
    r = client.patch("/api/basedata/countries/IR", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


def test_control_characters_in_upload_form_rejected(client):
    r = upload(client, "nul.txt", b"content nul form", title="bad\x00title")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_input"


def test_unknown_fields_rejected_on_patch(client):
    r = client.patch("/api/basedata/countries/IR", json={"bogus": 1})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert client.get("/api/basedata/countries", params={"q": "IR"}).status_code == 200


@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/basedata/units", {"code": "zzz", "name_fa": "x", "name_en": "x", "kind": "count", "base_factor": "1", "bogus": 1}),
    ("patch", "/api/me", {"theme": "dark", "bogus": 1}),
    ("post", "/api/me/password", {"current_password": "x", "new_password": "yyyyyyyy", "bogus": 1}),
    ("post", "/api/system/restore-test", {"bogus": 1}),
    ("post", "/api/settings/archive-password", {"password": "long-enough-password", "bogus": 1}),
])
def test_unknown_fields_rejected_on_every_input_model(client, method, path, body):
    r = getattr(client, method)(path, json=body)
    assert r.status_code == 422, (path, r.text)


def test_unknown_fields_rejected_on_login(anon_client):
    r = anon_client.post("/api/auth/login", json={"username": "admin", "password": "x", "bogus": 1})
    assert r.status_code == 422


def test_unknown_fields_rejected_on_document_patch_and_link(client):
    doc = upload(client, "extra.txt", b"extra fields test 0.1.1").json()
    assert client.patch(f"/api/documents/{doc['id']}", json={"title": "t", "bogus": 1}).status_code == 422
    r = client.post(f"/api/documents/{doc['id']}/links", json={"entity_type": "country", "entity_id": "IR", "bogus": 1})
    assert r.status_code == 422
