"""Invoice documents (v0.8.0) on the quote output engine: print view (HTML), PDF (headless browser) and Word.

- fa: the usual Iranian layout «صورتحساب فروش کالا و خدمات» — seller and buyer blocks with national ID and economic
  code, lines (amount, discount, after discount, VAT, total), totals and the total in Persian words; Jalali dates and
  Persian digits.
- en: a standard commercial invoice — seller, buyer, Incoterm, origin, marks, weights, packages, transport document,
  HS code per line; Gregorian dates and Latin digits.
A DRAFT mark until the invoice is issued. Credit and debit notes use the same layout with their own title.
"""
import io
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.finance import sales_invoices
from app.modules.finance.common import ZERO, decimals
from app.modules.parties import service as parties
from app.modules.quotes import output as qo
from app.modules.system import settings

LABELS = {
    "fa": {"invoice": "صورتحساب فروش کالا و خدمات", "credit_note": "صورتحساب اصلاحی (برگشت از فروش / کاهش مبلغ)",
           "debit_note": "صورتحساب اصلاحی (افزایش مبلغ)", "number": "شماره صورتحساب", "date": "تاریخ صدور",
           "due": "سررسید پرداخت", "seller": "مشخصات فروشنده", "buyer": "مشخصات خریدار", "name": "نام",
           "national_id": "شناسه ملی / کد ملی", "economic_code": "کد اقتصادی", "address": "نشانی", "phone": "تلفن",
           "no": "ردیف", "description": "شرح کالا یا خدمات", "quantity": "مقدار", "unit": "واحد", "unit_price": "مبلغ واحد",
           "amount": "مبلغ کل", "discount": "تخفیف", "after_discount": "مبلغ پس از تخفیف", "vat": "مالیات و عوارض",
           "line_total": "جمع کل", "subtotal": "جمع مبالغ", "total_discount": "تخفیف", "vat_total": "مالیات بر ارزش افزوده",
           "grand": "مبلغ قابل پرداخت", "in_words": "مبلغ به حروف", "corrects": "اصلاح صورتحساب شماره",
           "moadian": "شماره منحصربه‌فرد مالیاتی", "signer_seller": "مهر و امضای فروشنده", "signer_buyer": "مهر و امضای خریدار",
           "draft": "پیش‌نویس", "draft_note": "پیش‌نویس — صورتحساب هنوز صادر نشده است", "notes": "توضیحات",
           "currency": "ارز"},
    "en": {"invoice": "Commercial invoice", "credit_note": "Credit note", "debit_note": "Debit note",
           "number": "Invoice no.", "date": "Date", "due": "Payment due", "seller": "Seller / Exporter",
           "buyer": "Buyer / Consignee", "name": "Name", "national_id": "National ID", "economic_code": "Economic code",
           "address": "Address", "phone": "Phone", "no": "#", "description": "Description of goods", "quantity": "Quantity",
           "unit": "Unit", "unit_price": "Unit price", "amount": "Amount", "discount": "Discount", "after_discount": "Net",
           "vat": "VAT", "line_total": "Total", "subtotal": "Subtotal", "total_discount": "Discount", "vat_total": "VAT",
           "grand": "Total", "in_words": "Amount in words", "corrects": "Corrects invoice", "moadian": "Tax ID",
           "signer_seller": "Signature and stamp", "signer_buyer": "", "draft": "DRAFT",
           "draft_note": "DRAFT — the invoice is not issued yet", "notes": "Notes", "currency": "Currency",
           "incoterm": "Terms of delivery", "origin": "Country of origin", "marks": "Shipping marks",
           "gross": "Gross weight", "net": "Net weight", "packages": "Packages", "transport": "Transport document",
           "hs": "HS code", "payment_terms": "Payment terms"},
}


def _company(db: Session, lang: str) -> dict:
    def per_lang(key: str) -> str:
        return ((settings.get(db, key) or {}).get(lang) or "").strip()

    name = (settings.get(db, "company.name_fa") or settings.get(db, "company.name_en")) if lang == "fa" else \
        (settings.get(db, "company.name_en") or settings.get(db, "company.name_fa"))
    return {"name": name or settings.get(db, "company.name") or "", "national_id": settings.get(db, "company.national_id") or "",
            "economic_code": settings.get(db, "company.economic_code") or "", "address": per_lang("company.address"),
            "phone": settings.get(db, "company.phone") or "", "email": settings.get(db, "company.email") or "",
            "footer": per_lang("company.footer"), "bank": per_lang("company.bank_details"),
            "signer": " — ".join(x for x in (per_lang("company.signer_name"), per_lang("company.signer_title")) if x)}


def _digits(value: str, digits: str) -> str:
    return value.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")) if digits == "fa" and value else value


def build_context(db: Session, inv) -> dict:
    lang = inv.language
    calendar, digits = qo.output_style(lang)
    dec = decimals(db, inv.currency)
    num = lambda v: qo._fmt_num(v, dec, digits)  # noqa: E731
    date = lambda v: qo._fmt_date(v, calendar, digits)  # noqa: E731
    lb = LABELS[lang]
    p = parties.get_party(db, inv.customer_party_id)
    rate = (inv.vat_rate or ZERO) / Decimal(100)
    lines = []
    for r in sales_invoices.lines_of(db, inv.id):
        after = r.total
        line_vat = after * rate
        lines.append({"description": r.description, "quantity": qo._fmt_qty(r.quantity, digits), "unit": r.unit or "",
                      "unit_price": num(r.unit_price), "amount": num(r.quantity * r.unit_price), "discount": num(r.discount),
                      "after_discount": num(after), "vat": num(line_vat), "total": num(after + line_vat), "hs": r.hs_code or ""})
    base = sales_invoices.get_invoice(db, inv.corrects_invoice_id) if inv.corrects_invoice_id else None
    from app.modules.execution.common import get_sales_order

    order = get_sales_order(db, inv.sales_order_id)
    export = [(lb.get(k, k), v) for k, v in (
        ("incoterm", " ".join(x for x in (inv.incoterm, inv.incoterm_place) if x)), ("origin", inv.country_of_origin or ""),
        ("marks", inv.shipping_marks or ""), ("gross", inv.gross_weight or ""), ("net", inv.net_weight or ""),
        ("packages", inv.packages or ""), ("transport", inv.transport_doc_no or ""),
        ("payment_terms", order.payment_terms or "")) if v] if lang == "en" else []
    company = _company(db, lang)
    company.update({k: _digits(company[k], digits) for k in ("national_id", "economic_code", "phone")})
    return {
        "lang": lang, "dir": "rtl" if lang == "fa" else "ltr", "labels": lb, "draft": inv.status == "draft",
        "title": lb[inv.kind], "number": inv.number or "—", "date": date(inv.issue_date) if inv.issue_date else "—",
        "due": date(inv.due_date) if inv.due_date else "", "company": company, "currency": inv.currency,
        "buyer": {"name": (p.name_fa or p.name_en or "") if lang == "fa" else (p.name_en or p.name_fa or ""),
                  "national_id": _digits(p.national_id or "", digits), "economic_code": _digits(p.economic_code or "", digits),
                  "country": p.country_iso2 or ""},
        "lines": lines, "subtotal": num(inv.subtotal), "discount": num(inv.discount), "show_discount": bool(inv.discount),
        "vat": num(inv.vat_amount), "show_vat": bool(inv.vat_amount) or lang == "fa",
        "vat_rate": qo._fmt_num(inv.vat_rate, 2, digits).rstrip("0").rstrip(".٫") if inv.vat_rate else "",
        "grand": num(inv.total), "words": qo.total_in_words(inv.total, inv.currency) if lang == "fa" else "",
        "corrects": base.number if base else "", "moadian": inv.moadian_tax_id or "", "export": export,
        "notes": inv.notes or "", "kind": inv.kind,
    }


def render_html(ctx: dict) -> str:
    lb, c, b, e = ctx["labels"], ctx["company"], ctx["buyer"], qo._e
    fa = ctx["lang"] == "fa"
    if fa:
        head = (f"<th>{e(lb['no'])}</th><th>{e(lb['description'])}</th><th>{e(lb['quantity'])}</th><th>{e(lb['unit'])}</th>"
                f"<th>{e(lb['unit_price'])}</th><th>{e(lb['amount'])}</th><th>{e(lb['discount'])}</th>"
                f"<th>{e(lb['after_discount'])}</th><th>{e(lb['vat'])}</th><th>{e(lb['line_total'])}</th>")
        rows = "".join(
            f"<tr><td class='n'>{qo._fmt_qty(Decimal(i), "fa")}</td><td><bdi>{e(r['description'])}</bdi></td>"
            f"<td class='n'>{e(r['quantity'])}</td><td>{e(r['unit'])}</td><td class='n'>{e(r['unit_price'])}</td>"
            f"<td class='n'>{e(r['amount'])}</td><td class='n'>{e(r['discount'])}</td><td class='n'>{e(r['after_discount'])}</td>"
            f"<td class='n'>{e(r['vat'])}</td><td class='n'>{e(r['total'])}</td></tr>"
            for i, r in enumerate(ctx["lines"], start=1))
    else:
        head = (f"<th>{e(lb['no'])}</th><th>{e(lb['description'])}</th><th>{e(lb['hs'])}</th><th>{e(lb['quantity'])}</th>"
                f"<th>{e(lb['unit'])}</th><th>{e(lb['unit_price'])} ({e(ctx['currency'])})</th>"
                f"<th>{e(lb['amount'])} ({e(ctx['currency'])})</th>")
        rows = "".join(
            f"<tr><td class='n'>{i}</td><td><bdi>{e(r['description'])}</bdi></td><td>{e(r['hs'])}</td>"
            f"<td class='n'>{e(r['quantity'])}</td><td>{e(r['unit'])}</td><td class='n'>{e(r['unit_price'])}</td>"
            f"<td class='n'>{e(r['after_discount'])}</td></tr>" for i, r in enumerate(ctx["lines"], start=1))
    totals = [(lb["subtotal"], ctx["subtotal"])]
    if ctx["show_discount"]:
        totals.append((lb["total_discount"], ctx["discount"]))
    if ctx["show_vat"]:
        totals.append((f"{lb['vat_total']}{(' ' + ctx['vat_rate'] + '٪') if fa and ctx['vat_rate'] else (' ' + ctx['vat_rate'] + '%') if ctx['vat_rate'] else ''}",
                       ctx["vat"]))
    totals.append((lb["grand"], ctx["grand"]))
    totals_html = "".join(f"<tr{' class=grand' if i == len(totals) - 1 else ''}><th>{e(k)}</th>"
                          f"<td class='n'>{e(v)} {e(ctx['currency'])}</td></tr>" for i, (k, v) in enumerate(totals))

    def party_block(title, rows_):
        cells = "".join(f"<div><span>{e(k)}:</span> <bdi>{e(v)}</bdi></div>" for k, v in rows_ if v)
        return f"<section class='party'><h2>{e(title)}</h2>{cells}</section>"

    seller = party_block(lb["seller"], [(lb["name"], c["name"]), (lb["national_id"], c["national_id"]),
                                        (lb["economic_code"], c["economic_code"]), (lb["address"], c["address"]),
                                        (lb["phone"], c["phone"])])
    buyer = party_block(lb["buyer"], [(lb["name"], b["name"]), (lb["national_id"], b["national_id"]),
                                      (lb["economic_code"], b["economic_code"])])
    meta = [(lb["number"], ctx["number"]), (lb["date"], ctx["date"]), (lb["due"], ctx["due"]),
            (lb["corrects"], ctx["corrects"]), (lb["moadian"], ctx["moadian"])] + list(ctx["export"])
    meta_html = "".join(f"<div><span>{e(k)}:</span> <bdi>{e(v)}</bdi></div>" for k, v in meta if v)
    signers = (f"<div class='signers'><div>{e(lb['signer_seller'])}<br><bdi>{e(c['signer'])}</bdi></div>"
               + (f"<div>{e(lb['signer_buyer'])}</div>" if lb["signer_buyer"] else "") + "</div>")
    return f"""<!doctype html>
<html lang="{ctx['lang']}" dir="{ctx['dir']}"><head><meta charset="utf-8"><title>{e(ctx['title'])} {e(ctx['number'])}</title>
<style>
{qo._font_faces()}
@page {{ size: A4{' landscape' if fa else ''}; margin: 12mm 10mm 14mm 10mm; }}
{qo.page_footer_css(c['footer'])}
* {{ box-sizing: border-box; }} html, body {{ margin: 0; padding: 0; }}
body {{ font-family: 'Vazirmatn', Tahoma, sans-serif; font-size: 9.5pt; color: #111; }}
h1 {{ font-size: 14pt; text-align: center; margin: 0 0 6px; }} h2 {{ font-size: 10pt; margin: 0 0 3px; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 2px 20px; margin-bottom: 6px; }} .meta span, .party span {{ color: #555; }}
.parties {{ display: flex; gap: 8px; margin-bottom: 6px; }}
.party {{ flex: 1; border: 1px solid #999; padding: 4px 6px; display: flex; flex-wrap: wrap; gap: 2px 16px; }}
.party h2 {{ width: 100%; }}
table {{ width: 100%; border-collapse: collapse; }}
table.items th, table.items td {{ border: 1px solid #999; padding: 3px 4px; }} table.items th {{ background: #eef2ff; font-size: 8.5pt; }}
td.n {{ text-align: end; white-space: nowrap; font-variant-numeric: tabular-nums; }}
table.totals {{ width: 50%; margin-inline-start: auto; margin-top: 6px; }} table.totals th {{ text-align: start; font-weight: 400; padding: 2px 6px; }}
table.totals td {{ padding: 2px 6px; }} table.totals tr.grand th, table.totals tr.grand td {{ font-weight: 700; border-top: 1px solid #333; }}
.words {{ margin-top: 4px; }} .notes {{ margin-top: 6px; white-space: pre-line; }}
.signers {{ display: flex; justify-content: space-between; margin-top: 14mm; }}
.draft-note {{ color: #b91c1c; font-weight: 700; }}
.watermark {{ position: fixed; top: 35%; inset-inline: 0; text-align: center; font-size: 96pt; font-weight: 700; color: rgba(185,28,28,.12); transform: rotate(-20deg); }}
@media screen {{ body {{ max-width: {'297mm' if fa else '210mm'}; margin: 0 auto; padding: 10mm; background: #fff; }} }}
</style></head><body>
{f"<div class='watermark'>{e(lb['draft'])}</div>" if ctx['draft'] else ''}
{f"<p class='draft-note'>{e(lb['draft_note'])}</p>" if ctx['draft'] else ''}
<h1>{e(ctx['title'])}</h1>
<div class="meta">{meta_html}</div>
<div class="parties">{seller}{buyer}</div>
<table class="items"><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>
<table class="totals">{totals_html}</table>
{f"<p class='words'><b>{e(lb['in_words'])}:</b> {e(ctx['words'])}</p>" if ctx['words'] else ''}
{f"<div class='notes'><b>{e(lb['notes'])}:</b> {e(ctx['notes'])}</div>" if ctx['notes'] else ''}
{signers}
</body></html>"""


def render_docx(ctx: dict) -> bytes:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.shared import Pt, RGBColor

    rtl = ctx["dir"] == "rtl"
    lb, c, b = ctx["labels"], ctx["company"], ctx["buyer"]
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name, style.font.size = ("Tahoma" if rtl else "Calibri"), Pt(9.5)

    def para(value: str = "", bold: bool = False, size: float | None = None, color=None):
        p = doc.add_paragraph()
        if rtl:
            p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
        r = p.add_run(value)
        r.bold = bold
        if size:
            r.font.size = Pt(size)
        if color is not None:
            r.font.color.rgb = color
        if rtl:
            r._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
        return p

    if ctx["draft"]:
        para(lb["draft_note"], bold=True, size=14, color=RGBColor(0xB9, 0x1C, 0x1C))
    para(ctx["title"], bold=True, size=14)
    for k, v in [(lb["number"], ctx["number"]), (lb["date"], ctx["date"]), (lb["due"], ctx["due"]),
                 (lb["corrects"], ctx["corrects"]), (lb["moadian"], ctx["moadian"])] + list(ctx["export"]):
        if v:
            para(f"{k}: {v}")
    for title, rows_ in ((lb["seller"], [(lb["name"], c["name"]), (lb["national_id"], c["national_id"]),
                                         (lb["economic_code"], c["economic_code"]), (lb["address"], c["address"])]),
                         (lb["buyer"], [(lb["name"], b["name"]), (lb["national_id"], b["national_id"]),
                                        (lb["economic_code"], b["economic_code"])])):
        para(title, bold=True)
        para(" · ".join(f"{k}: {v}" for k, v in rows_ if v))
    if rtl:
        heads = [lb["no"], lb["description"], lb["quantity"], lb["unit"], lb["unit_price"], lb["amount"], lb["discount"],
                 lb["after_discount"], lb["vat"], lb["line_total"]]
        keys = ["description", "quantity", "unit", "unit_price", "amount", "discount", "after_discount", "vat", "total"]
    else:
        heads = [lb["no"], lb["description"], lb["hs"], lb["quantity"], lb["unit"], lb["unit_price"], lb["amount"]]
        keys = ["description", "hs", "quantity", "unit", "unit_price", "after_discount"]
    table = doc.add_table(rows=1, cols=len(heads))
    table.style = "Table Grid"
    if rtl:
        table._tbl.tblPr.append(OxmlElement("w:bidiVisual"))
    for cell, value in zip(table.rows[0].cells, heads):
        cell.text = value
    for i, r in enumerate(ctx["lines"], start=1):
        for cell, value in zip(table.add_row().cells, [str(i)] + [r[k] for k in keys]):
            cell.text = value
    para(f"{lb['subtotal']}: {ctx['subtotal']} {ctx['currency']}")
    if ctx["show_discount"]:
        para(f"{lb['total_discount']}: {ctx['discount']} {ctx['currency']}")
    if ctx["show_vat"]:
        para(f"{lb['vat_total']}: {ctx['vat']} {ctx['currency']}")
    para(f"{lb['grand']}: {ctx['grand']} {ctx['currency']}", bold=True)
    if ctx["words"]:
        para(f"{lb['in_words']}: {ctx['words']}")
    if ctx["notes"]:
        para(f"{lb['notes']}: {ctx['notes']}")
    para(lb["signer_seller"], bold=True)
    if c["signer"]:
        para(c["signer"])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def generate(db: Session, inv, fmt: str, source: str, actor: str | None) -> dict:
    """PDF or Word into the document store, linked to the invoice (``output``), with an event."""
    if fmt not in ("pdf", "docx"):
        raise AppError("invalid_format", "Format is pdf or docx", status=422)
    ctx = build_context(db, inv)
    if fmt == "pdf":
        data, ext = qo.html_to_pdf(render_html(ctx), qo.find_browser(db)), "pdf"
    else:
        data, ext = render_docx(ctx), "docx"
    stem = inv.number or f"invoice-draft-{str(inv.id)[:8]}"
    filename = f"{stem}{'-DRAFT' if ctx['draft'] else ''}.{ext}"
    try:
        doc = documents.upload(db, io.BytesIO(data), filename, title=filename.rsplit(".", 1)[0], language=ctx["lang"],
                               source=source, actor=actor)
        document_id = doc.id
    except Conflict as exc:
        if exc.code != "duplicate_document":
            raise
        document_id = uuid.UUID(exc.details["id"])
    documents.link(db, document_id, "sales_invoice", str(inv.id), "output", source=source, actor=actor)
    events.record(db, "sales_invoice", inv.id, "output", {"format": fmt, "document_id": str(document_id),
                                                          "filename": filename, "draft": ctx["draft"],
                                                          "language": ctx["lang"]}, source, actor=actor)
    return {"document_id": str(document_id), "filename": filename, "format": fmt, "draft": ctx["draft"]}
