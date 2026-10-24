from decimal import Decimal

import pytest

from app.core.money import Money
from app.core.time import ensure_aware


def test_money_uses_decimal_and_rounds_to_4_places():
    m = Money("10.123456", "USD")
    assert m.amount == Decimal("10.1235")
    assert (m + Money("1", "USD")).amount == Decimal("11.1235")


def test_money_rejects_float_and_mixed_currency():
    with pytest.raises(TypeError):
        Money(1.5, "USD")
    with pytest.raises(ValueError):
        Money("1", "USD") + Money("1", "EUR")
    with pytest.raises(ValueError):
        Money("1", "usd")


def test_money_convert():
    assert Money("2", "USD").convert("1050000.5", "IRR") == Money("2100001", "IRR")


def test_naive_datetime_rejected():
    from datetime import datetime

    with pytest.raises(ValueError):
        ensure_aware(datetime(2026, 1, 1))
