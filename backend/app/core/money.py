"""Money conventions.

Database: amounts NUMERIC(18,4) plus a currency code column (sys.currency.code);
FX rates NUMERIC(20,10). Python: Decimal only - float is rejected everywhere.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

AMOUNT_QUANT = Decimal("0.0001")  # NUMERIC(18,4)
RATE_QUANT = Decimal("0.0000000001")  # NUMERIC(20,10)
AMOUNT_MAX = Decimal("99999999999999.9999")


def to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float is not allowed for money; use Decimal or str")
    return Decimal(value)


def fx_rate(value: Decimal | int | str) -> Decimal:
    return to_decimal(value).quantize(RATE_QUANT, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        amount = to_decimal(self.amount).quantize(AMOUNT_QUANT, rounding=ROUND_HALF_EVEN)
        if abs(amount) > AMOUNT_MAX:
            raise ValueError("amount exceeds NUMERIC(18,4)")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be an ISO 4217 code")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "currency", self.currency.upper())

    def _same(self, other: "Money") -> None:
        if not isinstance(other, Money) or other.currency != self.currency:
            raise ValueError("cannot combine different currencies")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int | str) -> "Money":
        return Money(self.amount * to_decimal(factor), self.currency)

    def convert(self, rate: Decimal | int | str, to_currency: str) -> "Money":
        return Money(self.amount * fx_rate(rate), to_currency)
