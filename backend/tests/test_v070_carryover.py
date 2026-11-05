"""v0.7.0 section 0: Persian output documents always use Jalali dates and Persian digits, English ones Gregorian
dates and Latin digits, whatever the user's calendar and digit settings (the UI keeps following the user)."""
import re

import pytest

from app.modules.sourcing.jalali import to_jalali
from tests.test_quotes import new_quote, ready_case
from tests.test_tenders_m3 import new_proposal, tender_case

FA = re.compile("[۰-۹]")


@pytest.fixture
def user_settings(client):
    def set_(calendar, digits):
        assert client.patch("/api/me", json={"calendar": calendar, "digits": digits}).status_code == 200
    yield set_
    client.patch("/api/me", json={"calendar": "gregorian", "digits": "latin"})


def jalali_year() -> str:
    from datetime import date
    return str(to_jalali(date.today())[0])


def test_fa_quote_with_a_gregorian_latin_user_shows_jalali_and_persian_digits(client, user_settings):
    user_settings("gregorian", "latin")
    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case, language="fa")
    page = client.get(f"/api/quotes/{quote['id']}/print").text
    fa_year = jalali_year().translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert fa_year in page
    from datetime import date
    assert date.today().isoformat() not in page            # no Gregorian date
    body = re.sub(r"<style.*?</style>", "", page, flags=re.S)
    totals = re.findall(r"[0-9۰-۹][0-9۰-۹,٬.]*[0-9۰-۹]", re.sub(r"<[^>]+>", " ", body))
    assert any(FA.search(x) for x in totals)
    # the terms text of the fa quote uses Persian digits too
    detail = client.get(f"/api/quotes/{quote['id']}").json()
    assert re.search("[۰-۹]{4}/[۰-۹]{2}/[۰-۹]{2}", detail["terms_text"] or "")
    assert not re.search("[0-9]{4}/[0-9]{2}/[0-9]{2}", detail["terms_text"] or "")


def test_en_quote_with_a_jalali_user_shows_gregorian_and_latin(client, user_settings):
    case, items, party, sheet = ready_case(client)
    quote = new_quote(client, case, language="en")
    user_settings("jalali", "fa")
    page = client.get(f"/api/quotes/{quote['id']}/print").text
    from datetime import date
    assert date.today().isoformat() in page
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", page, flags=re.S))
    assert not FA.search(text.replace("پیش‌نویس", ""))


def test_fa_tender_proposal_with_a_gregorian_latin_user_shows_jalali_and_persian_digits(client, user_settings):
    case, items, party, sheet, t = tender_case(client)
    p = new_proposal(client, t)
    user_settings("gregorian", "latin")
    page = client.get(f"/api/tender-proposals/{p['id']}/print").text
    fa_year = jalali_year().translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    assert fa_year in page
    from datetime import date
    assert date.today().isoformat() not in page


def test_the_ui_still_follows_the_user(client, user_settings):
    """Only output documents are fixed: /api/me keeps the user's own choice."""
    user_settings("gregorian", "latin")
    me = client.get("/api/me").json()
    assert me["calendar"] == "gregorian" and me["digits"] == "latin"
