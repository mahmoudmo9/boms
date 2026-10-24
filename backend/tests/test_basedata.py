"""Seed data, base data service, money helper and single-user constraint."""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError, Conflict
from app.core.money import Money
from app.modules.system import basedata, seed_data


def test_seed_counts(db):
    # Other tests may add rows, so check that every seeded code is present.
    seeded = {
        "country": ("iso2", [r["iso2"] for r in seed_data.countries()]),
        "currency": ("code", [r["code"] for r in seed_data.currencies()]),
        "unit": ("code", [r["code"] for r in seed_data.units()]),
    }
    for table, (pk, codes) in seeded.items():
        found = db.scalar(text(f"SELECT count(*) FROM sys.{table} WHERE {pk} = ANY(:c)"), {"c": codes})
        assert found == len(codes)
    assert len(seeded["country"][1]) == 249
    assert len(seeded["currency"][1]) >= 150 and len(seeded["unit"][1]) >= 30
    iran = db.execute(text("SELECT iso3, name_fa, sort_order FROM sys.country WHERE iso2='IR'")).one()
    assert (iran.iso3, iran.name_fa, iran.sort_order) == ("IRN", "ایران", 1)
    for code in ("IRR", "USD", "EUR", "AED", "CNY", "TRY", "GBP", "RUB", "INR", "JPY", "KRW"):
        assert db.scalar(text("SELECT name_fa FROM sys.currency WHERE code=:c"), {"c": code})


def test_seed_data_unique():
    c = seed_data.countries()
    assert len({r["iso2"] for r in c}) == len({r["iso3"] for r in c}) == len(c) == 249
    cur = seed_data.currencies()
    assert len({r["code"] for r in cur}) == len(cur)
    assert len({r["code"] for r in seed_data.units()}) == len(seed_data.units())


def test_seed_is_idempotent(db):
    counts = seed_data.seed(db.connection())
    assert counts == {"sys.country": 0, "sys.currency": 0, "sys.unit": 0}


def test_unit_factors(db):
    f = dict(db.execute(text("SELECT code, base_factor FROM sys.unit")).all())
    assert f["t"] == Decimal("1000") and f["g"] == Decimal("0.001") and f["l"] == Decimal("0.001")
    assert f["lb"] == Decimal("0.45359237") and f["h"] == Decimal("3600")


def test_search_both_languages(db):
    assert any(c.iso2 == "DE" for c in basedata.list_items(db, "countries", q="آلمان"))
    assert any(c.iso2 == "DE" for c in basedata.list_items(db, "countries", q="germ"))
    # Arabic yeh/kaf in the query still match Persian names.
    assert any(c.code == "kg" for c in basedata.list_items(db, "units", q="كيلوگرم"))


def test_create_and_duplicate(db):
    basedata.create_item(db, "units", {"code": "Ream", "name_fa": "بند", "name_en": "Ream", "kind": "count", "base_factor": "500"})
    assert db.scalar(text("SELECT base_factor FROM sys.unit WHERE code='ream'")) == Decimal("500")
    with pytest.raises(Conflict):
        basedata.create_item(db, "units", {"code": "ream", "name_fa": "x", "name_en": "x", "kind": "count", "base_factor": "1"})
    with pytest.raises(AppError):
        basedata.create_item(db, "units", {"code": "bad", "name_fa": "x", "name_en": "x", "kind": "nope", "base_factor": "1"})
    db.rollback()


def test_single_user_constraint(user, db):
    assert db.scalar(text("SELECT count(*) FROM sys.app_user")) == 1
    with pytest.raises(IntegrityError):
        db.execute(text("INSERT INTO sys.app_user (username, password_hash) VALUES ('b', 'y')"))
    db.rollback()


def test_money_rules():
    assert Money("10.123456", "usd").amount == Decimal("10.1235")
    assert (Money("1", "USD") + Money("2.5", "USD")).amount == Decimal("3.5000")
    with pytest.raises(TypeError):
        Money(1.5, "USD")
    with pytest.raises(ValueError):
        Money("1", "USD") + Money("1", "EUR")
