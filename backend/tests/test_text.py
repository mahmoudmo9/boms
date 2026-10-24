import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.text import normalize_fa

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "normalize_fa.json").read_text(encoding="utf-8"))


def test_python_and_sql_agree(db):
    for value in FIXTURES:
        sql_value = db.execute(text("SELECT core.normalize_fa(:v)"), {"v": value}).scalar()
        assert sql_value == normalize_fa(value), f"mismatch for {value!r}"


def test_sql_function_is_immutable(db):
    volatility = db.execute(
        text("SELECT provolatile FROM pg_proc WHERE oid = 'core.normalize_fa(text)'::regprocedure")
    ).scalar()
    assert volatility == "i"


def test_null_passthrough(db):
    assert normalize_fa(None) is None
    assert db.execute(text("SELECT core.normalize_fa(NULL)")).scalar() is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("علي", "علی"),
        ("كتاب", "کتاب"),
        ("مدرسة", "مدرسه"),
        ("مـــحـمـد", "محمد"),
        ("مُحَمَّد", "محمد"),
        ("۱۲۳ و ٤٥٦", "123 و 456"),
        ("می‌خواهم", "می خواهم"),
        ("  a \t\n  b  ", "a b"),
        ("Hello WORLD", "hello world"),
        ("ÉCOLE", "école"),
    ],
)
def test_rules(raw, expected):
    assert normalize_fa(raw) == expected
