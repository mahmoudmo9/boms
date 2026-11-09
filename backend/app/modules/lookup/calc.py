"""Calculation in place (v0.9.0 section 8.4): the same code the backend uses for its checks, served to the forms.

Line and document totals, margin and markup side by side, conversion at the latest rate entered on the case, the
amount in words (fa and en) and the time left to a deadline. Money is ``Decimal`` throughout."""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
SCALES = [(10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")]
CURRENCY_EN = {"USD": ("US dollar", "US dollars", "cent", "cents"), "EUR": ("euro", "euros", "cent", "cents"),
               "AED": ("UAE dirham", "UAE dirhams", "fils", "fils"), "CNY": ("yuan", "yuan", "fen", "fen"),
               "IRR": ("Iranian rial", "Iranian rials", None, None), "GBP": ("pound sterling", "pounds sterling", "penny", "pence")}


def _below_thousand(n: int) -> str:
    words = []
    if n >= 100:
        words.append(f"{ONES[n // 100]} hundred")
        n %= 100
    if n >= 20:
        words.append(TENS[n // 10] + (f"-{ONES[n % 10]}" if n % 10 else ""))
    elif n:
        words.append(ONES[n])
    return " ".join(words)


def number_words_en(n: int) -> str:
    if n == 0:
        return "zero"
    parts = []
    for size, name in SCALES:
        if n >= size:
            parts.append(f"{_below_thousand(n // size)} {name}")
            n %= size
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def amount_in_words(amount: Decimal, currency: str, lang: str) -> str:
    amount = Decimal(amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
    whole, cents = int(amount), int((amount - int(amount)) * 100)
    if lang == "fa":
        from app.modules.quotes.output import total_in_words

        return total_in_words(Decimal(whole), currency)
    one, many, minor_one, minor_many = CURRENCY_EN.get(currency, (currency, currency, None, None))
    text = f"{number_words_en(whole)} {one if whole == 1 else many}"
    if cents and minor_one:
        text += f" and {number_words_en(cents)} {minor_one if cents == 1 else minor_many}"
    return text[0].upper() + text[1:]


def line(quantity: Decimal, unit_price: Decimal, discount: Decimal = Decimal(0), vat_rate: Decimal = Decimal(0)) -> dict:
    amount = quantity * unit_price
    net = amount - discount
    vat = (net * vat_rate / Decimal(100)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"amount": str(amount), "net": str(net), "vat": str(vat), "total": str(net + vat)}


def margin_markup(price: Decimal, cost: Decimal) -> dict:
    """Margin = profit / price; markup = profit / cost (both shown: the owner reads both)."""
    profit = price - cost
    pct = lambda a, b: str((a / b * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)) if b else None  # noqa: E731
    return {"profit": str(profit), "margin_percent": pct(profit, price), "markup_percent": pct(profit, cost)}


def convert(db, case_id, amount: Decimal, from_currency: str, to_currency: str) -> dict:
    """At the latest rate entered on the case (the costing FX entries); none entered -> no conversion."""
    from sqlalchemy import text

    if from_currency == to_currency:
        return {"amount": str(amount), "rate": "1", "source": None}
    row = db.execute(text(
        "SELECT e.rate, e.from_currency, e.to_currency, s.id FROM ops.fx_rate_entry e JOIN ops.cost_sheet s ON s.id = e.cost_sheet_id "
        "WHERE s.case_id = :c AND ((e.from_currency = :f AND e.to_currency = :t) OR (e.from_currency = :t AND e.to_currency = :f)) "
        "ORDER BY e.as_of DESC NULLS LAST, e.created_at DESC LIMIT 1"), {"c": case_id, "f": from_currency, "t": to_currency}).mappings().first()
    if row is None:
        return {"amount": None, "rate": None, "source": None}
    rate = Decimal(row["rate"]) if row["from_currency"] == from_currency else Decimal(1) / Decimal(row["rate"])
    return {"amount": str((amount * rate).quantize(Decimal("0.01"), ROUND_HALF_UP)), "rate": str(rate),
            "source": {"kind": "cost_sheet", "id": str(row["id"])}}


def time_left(deadline: datetime, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    seconds = int((deadline - now).total_seconds())
    return {"seconds": seconds, "days": seconds // 86400, "hours": (abs(seconds) % 86400) // 3600, "overdue": seconds < 0}
