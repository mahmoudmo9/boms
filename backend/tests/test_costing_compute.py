"""Costing math (pure functions, Decimal fixtures, expected values worked out by hand in the comments)."""

from datetime import date
from decimal import Decimal as D

import pytest

from app.modules.costing.compute import (
    CostingError,
    Fx,
    Item,
    Line,
    Sheet,
    allocate,
    compute,
    margin_markup,
    price_from_cost,
    round_price,
)


def test_margin_vs_markup_from_the_technical_decisions():
    # cost 81,000: markup 20 % -> 81,000 x 1.2 = 97,200; margin 20 % -> 81,000 / 0.8 = 101,250
    assert price_from_cost(D(81000), "markup", D(20)) == D(97200)
    assert price_from_cost(D(81000), "margin", D(20)) == D(101250)
    view = margin_markup(D(81000), D(101250))
    assert (view["profit"], view["margin_percent"], view["markup_percent"]) == (D(20250), D("20.00"), D("25.00"))
    view = margin_markup(D(81000), D(97200))
    assert (view["margin_percent"], view["markup_percent"]) == (D("16.67"), D("20.00"))


@pytest.mark.parametrize("percent", [D(100), D(150)])
def test_margin_of_100_percent_or_more_is_rejected(percent):
    with pytest.raises(CostingError) as err:
        price_from_cost(D(10), "margin", percent)
    assert err.value.code == "invalid_margin"


def test_allocation_sums_back_without_rounding_loss():
    # 100.00 in three equal parts: 33.33 x 3 = 99.99, the 0.01 remainder goes to the largest share (first on a tie)
    assert allocate(D("100.00"), {"a": D(1), "b": D(1), "c": D(1)}, 2) == {"a": D("33.34"), "b": D("33.33"), "c": D("33.33")}
    # by quantity 2 : 3 -> 40 / 60
    assert allocate(D(100), {"a": D(2), "b": D(3)}, 0) == {"a": D(40), "b": D(60)}
    # manual 1 : 2 of 10 IRR (0 decimals): 3.33 -> 3, 6.67 -> 7, sum 10
    assert allocate(D(10), {"a": D(1), "b": D(2)}, 0) == {"a": D(3), "b": D(7)}
    # by value with an odd split: 1000 by 1 : 6 -> 142.86 / 857.14 (exact sum 1000.00)
    shares = allocate(D("1000.00"), {"a": D(1), "b": D(6)}, 2)
    assert sum(shares.values()) == D("1000.00") and shares == {"a": D("142.86"), "b": D("857.14")}
    # remainder to the largest share: 0.05 in 3 parts of weights 1, 1, 2 -> 0.01, 0.01, 0.03 (0.0125 rounds to 0.01)
    shares = allocate(D("0.05"), {"a": D(1), "b": D(1), "c": D(2)}, 2)
    assert shares == {"a": D("0.01"), "b": D("0.01"), "c": D("0.03")} and sum(shares.values()) == D("0.05")
    # all-zero weights split equally
    assert allocate(D(9), {"a": D(0), "b": D(0), "c": D(0)}, 0) == {"a": D(3), "b": D(3), "c": D(3)}


@pytest.mark.parametrize("mode,step,decimals,expected", [
    ("none", None, 0, D(1235)),     # 1234.5 half-up to whole rials
    ("none", None, 2, D("1234.50")),
    ("nearest", D(100), 0, D(1200)),
    ("up", D(100), 0, D(1300)),
    ("nearest", D("0.05"), 2, D("1234.50")),
    ("up", D(1000), 0, D(2000)),
])
def test_rounding_modes(mode, step, decimals, expected):
    assert round_price(D("1234.5"), mode, step, decimals) == expected


def _sheet(**kw):
    base = {"currency": "USD", "decimals": 2, "target_percent": D(0), "pricing_method": "markup"}
    return Sheet(**{**base, **kw})


def test_fx_missing_names_the_pair():
    lines = [Line("p", "purchase", "Buy", "item", "a", D(10), "EUR", "per_unit")]
    with pytest.raises(CostingError) as err:
        compute(_sheet(), [Item("a", "A", D(1))], lines)
    assert err.value.code == "fx_missing"
    assert err.value.details == {"from_currency": "EUR", "to_currency": "USD"}


def test_fx_direct_and_reverse_pairs_and_irr_zero_decimals():
    # USD 12.5 x 10 at 600,000 IRR/USD = 75,000,000; EUR 3 x 2 with the reverse pair IRR->EUR 0.0000015 = 4,000,000
    sheet = _sheet(currency="IRR", decimals=0, fx={("USD", "IRR"): Fx(D(600000), date(2026, 10, 25)),
                                                   ("IRR", "EUR"): Fx(D("0.0000015"), date(2026, 10, 26))})
    lines = [Line("p1", "purchase", "Buy", "item", "a", D("12.5"), "USD", "per_unit"),
             Line("p2", "purchase", "Buy", "item", "b", D(3), "EUR", "per_unit")]
    result = compute(sheet, [Item("a", "A", D(10)), Item("b", "B", D(2))], lines)
    purchase = {r["item_id"]: r["purchase"] for r in result["items"]}
    assert purchase == {"a": D(75000000), "b": D(4000000)}
    assert result["newest_fx_as_of"] == date(2026, 10, 26) and result["oldest_fx_as_of"] == date(2026, 10, 25)
    assert all(r["total_price"] == r["total_price"].quantize(D(1)) for r in result["items"])


def test_duty_on_cif_per_item():
    # A: purchase 1000, freight 100 and insurance 10 (by value 1000 : 3000 -> 25 / 2.50) -> CIF 1027.50, duty 4 % = 41.10
    # B: purchase 3000, freight 75, insurance 7.50 -> CIF 3082.50, duty 4 % = 123.30
    lines = [Line("pa", "purchase", "Buy", "item", "a", D(1000), "USD", "total"),
             Line("pb", "purchase", "Buy", "item", "b", D(3000), "USD", "total"),
             Line("f", "freight_international", "Freight", "case", None, D(100), "USD", "total"),
             Line("i", "insurance", "Insurance", "case", None, D(10), "USD", "total"),
             Line("d", "customs_duty", "Duty", "case", None, None, None, "percent_of_cif", percent=D(4)),
             Line("c", "customs_clearance", "Clearance", "case", None, D(40), "USD", "total", allocation="equal")]
    result = compute(_sheet(), [Item("a", "A", D(1)), Item("b", "B", D(1))], lines)
    rows = {r["item_id"]: r for r in result["items"]}
    assert (rows["a"]["cif"], rows["b"]["cif"]) == (D("1027.50"), D("3082.50"))
    duty = next(ln for ln in result["lines"] if ln["line_id"] == "d")
    assert duty["shares"] == {"a": D("41.10"), "b": D("123.30")} and duty["total"] == D("164.40")
    # clearance split equally 20 / 20; landed A = 1027.50 + 41.10 + 20 = 1088.60
    assert rows["a"]["landed_cost"] == D("1088.60") and rows["b"]["landed_cost"] == D("3225.80")
    assert result["totals"]["cost_before_vat"] == D("4314.40")


def test_percent_of_purchase_and_vat_kept_separate():
    # purchase 2000, bank fee 1.5 % of purchase = 30; margin 20 % -> 2030 / 0.8 = 2537.50; VAT 10 % of price = 253.75
    lines = [Line("p", "purchase", "Buy", "item", "a", D(2000), "USD", "total"),
             Line("b", "bank_fees", "Bank", "case", None, None, None, "percent_of_purchase", percent=D("1.5")),
             Line("v", "vat", "VAT", "case", None, None, None, "percent_of_cif", percent=D(10))]
    result = compute(_sheet(pricing_method="margin", target_percent=D(20)), [Item("a", "A", D(1))], lines)
    t = result["totals"]
    assert (t["cost_before_vat"], t["price_before_vat"], t["vat"], t["price_with_vat"]) == \
        (D(2030), D("2537.50"), D("253.75"), D("2791.25"))
    assert (t["margin_percent"], t["markup_percent"]) == (D("20.00"), D("25.00"))


def test_cost_of_money_guarantee_and_exposure():
    # purchase 1000 (supplier prepays 30 % = 300), freight 100 paid before receipt -> cash tied up 400
    # cost of money = 400 x 24 % x 90 / 365 = 23.6712... -> 23.67
    # guarantee = 10 % x price x 24 % x 180 / 365 on the final price (markup 0: price = cost incl. both)
    sheet = _sheet(supplier_prepay_percent=D(30), days_from_payment_to_receipt=90, annual_cost_of_money_percent=D(24),
                   guarantee_percent=D(10), guarantee_days=180)
    lines = [Line("p", "purchase", "Buy", "item", "a", D(1000), "USD", "total"),
             Line("f", "freight_international", "Freight", "case", None, D(100), "USD", "total", paid_before_receipt=True)]
    result = compute(sheet, [Item("a", "A", D(1))], lines)
    assert result["exposure"] == {"supplier_prepayment": D(300), "paid_before_receipt": D(100),
                                  "customer_prepayment": D(0), "exposure": D(400)}
    assert result["cost_of_money"]["amount"] == D("23.67")
    price = result["totals"]["price_before_vat"]
    guarantee = result["guarantee"]["amount"]
    assert guarantee == (price * D("0.10") * D("0.24") * 180 / 365).quantize(D("0.01"))
    assert price == D(1100) + D("23.67") + guarantee  # markup 0 -> price equals the full landed cost
    assert guarantee == D("13.46")


def test_exposure_floor_at_zero_with_customer_prepayment():
    # customer prepays 100 % of the price: 300 + 0 - price < 0 -> exposure 0 and no cost of money
    sheet = _sheet(supplier_prepay_percent=D(30), customer_prepay_percent=D(100), days_from_payment_to_receipt=90,
                   annual_cost_of_money_percent=D(24))
    result = compute(sheet, [Item("a", "A", D(1))], [Line("p", "purchase", "Buy", "item", "a", D(1000), "USD", "total")])
    assert result["exposure"]["exposure"] == D(0) and result["cost_of_money"]["amount"] == D(0)
    assert result["exposure"]["customer_prepayment"] == D(1000)


def test_manual_price_override_and_minimums():
    sheet = _sheet(pricing_method="margin", target_percent=D(20), price_overrides={"a": D(90)},
                   item_min_prices={"a": D(100)}, min_acceptable_price=D(500))
    lines = [Line("p", "purchase", "Buy", "item", "a", D(80), "USD", "per_unit")]
    result = compute(sheet, [Item("a", "A", D(5))], lines)
    row = result["items"][0]
    assert row["manual"] is True and row["unit_price"] == D(90) and row["total_price"] == D(450)
    assert (row["margin_percent"], row["markup_percent"]) == (D("11.11"), D("12.50"))
    assert row["below_minimum"] is True and result["below_minimum"] is True


def test_allocation_by_quantity_and_manual_shares_on_a_sheet():
    lines = [Line("pa", "purchase", "Buy", "item", "a", D(1), "USD", "per_unit"),
             Line("pb", "purchase", "Buy", "item", "b", D(1), "USD", "per_unit"),
             Line("q", "storage", "Storage", "case", None, D(100), "USD", "total", allocation="by_quantity"),
             Line("m", "inspection", "Inspection", "case", None, D(10), "USD", "total", allocation="manual",
                  manual_shares={"a": D(1), "b": D(2)})]
    result = compute(_sheet(), [Item("a", "A", D(2)), Item("b", "B", D(3))], lines)
    by_line = {ln["line_id"]: ln["shares"] for ln in result["lines"]}
    assert by_line["q"] == {"a": D(40), "b": D(60)}
    assert by_line["m"] == {"a": D("3.33"), "b": D("6.67")}


def test_missing_inputs_are_reported_not_guessed():
    lines = [Line("p", "purchase", "Buy", "item", "a", None, None, "per_unit"),
             Line("d", "customs_duty", "Duty", "case", None, None, None, "percent_of_cif")]
    result = compute(_sheet(), [Item("a", "A", None)], lines)
    codes = {p["code"] for p in result["problems"]}
    assert {"amount_missing", "percent_missing", "quantity_missing"} <= codes
    assert result["items"][0]["total_price"] is None
