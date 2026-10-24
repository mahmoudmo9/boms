from decimal import Decimal

from sqlalchemy import func, select

from app.modules.system.models import Country, Currency, Unit
from app.modules.system.seed import seed_base_data
from app.modules.system.seed_data import COUNTRIES, CURRENCIES, UNITS


def test_seed_counts_and_idempotent(db):
    assert db.scalar(select(func.count()).select_from(Country)) >= 249
    assert db.scalar(select(func.count()).select_from(Currency)) >= 178
    assert db.scalar(select(func.count()).select_from(Unit)) >= 30
    assert seed_base_data(db) == {"countries": 0, "currencies": 0, "units": 0}


def test_seed_data_quality():
    iso2 = [c[0] for c in COUNTRIES]
    assert len(iso2) == len(set(iso2)) == 249
    assert len({c[1] for c in COUNTRIES}) == 249
    codes = {c[0] for c in CURRENCIES}
    for required in ("IRR", "USD", "EUR", "AED", "CNY", "TRY", "GBP", "RUB", "INR", "JPY", "KRW"):
        assert required in codes
    for _, _, name_fa, _ in COUNTRIES:
        assert "ي" not in name_fa and "ك" not in name_fa
    by_code = {u[0]: u for u in UNITS}
    assert by_code["t"][4] == Decimal("1000") and by_code["g"][4] == Decimal("0.001")
    assert by_code["l"][4] == Decimal("0.001") and by_code["h"][4] == Decimal("3600")


def test_minor_units(db):
    assert db.get(Currency, "JPY").minor_units == 0
    assert db.get(Currency, "KWD").minor_units == 3
    assert db.get(Currency, "USD").minor_units == 2
    assert db.get(Currency, "XAU").active is False


def test_search_with_arabic_letters_finds_persian_name(client):
    r = client.get("/api/basedata/countries", params={"q": "ايران"})
    assert r.status_code == 200
    assert "IR" in [c["iso2"] for c in r.json()["items"]]
    r = client.get("/api/basedata/currencies", params={"q": "يورو"})
    assert "EUR" in [c["code"] for c in r.json()["items"]]
    r = client.get("/api/basedata/units", params={"q": "KILO"})
    assert {"kg", "km"} <= {u["code"] for u in r.json()["items"]}


def test_list_paging_and_filter(client):
    r = client.get("/api/basedata/countries", params={"page": 2, "page_size": 10})
    body = r.json()
    assert body["page"] == 2 and len(body["items"]) == 10 and body["total"] >= 249
    inactive = client.get("/api/basedata/currencies", params={"active": "false"}).json()
    assert all(not c["active"] for c in inactive["items"]) and inactive["total"] > 0


def test_create_edit_activate_country(client):
    r = client.post("/api/basedata/countries", json={"iso2": "xk", "iso3": "xkx", "name_fa": "کوزوو", "name_en": "Kosovo"})
    assert r.status_code == 201, r.text
    assert r.json()["iso2"] == "XK"
    assert client.post("/api/basedata/countries",
                       json={"iso2": "XK", "iso3": "XKY", "name_fa": "x", "name_en": "x"}).status_code == 409
    r = client.patch("/api/basedata/countries/XK", json={"name_en": "Republic of Kosovo"})
    assert r.status_code == 200 and r.json()["name_en"] == "Republic of Kosovo"
    r = client.patch("/api/basedata/countries/XK", json={"active": False})
    assert r.json()["active"] is False
    actions = [e["action"] for e in client.get("/api/events", params={"entity_type": "country"}).json()["items"]
               if e["entity_id"] == "XK"]
    assert actions[:3] == ["deactivate", "update", "create"]
    assert client.patch("/api/basedata/countries/QQ", json={"active": False}).status_code == 404


def test_unit_decimal_factor_and_validation(client):
    r = client.post("/api/basedata/units",
                    json={"code": "ozt", "name_fa": "اونس تروا", "name_en": "Troy ounce", "kind": "weight",
                          "base_factor": "0.0311034768"})
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["base_factor"]) == Decimal("0.0311034768")
    bad = client.post("/api/basedata/units",
                      json={"code": "Bad Code", "name_fa": "x", "name_en": "x", "kind": "weight", "base_factor": "1"})
    assert bad.status_code == 422
    assert client.post("/api/basedata/units",
                       json={"code": "zz", "name_fa": "x", "name_en": "x", "kind": "weight", "base_factor": "0"}).status_code == 422


def test_no_delete_endpoint(client):
    assert client.delete("/api/basedata/countries/IR").status_code == 405


def test_requires_login(anon_client):
    assert anon_client.get("/api/basedata/countries").status_code == 401
