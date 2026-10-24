"""Money conventions.

Database: amounts are ``NUMERIC(18,4)`` next to a ``currency`` code column;
FX rates are ``NUMERIC(20,10)``. Python: ``Decimal`` only. Floats are rejected.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

AMOUNT_PLACES = Decimal("0.0001")
RATE_PLACES = Decimal("0.0000000001")


def to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float is not allowed for money; use Decimal or str")
    try:
        result = Decimal(value) if not isinstance(value, Decimal) else value
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("amount must be finite")
    return result


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self):
        amount = to_decimal(self.amount).quantize(AMOUNT_PLACES, rounding=ROUND_HALF_EVEN)
        if len(self.currency) != 3 or not self.currency.isalpha() or not self.currency.isupper():
            raise ValueError(f"invalid currency code: {self.currency!r}")
        object.__setattr__(self, "amount", amount)

    def _check(self, other: "Money") -> None:
        if not isinstance(other, Money):
            raise TypeError("can only combine Money with Money")
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch: {self.currency} vs {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int | str) -> "Money":
        return Money(self.amount * to_decimal(factor), self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def convert(self, rate: Decimal | str, to_currency: str) -> "Money":
        """Convert with an FX rate expressed as units of ``to_currency`` per 1 unit of self."""
        rate_d = to_decimal(rate).quantize(RATE_PLACES, rounding=ROUND_HALF_EVEN)
        return Money(self.amount * rate_d, to_currency)

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"
