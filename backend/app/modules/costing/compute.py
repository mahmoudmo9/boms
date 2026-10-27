"""Cost sheet computation: pure functions on Decimal (no database, no floats).

Order of work for one sheet (all amounts converted to the sheet's pricing currency):

1. Every line amount is converted with the sheet's FX entries (``from -> to`` used as is, the reverse pair is
   divided) and rounded to the currency's decimals once, at line level. A missing pair is 422 ``fx_missing``.
2. ``total`` / ``per_unit`` lines: item-scope lines belong to their item; ``per_unit`` multiplies by the item
   quantity; case-scope ``total`` lines are allocated by value (purchase), quantity, equally or by manual shares,
   the rounding remainder going to the largest share so the shares always sum back to the line total.
3. ``percent_of_cif`` (CIF = purchase + international freight + insurance) and ``percent_of_purchase`` lines are
   computed per item from that item's base.
4. ``vat`` lines never enter the cost: a percent VAT line applies to the item's selling price before VAT; the
   sheet shows cost and price before VAT and the VAT amount separately.
5. Cost of money = cash tied up x annual rate x days / 365, where cash tied up (= exposure) is
   supplier prepayment + lines paid before receipt - customer prepayment (never below zero). Guarantee cost =
   guarantee % x total price x annual rate x guarantee days / 365. Both depend on the price (customer
   prepayment, guarantee base), so they are solved by fixed-point iteration (converges in a few rounds), and
   allocated to items by their cost.
6. Price per unit: markup cost x (1 + p) or margin cost / (1 - p) (p < 100 %), then the rounding mode; a manual
   unit price replaces it. Margin % = (price - cost) / price, markup % = (price - cost) / cost, both always shown.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

HUNDRED = Decimal(100)
ZERO = Decimal(0)
DAYS_PER_YEAR = Decimal(365)
CIF_KINDS = ("purchase", "freight_international", "insurance")
MAX_ROUNDS = 50


class CostingError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}


@dataclass
class Item:
    id: str
    name: str
    quantity: Decimal | None


@dataclass
class Line:
    id: str
    kind: str
    label: str
    scope: str  # 'case' | 'item'
    item_id: str | None
    amount: Decimal | None
    currency: str | None
    basis: str  # 'total' | 'per_unit' | 'percent_of_cif' | 'percent_of_purchase'
    percent: Decimal | None = None
    allocation: str = "by_value"
    manual_shares: dict[str, Decimal] | None = None
    paid_before_receipt: bool = False


@dataclass
class Fx:
    rate: Decimal
    as_of: date
    entry_id: str | None = None


@dataclass
class Sheet:
    currency: str
    decimals: int
    fx: dict[tuple[str, str], Fx] = field(default_factory=dict)
    supplier_prepay_percent: Decimal = ZERO
    customer_prepay_percent: Decimal = ZERO
    days_from_payment_to_receipt: int = 0
    annual_cost_of_money_percent: Decimal = ZERO
    guarantee_percent: Decimal = ZERO
    guarantee_days: int = 0
    pricing_method: str = "margin"
    target_percent: Decimal | None = None
    rounding: str = "none"
    rounding_step: Decimal | None = None
    min_acceptable_price: Decimal | None = None
    item_min_prices: dict[str, Decimal] = field(default_factory=dict)
    price_overrides: dict[str, Decimal] = field(default_factory=dict)


# ---- small helpers -------------------------------------------------------------------------------------

def quantum(decimals: int) -> Decimal:
    return Decimal(1).scaleb(-decimals)


def q(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(quantum(decimals), rounding=ROUND_HALF_UP)


def pct(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def price_from_cost(cost: Decimal, method: str, percent: Decimal) -> Decimal:
    """Markup: cost x (1 + p); margin: cost / (1 - p). Unrounded."""
    if percent < 0:
        raise CostingError("invalid_percent", "The target percentage cannot be negative")
    if method == "markup":
        return cost * (1 + percent / HUNDRED)
    if method == "margin":
        if percent >= HUNDRED:
            raise CostingError("invalid_margin", "A margin must be below 100 %", {"percent": str(percent)})
        return cost / (1 - percent / HUNDRED)
    raise CostingError("invalid_method", f"Unknown pricing method {method}")


def margin_markup(cost: Decimal, price: Decimal) -> dict:
    """Both views of the same profit: margin on the price, markup on the cost."""
    amount = price - cost
    return {"profit": amount, "margin_percent": pct(amount / price * HUNDRED) if price else None,
            "markup_percent": pct(amount / cost * HUNDRED) if cost else None}


def round_price(value: Decimal, mode: str, step: Decimal | None, decimals: int) -> Decimal:
    if mode == "none" or not step:
        return q(value, decimals)
    units = value / step
    units = units.quantize(Decimal(1), rounding=ROUND_CEILING if mode == "up" else ROUND_HALF_UP)
    return q(units * step, decimals)


def allocate(total: Decimal, weights: dict[str, Decimal], decimals: int) -> dict[str, Decimal]:
    """Split ``total`` (already rounded) by ``weights``; rounded shares sum exactly to ``total``.
    The remainder of rounding goes to the largest share (first one on a tie). All-zero weights split equally."""
    if not weights:
        return {}
    if sum(weights.values(), ZERO) <= 0:
        weights = {key: Decimal(1) for key in weights}
    weight_sum = sum(weights.values(), ZERO)
    shares = {key: q(total * w / weight_sum, decimals) for key, w in weights.items()}
    remainder = total - sum(shares.values(), ZERO)
    if remainder:
        largest = max(weights, key=lambda key: weights[key])  # max() keeps the first on a tie
        shares[largest] += remainder
    return shares


def convert(amount: Decimal, currency: str, sheet: Sheet, used: dict) -> Decimal:
    """Amount in the pricing currency (unrounded); records the FX entry used."""
    if currency == sheet.currency:
        return amount
    direct = sheet.fx.get((currency, sheet.currency))
    if direct is not None:
        used[(currency, sheet.currency)] = direct
        return amount * direct.rate
    reverse = sheet.fx.get((sheet.currency, currency))
    if reverse is not None:
        used[(sheet.currency, currency)] = reverse
        return amount / reverse.rate
    raise CostingError("fx_missing", f"No exchange rate {currency} -> {sheet.currency} on this sheet",
                       {"from_currency": currency, "to_currency": sheet.currency})


# ---- the computation -------------------------------------------------------------------------------------

def compute(sheet: Sheet, items: list[Item], lines: list[Line]) -> dict:
    d = sheet.decimals
    ids = [i.id for i in items]
    qty = {i.id: i.quantity for i in items}
    used_fx: dict = {}
    problems: list[dict] = []
    per_item: dict[str, dict[str, Decimal]] = {i: {} for i in ids}  # item -> line id -> amount
    line_out: dict[str, dict] = {}

    def add(line: Line, item_id: str, amount: Decimal) -> None:
        per_item[item_id][line.id] = per_item[item_id].get(line.id, ZERO) + amount

    def targets(line: Line) -> list[str]:
        if line.scope == "item":
            return [line.item_id] if line.item_id in per_item else []
        return ids

    fixed = [ln for ln in lines if ln.basis in ("total", "per_unit")]
    percent_lines = [ln for ln in lines if ln.basis in ("percent_of_cif", "percent_of_purchase")]

    # 1-2. fixed amounts: item lines first (purchase values drive the "by value" allocation), then case lines
    for line in sorted(fixed, key=lambda ln: (ln.scope != "item", ln.kind != "purchase")):
        if line.kind == "vat" and line.basis != "total":
            continue  # per-unit VAT is not meaningful; percent VAT is applied to the price below
        if line.amount is None:
            problems.append({"code": "amount_missing", "line_id": line.id, "label": line.label})
            continue
        converted = convert(line.amount, line.currency or sheet.currency, sheet, used_fx)
        fx = None
        if (line.currency or sheet.currency) != sheet.currency:
            pair = next(k for k in used_fx if line.currency in k)
            fx = {"from_currency": pair[0], "to_currency": pair[1], "rate": used_fx[pair].rate,
                  "as_of": used_fx[pair].as_of, "reverse": pair[0] == sheet.currency}
        shares: dict[str, Decimal] = {}
        if line.basis == "per_unit":
            for item_id in targets(line):
                if qty[item_id] is None:
                    problems.append({"code": "quantity_missing", "item_id": item_id, "line_id": line.id})
                    continue
                shares[item_id] = q(converted * qty[item_id], d)
        elif line.scope == "item":
            if line.item_id in per_item:
                shares[line.item_id] = q(converted, d)
        else:
            total = q(converted, d)
            weights = _weights(line, ids, qty, per_item, lines, problems)
            if weights is not None:
                shares = allocate(total, weights, d)
        for item_id, amount in shares.items():
            if line.kind != "vat":
                add(line, item_id, amount)
        line_out[line.id] = {"line_id": line.id, "kind": line.kind, "label": line.label, "fx": fx,
                             "total": sum(shares.values(), ZERO), "shares": shares, "vat": line.kind == "vat"}

    def base_of(item_id: str, kinds: tuple[str, ...]) -> Decimal:
        by_kind = {ln.id: ln.kind for ln in lines}
        return sum((a for lid, a in per_item[item_id].items() if by_kind.get(lid) in kinds), ZERO)

    purchase = {i: base_of(i, ("purchase",)) for i in ids}
    cif = {i: base_of(i, CIF_KINDS) for i in ids}

    # 3. percentages of CIF / purchase, per item
    vat_percent_lines = []
    for line in percent_lines:
        if line.kind == "vat":
            vat_percent_lines.append(line)
            continue
        if line.percent is None:
            problems.append({"code": "percent_missing", "line_id": line.id, "label": line.label})
            continue
        base = cif if line.basis == "percent_of_cif" else purchase
        shares = {item_id: q(base[item_id] * line.percent / HUNDRED, d) for item_id in targets(line)}
        for item_id, amount in shares.items():
            add(line, item_id, amount)
        line_out[line.id] = {"line_id": line.id, "kind": line.kind, "label": line.label, "fx": None,
                             "percent": line.percent, "base": line.basis, "total": sum(shares.values(), ZERO),
                             "shares": shares, "vat": False}

    base_cost = {i: sum(per_item[i].values(), ZERO) for i in ids}
    kinds = {ln.id: ln.kind for ln in lines}
    flagged = {ln.id for ln in lines if ln.paid_before_receipt and ln.kind not in ("purchase", "vat")}
    purchase_total = sum(purchase.values(), ZERO)
    supplier_prepayment = q(purchase_total * sheet.supplier_prepay_percent / HUNDRED, d)
    paid_before = sum((a for i in ids for lid, a in per_item[i].items() if lid in flagged), ZERO)
    rate = sheet.annual_cost_of_money_percent / HUNDRED

    # 5-6. price <-> cost of money / guarantee: fixed-point iteration
    com_shares = {i: ZERO for i in ids}
    guarantee_shares = {i: ZERO for i in ids}
    priced: dict[str, dict] = {}
    cash = com = guarantee = customer_prepayment = ZERO
    problems_out: list[dict] = []
    for _ in range(MAX_ROUNDS):
        problems_out = []
        priced = _price_items(sheet, items, base_cost, com_shares, guarantee_shares, problems_out)
        price_total = sum((p["total_price"] for p in priced.values() if p["total_price"] is not None), ZERO)
        customer_prepayment = q(price_total * sheet.customer_prepay_percent / HUNDRED, d)
        cash = max(ZERO, supplier_prepayment + paid_before - customer_prepayment)
        new_com = q(cash * rate * Decimal(sheet.days_from_payment_to_receipt) / DAYS_PER_YEAR, d)
        new_guarantee = q(price_total * sheet.guarantee_percent / HUNDRED * rate * Decimal(sheet.guarantee_days)
                          / DAYS_PER_YEAR, d)
        if new_com == com and new_guarantee == guarantee:
            break  # the prices above already include these amounts
        com, guarantee = new_com, new_guarantee
        com_shares = allocate(com, base_cost, d) if ids else {}
        guarantee_shares = allocate(guarantee, base_cost, d) if ids else {}
    problems.extend(problems_out)

    # VAT on the price (percent) or as a fixed amount, never part of the cost
    vat_by_item = {i: ZERO for i in ids}
    for line_id, out in line_out.items():
        if out["vat"]:
            for item_id, amount in out["shares"].items():
                vat_by_item[item_id] += amount
    for line in vat_percent_lines:
        if line.percent is None:
            problems.append({"code": "percent_missing", "line_id": line.id, "label": line.label})
            continue
        shares = {i: q((priced[i]["total_price"] or ZERO) * line.percent / HUNDRED, d) for i in targets(line)}
        for item_id, amount in shares.items():
            vat_by_item[item_id] += amount
        line_out[line.id] = {"line_id": line.id, "kind": "vat", "label": line.label, "fx": None,
                             "percent": line.percent, "base": "price", "total": sum(shares.values(), ZERO),
                             "shares": shares, "vat": True}

    item_rows = []
    for item in items:
        p = priced[item.id]
        row = {"item_id": item.id, "name": item.name, "quantity": item.quantity,
               "purchase": purchase[item.id], "cif": cif[item.id],
               "lines": [{"line_id": lid, "kind": kinds.get(lid), "amount": a} for lid, a in per_item[item.id].items()],
               "cost_of_money": com_shares.get(item.id, ZERO), "guarantee": guarantee_shares.get(item.id, ZERO),
               "vat": vat_by_item[item.id], **p}
        item_rows.append(row)

    landed_total = sum((r["landed_cost"] for r in item_rows), ZERO)
    priced_rows = [r for r in item_rows if r["total_price"] is not None]
    price_total = sum((r["total_price"] for r in priced_rows), ZERO)
    vat_total = sum(vat_by_item.values(), ZERO)
    totals = {"purchase": purchase_total, "cif": sum(cif.values(), ZERO), "cost_before_vat": landed_total,
              "cost_of_money": com, "guarantee": guarantee, "vat": vat_total,
              "price_before_vat": price_total if priced_rows else None,
              "price_with_vat": price_total + vat_total if priced_rows else None,
              **({"profit": None, "margin_percent": None, "markup_percent": None} if not priced_rows or
                 len(priced_rows) != len(item_rows) else margin_markup(landed_total, price_total))}
    below_minimum = (sheet.min_acceptable_price is not None and totals["price_before_vat"] is not None
                     and totals["price_before_vat"] < sheet.min_acceptable_price)
    used = [{"from_currency": a, "to_currency": b, "rate": fx.rate, "as_of": fx.as_of, "entry_id": fx.entry_id}
            for (a, b), fx in used_fx.items()]
    return {
        "currency": sheet.currency, "decimals": d,
        "items": item_rows,
        "lines": list(line_out.values()),
        "totals": totals,
        "below_minimum": below_minimum,
        "exposure": {"supplier_prepayment": supplier_prepayment, "paid_before_receipt": paid_before,
                     "customer_prepayment": customer_prepayment, "exposure": cash},
        "cost_of_money": {"cash_tied_up": cash, "annual_percent": sheet.annual_cost_of_money_percent,
                          "days": sheet.days_from_payment_to_receipt, "amount": com},
        "guarantee": {"percent": sheet.guarantee_percent, "days": sheet.guarantee_days,
                      "annual_percent": sheet.annual_cost_of_money_percent, "amount": guarantee},
        "fx_used": used,
        "newest_fx_as_of": max((u["as_of"] for u in used), default=None),
        "oldest_fx_as_of": min((u["as_of"] for u in used), default=None),
        "problems": problems,
    }


def _weights(line: Line, ids: list[str], qty: dict, per_item: dict, lines: list[Line], problems: list) -> dict | None:
    if line.allocation == "equal":
        return {i: Decimal(1) for i in ids}
    if line.allocation == "by_quantity":
        missing = [i for i in ids if qty[i] is None]
        if missing:
            problems.extend({"code": "quantity_missing", "item_id": i, "line_id": line.id} for i in missing)
            return None
        return {i: qty[i] for i in ids}
    if line.allocation == "manual":
        shares = {i: Decimal(str((line.manual_shares or {}).get(i, 0))) for i in ids}
        if sum(shares.values(), ZERO) <= 0:
            problems.append({"code": "manual_shares_missing", "line_id": line.id, "label": line.label})
            return None
        return shares
    purchase_ids = {ln.id for ln in lines if ln.kind == "purchase"}
    return {i: sum((a for lid, a in per_item[i].items() if lid in purchase_ids), ZERO) for i in ids}


def _price_items(sheet: Sheet, items: list[Item], base_cost: dict, com: dict, guarantee: dict, problems: list) -> dict:
    d = sheet.decimals
    out = {}
    for item in items:
        landed = base_cost[item.id] + com.get(item.id, ZERO) + guarantee.get(item.id, ZERO)
        row = {"landed_cost": landed, "unit_cost": None, "unit_price": None, "total_price": None, "manual": False,
               "profit": None, "margin_percent": None, "markup_percent": None, "min_unit_price": None,
               "below_minimum": False, "priced": False}
        override = sheet.price_overrides.get(item.id)
        if item.quantity is None or item.quantity <= 0:
            problems.append({"code": "quantity_missing", "item_id": item.id})
            out[item.id] = row
            continue
        unit_cost = landed / item.quantity
        row["unit_cost"] = q(unit_cost, max(d, 4))
        if override is not None:
            unit_price, row["manual"] = q(Decimal(override), d), True
        elif sheet.target_percent is None:
            out[item.id] = row
            continue
        elif landed <= 0:
            problems.append({"code": "cost_missing", "item_id": item.id})
            out[item.id] = row
            continue
        else:
            unit_price = round_price(price_from_cost(unit_cost, sheet.pricing_method, sheet.target_percent),
                                     sheet.rounding, sheet.rounding_step, d)
        total = q(unit_price * item.quantity, d)
        minimum = sheet.item_min_prices.get(item.id)
        row.update(unit_price=unit_price, total_price=total, priced=True, **margin_markup(landed, total),
                   min_unit_price=minimum, below_minimum=minimum is not None and unit_price < Decimal(minimum))
        out[item.id] = row
    return out
