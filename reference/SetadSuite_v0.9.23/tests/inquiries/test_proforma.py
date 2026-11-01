from pathlib import Path

import pipeline as P
import proforma
from parser import parse_board, parse_need_detail

ROOT = Path(__file__).parents[2] / "inquiries"
FIXT = Path(__file__).parent / "fixtures"


def test_render_proforma(tmp_path):
    need = parse_board((FIXT / "board.txt").read_text(encoding="utf-8"), "https://x/eproc/a.do")[0]
    info = parse_need_detail((FIXT / "need_detail.html").read_text(encoding="utf-8"))
    items = P.items_of(need, info)
    plan = P.price_plan(items, [8_000_000], P.PricingParams(margin_pct=15, shipping=2_000_000, payment_months=3))
    ctx = proforma.build_context(number="1405/001", date_j="1405/07/28", addressee="مدیریت محترم امور تدارکات بیمارستان البرز کرج",
                                 need=need, info=info, seller={"seller_name": "شرکت نمونه"}, plan=plan, vat_pct=10,
                                 validity="1405/08/28", delivery="۷ روز", payment="نقدی", shipping="فروشنده")
    assert ctx["شماره_نیاز"] == "۱۱۰۵۰۹۰۳۳۳۰۰۰۴۰۲" and ctx["محل_تحویل"] == "البرز، کرج"
    assert ctx["تاریخ_اعلان"] == "۱۴۰۵/۰۷/۲۸" and ctx["اقلام"][0]["تعداد"] == "۱۵۰"
    out = proforma.render_docx(proforma.default_template(ROOT), ctx, tmp_path / "p.docx")
    from docx import Document
    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    cells = " ".join(c.text for t in Document(str(out)).tables for r in t.rows for c in r.cells)
    assert "{{" not in text and "{%" not in text and "{{" not in cells
    assert "استریلایزر پلاسما" in cells and ctx["جمع_کل"] in cells and ctx["جمع_به_حروف"] in cells
