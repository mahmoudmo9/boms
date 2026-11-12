"""v0.10.0 milestone 5: the company's bank details as structured fields (bank name, account holder, IBAN and BIC with
validation, other lines); the letterhead keeps printing `company.bank_details`, now composed from the fields."""

BANK = {"bank_name": {"fa": "بانک ملت", "en": "Bank Mellat"}, "account_holder": {"fa": "بازرگانی نمونه", "en": "Sample Trading"},
        "iban": "gb82 west 1234 5698 7654 32", "bic": "bkmtirth", "other": {"en": "Branch 1234"}}


def test_bank_fields_are_validated_normalized_and_printed_as_before(client):
    r = client.patch("/api/settings", json={"company.bank": BANK})
    assert r.status_code == 200, r.text
    out = r.json()["values"]
    assert out["company.bank"]["iban"] == "GB82 WEST 1234 5698 7654 32" and out["company.bank"]["bic"] == "BKMTIRTH"
    text = out["company.bank_details"]
    assert text["en"].splitlines() == ["Bank Mellat", "Account holder: Sample Trading", "IBAN: GB82 WEST 1234 5698 7654 32",
                                       "BIC / SWIFT: BKMTIRTH", "Branch 1234"]
    assert text["fa"].splitlines()[0] == "بانک ملت" and "شبا (IBAN): GB82 WEST 1234 5698 7654 32" in text["fa"]
    assert text["fa"].splitlines()[-1] == "Branch 1234"            # a line typed in one language prints in both


def test_bad_iban_or_bic_is_refused_and_changes_nothing(client):
    before = client.get("/api/settings").json()["values"]["company.bank_details"]
    for bad in ({"iban": "GB82 WEST 1234 5698 7654 33"}, {"bic": "BKM1"}, {"iban": "x" * 70}, {"colour": "red"}):
        r = client.patch("/api/settings", json={"company.bank": {**BANK, **bad} if "colour" not in bad else bad})
        assert r.status_code == 422, bad
        assert "company.bank" in r.json()["error"]["details"]["fields"]
    assert client.get("/api/settings").json()["values"]["company.bank_details"] == before


def test_free_text_still_accepted_and_empty_fields_are_allowed(client):
    r = client.patch("/api/settings", json={"company.bank": {"bank_name": {"en": "Only a name"}}})
    assert r.status_code == 200 and r.json()["values"]["company.bank_details"]["en"] == "Only a name"
    r = client.patch("/api/settings", json={"company.bank": None, "company.bank_details": {"fa": "متن آزاد", "en": "Free text"}})
    assert r.status_code == 200
    assert r.json()["values"]["company.bank"] is None and r.json()["values"]["company.bank_details"]["en"] == "Free text"
