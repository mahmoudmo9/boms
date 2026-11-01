from datetime import date, datetime
from pathlib import Path

import jalali
import pipeline as P
from db import Store
from parser import parse_board, parse_need_detail

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


def test_rfq_text():
    need = board()[0]
    text = P.rfq_text(need, detail(), "شرکت نمونه", reply_by="1405/07/29", validity="1405/08/28")
    assert "1) استریلایزر پلاسما — 150 دستگاه" in text
    assert "محل تحویل: البرز، کرج" in text and "1405/08/28" in text and text.endswith("شرکت نمونه")


def test_pricing_and_warnings():
    items = [P.Item("الف", 10, "عدد"), P.Item("ب", 2, "عدد")]
    params = P.PricingParams(margin_pct=10, shipping=1_000_000, payment_months=2, finance_monthly_pct=2,
                             vat_pct=10, rounding=1000)
    plan = P.price_plan(items, [100_000, 1_000_000], params)
    # cost 1,000,000 + 2,000,000 = 3,000,000; shipping split 1/3 : 2/3
    assert plan.cost_total == 3_000_000
    a = plan.lines[0]
    expected_a = ((100_000 + 1_000_000 / 3 / 10) * 1.04) * 1.10
    assert a.suggested_unit >= expected_a and a.suggested_unit - expected_a < 1000
    assert plan.vat == round(plan.sale_total * 0.10)
    assert abs(plan.finance_cost - 4_000_000 * 0.04) < 1e-6
    assert plan.profit > 0 and 0 < plan.profit_pct < 15
    over = P.price_plan(items, [100_000, 1_000_000], params, overrides={1: 2_000_000})
    assert over.lines[1].final_unit == 2_000_000
    q = P.Quote(1, "x", [100_000, None], delivery_days=30, valid_until="1405/08/01")
    items[0].need_date = "1405/08/05"
    warns = P.quote_warnings(q, items, "1405/08/28", today=date(2026, 10, 20))
    assert any("همه اقلام" in w for w in warns)
    assert any("اعتبار قیمت" in w for w in warns)
    assert any("دیرتر" in w for w in warns)
    assert P.proforma_number({"1405": 4}, "1405") == ("1405/005", {"1405": 5})
    assert P.remaining_text(1000 + 3600 * 50, now=1000) == "2 روز و 2 ساعت"
    assert P.remaining_text(500, now=1000) == "مهلت گذشته"


def test_store_roundtrip(tmp_path):
    s = Store(tmp_path / "t.db")
    needs = board()
    new = s.upsert_needs(needs[:5], now=1000)
    assert len(new) == 5
    assert s.upsert_needs(needs[:7], now=2000) == [n.need_no for n in needs[5:7]]
    assert len(s.needs_seen_since(2000)) == 7
    meta = s.need_meta([needs[0].need_no])[needs[0].need_no]
    assert meta["first_seen"] == 1000 and meta["deadline_at"] > 2000
    s.set_exact_deadline(needs[0].need_no, 99999)
    s.upsert_needs(needs[:1], now=3000)
    assert s.need_meta([needs[0].need_no])[needs[0].need_no]["deadline_at"] == 99999
    s.save_detail(needs[0].need_no, {"info": detail()})
    assert s.get_detail(needs[0].need_no)["info"]["attachment_count"] == 0
    # case flow
    nn = needs[0].need_no
    s.set_stage(nn, "starred")
    s.set_stage(nn, "review")
    s.update_case_data(nn, note="یادداشت", checklist=[True, False])
    c = s.get_case(nn)
    assert c["stage"] == "review" and c["data"]["note"] == "یادداشت"
    assert len(s.events(nn)) == 2
    # suppliers & rfqs
    sid = s.save_supplier({"name": "تأمین الف", "phone": "0912"})
    rid = s.add_rfq(nn, sid)
    assert s.add_rfq(nn, sid) == rid
    s.update_rfq(rid, "sent")
    s.update_rfq(rid, "answered", prices=[100], delivery_days=5, valid_until="1405/09/01")
    r = s.rfqs(nn)[0]
    assert r["status"] == "answered" and r["sent_at"] and r["responded_at"] and r["data"]["prices"] == [100]
    assert s.rfq_counts()[nn] == (1, 1)
    assert not s.delete_supplier(sid)
    s.update_case_data(nn, final_rfq=rid, result="won")
    assert s.suppliers()[0]["win_count"] == 1
    # suggestions: same goods group, another need
    other = needs[4]  # same group (تجهیزات پزشکی و سلامت) as need 0? find one
    g0 = needs[0].goods_group or needs[0].service_group
    same = [n for n in needs[1:7] if (n.goods_group or n.service_group) == g0]
    if same:
        assert s.suggested_suppliers(g0, same[0].need_no)[0]["id"] == sid
    s.set("vat_pct", 9)
    assert s.settings()["vat_pct"] == 9 and s.settings()["margin_pct"] == 15.0
    s.close()


def test_unstar_and_supplier_delete(tmp_path):
    """Regression: removing a case must not leave RFQs that block deleting the supplier."""
    s = Store(tmp_path / "t.db")
    needs = board()
    s.upsert_needs(needs[:3])
    a, b = needs[0].need_no, needs[1].need_no
    sid = s.save_supplier({"name": "تأمین تست"})
    s.set_stage(a, "starred")
    assert not s.case_has_work(a)
    s.add_rfq(a, sid)
    assert s.case_has_work(a)                       # → the app asks before removing
    s.delete_case(a)                                # «حذف کامل»
    assert s.rfqs(a) == [] and s.events(a) == [] and s.get_case(a) is None
    assert s.delete_supplier(sid)                   # nothing blocks it any more
    # supplier used in a rejected case: deletable with its RFQs
    sid = s.save_supplier({"name": "تأمین دو"})
    s.set_stage(b, "rfq")
    rid = s.add_rfq(b, sid)
    assert not s.delete_supplier(sid)               # used → needs confirmation
    s.update_case_data(b, final_rfq=rid)
    assert not s.delete_supplier(sid, with_rfqs=True)   # chosen supplier of an active case → blocked
    s.set_stage(b, "rejected")
    assert s.delete_supplier(sid, with_rfqs=True)
    assert s.rfqs(b) == [] and s.get_case(b)["data"]["final_rfq"] is None
    # orphans from older versions are cleaned on open
    sid = s.save_supplier({"name": "سه"})
    s.con.execute("INSERT INTO rfqs(need_no, supplier_id, status, data) VALUES(?,?,'draft','{}')", (needs[2].need_no, sid))
    s.con.commit()
    s.close()
    s2 = Store(tmp_path / "t.db")
    assert s2.rfqs(needs[2].need_no) == [] and s2.delete_supplier(sid)
    s2.close()
