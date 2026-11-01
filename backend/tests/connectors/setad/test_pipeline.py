"""Ported from SetadSuite v0.9.23 tests/inquiries/test_pipeline.py: the tests of the ported helpers (Jalali, numbers
in words, detail helpers). rfq_text, pricing, the SQLite Store and supplier tests are not ported: BOMS has its own
RFQ, costing and supplier modules."""
from datetime import date, datetime
from pathlib import Path

from app.connectors.setad import jalali
from app.connectors.setad import pipeline as P
from app.connectors.setad.eproc_parser import parse_board, parse_need_detail

FIX = Path(__file__).parent / "fixtures"


def board():
    return parse_board((FIX / "board.txt").read_text(encoding="utf-8"), "https://eproc.setadiran.ir/eproc/a.do")


def detail():
    return parse_need_detail((FIX / "need_detail.html").read_text(encoding="utf-8"))


def test_jalali_roundtrip():
    assert jalali.gregorian_to_jalali(2026, 10, 20) == (1405, 7, 28)
    assert jalali.jalali_to_gregorian(1405, 7, 28) == (2026, 10, 20)
    assert jalali.gregorian_to_jalali(2025, 3, 21) == (1404, 1, 1)
    for y, m, d in [(1403, 12, 30), (1404, 6, 31), (1405, 1, 1), (1399, 12, 30)]:
        g = jalali.jalali_to_gregorian(y, m, d)
        assert jalali.gregorian_to_jalali(*g) == (y, m, d)
    assert jalali.to_date("۱۴۰۵/۰۷/۳۰") == date(2026, 10, 22)
    assert jalali.to_datetime("1405/07/30 ساعت 14:00") == datetime(2026, 10, 22, 14, 0)
    assert jalali.to_datetime("1405/07/28 - 14:00") == datetime(2026, 10, 20, 14, 0)


def test_number_words_and_money():
    assert P.number_words(1_617_000_000) == "یک میلیارد و ششصد و هفده میلیون"
    assert P.number_words(1_250_015) == "یک میلیون و دویست و پنجاه هزار و پانزده"
    assert P.number_words(110) == "صد و ده"
    assert P.money(1234000) == "1,234,000"
    assert P.money_fa(1234000) == "۱,۲۳۴,۰۰۰"
    assert P.parse_amount("۱٬۲۳۴٬۰۰۰ ریال") == 1234000
    assert P.parse_amount("") is None


def test_detail_helpers():
    need = board()[0]
    info = detail()
    items = P.items_of(need, info)
    assert len(items) == 1 and items[0].name == "استریلایزر پلاسما" and items[0].qty == 150
    assert items[0].unit == "دستگاه" and items[0].need_date == "1405/08/05" and items[0].code == ""
    assert P.required_validity(info) == "1405/08/28"
    assert datetime.fromtimestamp(P.exact_deadline(info)) == datetime(2026, 10, 22, 14, 0)
    assert P.payment_months(info["buyer_note"]) == 3
    assert P.payment_months("پرداخت نقدی پس از تحویل") == 0
    assert P.payment_months("تحویل در انبار") is None
    assert P.find_keywords(P.need_text_for_scan(need, info), ["آیمد", "IRC", "ISO"]) == ["آیمد", "IRC"]
    # generic need without goods table → one item from the description
    assert P.items_of(need, {})[0].name == need.description
