"""Python and SQL normalize_fa must produce identical output on the shared fixtures."""

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.text import normalize_fa

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "normalize_fa.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("raw", "expected"), FIXTURES)
def test_python_normalize(raw, expected):
    assert normalize_fa(raw) == expected


def test_sql_matches_python_on_fixtures(db):
    for raw, expected in FIXTURES:
        sql_out = db.execute(text("SELECT core.normalize_fa(:v)"), {"v": raw}).scalar()
        assert sql_out == normalize_fa(raw) == expected, raw


def test_sql_matches_python_on_all_bmp_letters(db):
    """Broader check: every Arabic-block and Latin char, plus the mapped/space characters."""
    sample = "".join(chr(c) for c in range(0x20, 0x250)) + "".join(chr(c) for c in range(0x600, 0x700))
    sample += "​‌‍‎‏⁠﻿       　"
    chunks = [sample[i : i + 64] for i in range(0, len(sample), 64)]
    for chunk in chunks:
        sql_out = db.execute(text("SELECT core.normalize_fa(:v)"), {"v": chunk}).scalar()
        assert sql_out == normalize_fa(chunk), chunk


def test_null_passthrough(db):
    assert normalize_fa(None) is None
    assert db.execute(text("SELECT core.normalize_fa(NULL)")).scalar() is None


def test_sql_function_is_immutable(db):
    vol = db.execute(text("SELECT provolatile FROM pg_proc WHERE proname = 'normalize_fa'")).scalar()
    assert vol == "i"
