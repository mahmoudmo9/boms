import os

from app.modules.search import registry
from app.modules.search.registry import SearchHit, SearchProvider
from tests.conftest import unique_bytes, upload


def _ids(groups, kind):
    for g in groups:
        if g["type"] == kind:
            return [i["id"] for i in g["items"]]
    return []


def test_persian_word_written_with_arabic_letters(client):
    tag = os.urandom(3).hex()
    doc = upload(client, f"q{tag}.txt", unique_bytes(), title=f"گزارش کیفیت لوله‌های فولادی {tag}").json()
    groups = client.get("/api/search", params={"q": "كيفيت"}).json()["groups"]
    assert doc["id"] in _ids(groups, "document")
    groups = client.get("/api/search", params={"q": "لوله هاي"}).json()["groups"]
    assert doc["id"] in _ids(groups, "document")


def test_misspelled_latin_word(client):
    tag = os.urandom(3).hex()
    doc = upload(client, f"pump-{tag}.txt", unique_bytes(), title=f"Hydraulic pump specification {tag}").json()
    groups = client.get("/api/search", params={"q": "hydrolic"}).json()["groups"]
    assert doc["id"] in _ids(groups, "document")
    groups = client.get("/api/search", params={"q": "specifcation"}).json()["groups"]
    assert doc["id"] in _ids(groups, "document")


def test_notes_are_searchable(client):
    tag = os.urandom(4).hex()
    doc = upload(client, "n.txt", unique_bytes(), title="plain", notes=f"شماره سفارش {tag}").json()
    assert doc["id"] in _ids(client.get("/api/search", params={"q": tag}).json()["groups"], "document")


def test_base_data_in_both_languages_and_fuzzy(client):
    groups = client.get("/api/search", params={"q": "ايران"}).json()["groups"]
    assert "IR" in _ids(groups, "country")
    assert "IRR" in _ids(groups, "currency")
    groups = client.get("/api/search", params={"q": "Germny"}).json()["groups"]
    assert "DE" in _ids(groups, "country")
    groups = client.get("/api/search", params={"q": "یورو"}).json()["groups"]
    assert "EUR" in _ids(groups, "currency")
    groups = client.get("/api/search", params={"q": "کیلوگرم"}).json()["groups"]
    assert "kg" in _ids(groups, "unit")


def test_results_are_grouped_and_ordered(client):
    groups = client.get("/api/search", params={"q": "iran", "limit": 3}).json()["groups"]
    types = [g["type"] for g in groups]
    assert types == sorted(types, key=["document", "country", "currency", "unit"].index)
    assert all(len(g["items"]) <= 3 for g in groups)
    assert all(g["label_key"].startswith("search.type.") for g in groups)
    assert client.get("/api/search", params={"q": "   "}).json()["groups"] == []


def test_registration_interface(client):
    def search(db, needle, raw, limit):
        return [SearchHit(id="x1", title=f"echo {needle}", link="/x/1")] if needle == "ping" else []

    registry.register(SearchProvider(type="test_echo", label_key="search.type.test", search=search, order=5))
    try:
        groups = client.get("/api/search", params={"q": "PING"}).json()["groups"]
        assert groups[0]["type"] == "test_echo" and groups[0]["items"][0]["title"] == "echo ping"
    finally:
        registry.PROVIDERS.pop("test_echo")


def test_search_requires_login(anon_client):
    assert anon_client.get("/api/search", params={"q": "x"}).status_code == 401
