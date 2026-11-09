"""v0.9.0 milestone 5 (backend part): lookup ranking per kind with Persian normalisation, suggestions with their
sources, every validator with valid and invalid official examples, calculation in place, the duplicate warning."""
from decimal import Decimal

import pytest

from tests.test_parties import make_party, tag


def lookup(client, kind, q, **extra):
    r = client.get("/api/lookup", params={"kind": kind, "q": q, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# ---- 8.1 lookup ----------------------------------------------------------------------------------------------------

def test_lookup_ranks_exact_code_then_prefix_then_names(client):
    t = tag()
    a = make_party(client, name_en=f"Valve Works {t}", roles=["supplier"], country_iso2="CN")
    make_party(client, name_en=f"Best Valve {t}", roles=["supplier"], country_iso2="CN")
    by_code = lookup(client, "party", a["code"])
    assert by_code[0]["id"] == a["id"] and by_code[0]["match"] == "exact_code"
    by_name = lookup(client, "party", f"valve works {t}")
    assert by_name[0]["id"] == a["id"] and by_name[0]["match"] in ("name_prefix", "name_contains")
    assert by_name[0]["subtitle"].startswith("CN")


def test_lookup_persian_normalisation_and_kinds(client):
    t = tag()
    p = make_party(client, name_fa=f"شرکت كيميا {t}", roles=["buyer"])          # Arabic kaf / yeh as typed elsewhere
    hits = lookup(client, "party", f"کیمیا {t}")                                 # Persian ک / ی
    assert hits and hits[0]["id"] == p["id"]
    sha = lookup(client, "location", "SHA", function="port")              # the location part of the UN/LOCODE
    assert sha[0]["code"] == "CNSHA" and sha[0]["match"] == "exact_code"
    assert lookup(client, "location", "IRBUZ")[0]["code"] == "IRBUZ"
    assert lookup(client, "incoterm", "CFR")[0]["code"] == "CFR"
    assert lookup(client, "container", "45G1")[0]["match"] == "exact_code"
    assert lookup(client, "currency", "usd")[0]["code"] == "USD"
    assert lookup(client, "hs", "8413")[0]["code"] == "8413"
    assert any(x["code"] == "IR-PJS" for x in lookup(client, "legal_form", "سهامی خاص", country="IR"))
    units = lookup(client, "unit", "H87")
    assert units and units[0]["match"] == "exact_code"
    case = client.post("/api/cases", json={"title": f"Pump deal {t}"}).json()
    found = lookup(client, "code", case["code"])
    assert found[0]["code"] == case["code"] and found[0]["link"]
    assert client.get("/api/lookup", params={"kind": "planet", "q": "x"}).status_code == 422


# ---- 8.2 suggestions -------------------------------------------------------------------------------------------------

def test_suggestions_come_with_their_source(client):
    from tests.test_execution_m3 import deal

    case, party, so, pos = deal(client)
    s = client.get("/api/suggest", params={"context": "party", "id": party["id"], "role": "buyer"}).json()
    assert s["currency"]["source"] == so["number"] and s["currency"]["source_kind"] == "sales_order"
    po = pos["USD"]
    sup = client.get("/api/suggest", params={"context": "party", "id": po["supplier_party_id"], "role": "supplier"}).json()
    assert sup["currency"]["value"] == "USD" and sup["currency"]["source"] == po["number"]
    c = client.get("/api/suggest", params={"context": "case", "id": case["id"]}).json()
    assert c["buyer_party_id"]["value"] == party["id"] and c["currency"]["source"] in (so["number"],) or c["currency"]["source_kind"] == "quote"
    fresh = make_party(client, name_en=f"New {tag()}", roles=["buyer"], country_iso2="AE")
    assert client.get("/api/suggest", params={"context": "party", "id": fresh["id"]}).json() == {
        "language": {"value": "en", "source": None, "source_kind": "rule", "source_id": None}}


def test_product_suggestion_last_prices(client):
    from tests.test_quotes import new_quote, ready_case

    product = client.post("/api/products", json={"name_en": f"Pump {tag()}", "hs_code": "841370",
                                                 "confirm_duplicate": True}).json()["product"]
    case, items, party, sheet = ready_case(client)
    client.patch(f"/api/line-items/{items[0]['id']}", json={"product_id": product["id"]})
    new_quote(client, case)
    s = client.get("/api/suggest", params={"context": "product", "id": product["id"]}).json()
    assert s["hs_code"]["value"] == "841370" and s["hs_code"]["source"] == product["code"]
    assert "unit_price" in s["last_purchase"]["value"] and s["last_purchase"]["source_kind"] == "offer"
    assert s["last_sale"]["source_kind"] == "quote"


# ---- 8.3 validators ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,good,bad", [
    ("iban", "GB82 WEST 1234 5698 7654 32", "GB82 WEST 1234 5698 7654 33"),
    ("iban", "IR06 2960 0000 0010 0324 2000 01", "IR06 2960 0000 0010 0324 2000 02"),
    ("bic", "DEUTDEFF500", "DEUT1EFF"),
    ("national_id_ir", "0499370899", "0499370898"),
    ("national_id_ir", "10380284790", "10380284791"),
    ("national_id_ir", "۰۴۹۹۳۷۰۸۹۹", "1111111111"),
    ("economic_code_ir", "411111111111", "41111"),
    ("uscc", "91350100M000100Y43", "91350100M000100Y44"),
    ("phone", "+86 21 5555 0101", "+86 12"),
    ("email", "sales@valve.cn", "sales@valve"),
    ("container", "CSQU3054383", "CSQU3054384"),
])
def test_validators_official_examples(client, kind, good, bad):
    ok = client.get("/api/validate", params={"kind": kind, "value": good}).json()
    no = client.get("/api/validate", params={"kind": kind, "value": bad}).json()
    assert ok["valid"] is True and no["valid"] is False, (ok, no)


def test_validator_normalisation(client):
    assert client.get("/api/validate", params={"kind": "phone", "value": "021 8888 7777"}).json()["normalized"] == "+982188887777"
    assert client.get("/api/validate", params={"kind": "iban", "value": "ir062960000000100324200001"}).json()["normalized"] == \
        "IR06 2960 0000 0010 0324 2000 01"
    assert client.get("/api/validate", params={"kind": "nope", "value": "x"}).status_code == 422


def test_duplicate_warning_while_typing(client):
    base = f"Hebei Pipe {tag()}"
    make_party(client, name_en=f"{base} Co., Ltd.", roles=["supplier"])
    r = client.get("/api/parties/duplicates", params={"name_en": f"{base} Limited"}).json()
    assert r["possible_duplicates"] and r["possible_duplicates"][0]["reason"] == "similar_name_without_legal_form"


# ---- 8.4 calculation -----------------------------------------------------------------------------------------------------

def test_calculation_in_place(client):
    from app.modules.lookup import calc

    assert client.get("/api/calc/words", params={"amount": "1250.50", "currency": "USD", "lang": "en"}).json()["words"] == \
        "One thousand two hundred fifty US dollars and fifty cents"
    fa = client.get("/api/calc/words", params={"amount": "1250", "currency": "IRR", "lang": "fa"}).json()["words"]
    assert fa.startswith("یک هزار") and fa.endswith("ریال")
    assert client.get("/api/calc/line", params={"quantity": "3", "unit_price": "10.5", "discount": "1.5", "vat_rate": "10"}).json() == \
        {"amount": "31.5", "net": "30.0", "vat": "3.00", "total": "33.00"}
    m = client.get("/api/calc/margin", params={"price": "125", "cost": "100"}).json()
    assert m == {"profit": "25", "margin_percent": "20.00", "markup_percent": "25.00"}
    assert calc.number_words_en(1_002_003) == "one million two thousand three"
    left = client.get("/api/calc/time-left", params={"deadline": "2000-01-01T00:00:00+00:00"}).json()
    assert left["overdue"] is True
    assert Decimal(calc.line(Decimal(2), Decimal("0.1"))["total"]) == Decimal("0.20")
