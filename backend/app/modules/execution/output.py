"""Order documents on the letterhead (v0.7.0): the sales order acknowledgement and the purchase order, fa or en, as
print view (HTML), PDF (the same headless browser as quotes) and Word. Built on the quote output engine (fonts,
number and date formatting, PDF printing); a DRAFT mark until the order is confirmed (SO) or approved (PO). Persian
documents always use Jalali dates and Persian digits (section 0)."""
import io
import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.costing import service as costing
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.parties import service as parties
from app.modules.quotes import output as qo
from app.modules.sourcing import templates as sourcing_templates
from app.modules.system import settings

LABELS = {
    "fa": {"so_title": "تأیید سفارش فروش", "po_title": "سفارش خرید", "number": "شماره", "date": "تاریخ",
           "customer": "خریدار", "supplier": "تأمین‌کننده", "contact": "طرف تماس", "customer_ref": "شماره قرارداد / سفارش خریدار",
           "contract_date": "تاریخ قرارداد", "delivery_due_on": "موعد تحویل", "ready_due_on": "تاریخ آمادگی",
           "delivery_place": "محل تحویل", "incoterm": "شرایط تحویل", "payment_terms": "نحوه پرداخت",
           "delivery_terms": "شرایط ارسال", "warranty": "گارانتی", "months": "ماه", "case": "پرونده", "no": "ردیف",
           "description": "شرح کالا", "quantity": "مقدار", "unit": "واحد", "unit_price": "قیمت واحد", "total": "مبلغ کل",
           "subtotal": "جمع", "vat": "مالیات بر ارزش افزوده", "grand": "جمع کل", "in_words": "مبلغ به حروف",
           "terms": "شرایط", "signer": "مهر و امضا", "draft": "پیش‌نویس",
           "draft_note_so": "پیش‌نویس — سفارش هنوز تأیید نشده است", "draft_note_po": "پیش‌نویس — سفارش هنوز تصویب نشده است",
           "national_id": "شناسه ملی", "economic_code": "کد اقتصادی", "version": "نسخه"},
    "en": {"so_title": "Order acknowledgement", "po_title": "Purchase order", "number": "Number", "date": "Date",
           "customer": "Customer", "supplier": "Supplier", "contact": "Attention", "customer_ref": "Your order / contract no.",
           "contract_date": "Contract date", "delivery_due_on": "Delivery due", "ready_due_on": "Ready by",
           "delivery_place": "Delivery place", "incoterm": "Incoterm", "payment_terms": "Payment terms",
           "delivery_terms": "Delivery terms", "warranty": "Warranty", "months": "months", "case": "Case", "no": "#",
           "description": "Description", "quantity": "Quantity", "unit": "Unit", "unit_price": "Unit price",
           "total": "Amount", "subtotal": "Subtotal", "vat": "VAT", "grand": "Total", "in_words": "Amount in words",
           "terms": "Terms", "signer": "Signature and stamp", "draft": "DRAFT",
           "draft_note_so": "DRAFT — the order is not confirmed yet", "draft_note_po": "DRAFT — the order is not approved yet",
           "national_id": "National ID", "economic_code": "Economic code", "version": "Version"},
}


def _company(db: Session, lang: str) -> dict:
    def per_lang(key: str) -> str:
        return ((settings.get(db, key) or {}).get(lang) or "").strip()

    pick = (lambda fa, en: (fa or en) if lang == "fa" else (en or fa))
    lb = LABELS[lang]
    ids = " · ".join(f"{lb[k]}: {v}" for k, v in (("national_id", settings.get(db, "company.national_id")),
                                                    ("economic_code", settings.get(db, "company.economic_code"))) if v)
    return {"name": pick(settings.get(db, "company.name_fa"), settings.get(db, "company.name_en"))
            or settings.get(db, "company.name") or "",
            "address": per_lang("company.address"), "phone": settings.get(db, "company.phone") or "",
            "email": settings.get(db, "company.email") or "", "footer": per_lang("company.footer"), "ids": ids,
            "signer": " — ".join(x for x in (per_lang("company.signer_name"), per_lang("company.signer_title")) if x)}


def _party_name(db: Session, party_id, lang: str) -> str:
    if party_id is None:
        return ""
    p = parties.get_party(db, party_id)
    return (p.name_fa or p.name_en or "") if lang == "fa" else (p.name_en or p.name_fa or "")


def _contact_name(db: Session, contact_id, lang: str) -> str:
    if contact_id is None:
        return ""
    c = parties.get_contact(db, contact_id)
    return (c.name_fa or c.name_en or "") if lang == "fa" else (c.name_en or c.name_fa or "")


def _base(db: Session, lang: str, currency: str, rows, draft: bool) -> dict:
    calendar, digits = qo.output_style(lang)
    decimals = costing.currency_decimals(db, currency)
    lines = [{"description": r.description, "quantity": qo._fmt_qty(r.quantity, digits), "unit": r.unit or "",
              "unit_price": qo._fmt_num(r.unit_price, decimals, digits), "total": qo._fmt_num(r.total, decimals, digits)}
             for r in rows]
    return {"lang": lang, "dir": "rtl" if lang == "fa" else "ltr", "labels": LABELS[lang], "draft": draft,
            "company": _company(db, lang), "currency": currency, "lines": lines, "calendar": calendar, "digits": digits,
            "decimals": decimals}


def sales_order_context(db: Session, order, language: str | None = None) -> dict:
    from app.modules.execution.sales_orders import items_of

    lang = language or _language_for(db, order.customer_party_id)
    ctx = _base(db, lang, order.currency, items_of(db, order.id), order.status == "draft")
    lb, cal, dig, dec = ctx["labels"], ctx["calendar"], ctx["digits"], ctx["decimals"]
    fmt_date = lambda v: qo._fmt_date(v, cal, dig)  # noqa: E731
    ctx.update({
        "kind": "so", "title": lb["so_title"], "number": order.number,
        "date": fmt_date((order.confirmed_at or order.created_at).date()),
        "party_label": lb["customer"], "party": _party_name(db, order.customer_party_id, lang),
        "contact": _contact_name(db, order.contact_id, lang),
        "meta": [(lb[k], v) for k, v in (
            ("customer_ref", order.customer_ref or ""), ("contract_date", fmt_date(order.contract_date)),
            ("delivery_due_on", fmt_date(order.delivery_due_on)), ("delivery_place", order.delivery_place or ""),
            ("incoterm", " ".join(x for x in (order.incoterm, order.incoterm_place) if x)),
            ("payment_terms", order.payment_terms or ""), ("delivery_terms", order.delivery_terms or ""),
            ("warranty", f"{sourcing_templates.localize_digits(str(order.warranty_months), lang, dig)} {lb['months']}"
             if order.warranty_months else "")) if v],
        "subtotal": qo._fmt_num(order.subtotal, dec, dig), "vat": qo._fmt_num(order.vat_amount, dec, dig),
        "grand": qo._fmt_num(order.total, dec, dig), "show_vat": bool(order.vat_amount),
        "words": qo.total_in_words(order.total, order.currency) if lang == "fa" else "", "terms": "",
        "draft_note": lb["draft_note_so"],
    })
    return ctx


def purchase_order_context(db: Session, po) -> dict:
    from app.modules.execution.purchase_orders import items_of

    lang = po.language
    ctx = _base(db, lang, po.currency, items_of(db, po.id), po.status == "draft")
    lb, cal, dig, dec = ctx["labels"], ctx["calendar"], ctx["digits"], ctx["decimals"]
    fmt_date = lambda v: qo._fmt_date(v, cal, dig)  # noqa: E731
    ctx.update({
        "kind": "po", "title": lb["po_title"], "number": po.number,
        "date": fmt_date((po.approved_at or po.created_at).date()),
        "party_label": lb["supplier"], "party": _party_name(db, po.supplier_party_id, lang),
        "contact": _contact_name(db, po.contact_id, lang),
        "meta": [(lb[k], v) for k, v in (
            ("ready_due_on", fmt_date(po.ready_due_on)), ("delivery_place", po.delivery_place or ""),
            ("incoterm", " ".join(x for x in (po.incoterm, po.incoterm_place) if x)),
            ("payment_terms", po.payment_terms or ""), ("delivery_terms", po.delivery_terms or "")) if v],
        "subtotal": qo._fmt_num(po.subtotal, dec, dig), "vat": "", "grand": qo._fmt_num(po.total, dec, dig),
        "show_vat": False, "words": qo.total_in_words(po.total, po.currency) if lang == "fa" else "",
        "terms": sourcing_templates.drop_empty_labels(po.terms_text or ""), "draft_note": lb["draft_note_po"],
    })
    return ctx


def _language_for(db: Session, party_id) -> str:
    if party_id is None:
        return "fa"
    p = parties.get_party(db, party_id)
    return "fa" if (p.country_iso2 or "IR") == "IR" else "en"


def render_html(ctx: dict) -> str:
    lb, c, e = ctx["labels"], ctx["company"], qo._e
    rows = "".join(f"<tr><td class='n'>{i}</td><td><bdi>{e(r['description'])}</bdi></td><td class='n'>{e(r['quantity'])}</td>"
                   f"<td>{e(r['unit'])}</td><td class='n'>{e(r['unit_price'])}</td><td class='n'>{e(r['total'])}</td></tr>"
                   for i, r in enumerate(ctx["lines"], start=1))
    totals = [("subtotal", ctx["subtotal"])] + ([("vat", ctx["vat"])] if ctx["show_vat"] else []) + [("grand", ctx["grand"])]
    totals_html = "".join(f"<tr{' class=grand' if k == 'grand' else ''}><th>{e(lb[k])}</th>"
                          f"<td class='n'>{e(v)} {e(ctx['currency'])}</td></tr>" for k, v in totals)
    meta = "".join(f"<div><span>{e(k)}:</span> <bdi>{e(v)}</bdi></div>" for k, v in ctx["meta"])
    contact = f"<div><span>{e(lb['contact'])}:</span> <bdi>{e(ctx['contact'])}</bdi></div>" if ctx["contact"] else ""
    head_small = " · ".join(x for x in (c["address"], c["phone"], c["email"]) if x)
    return f"""<!doctype html>
<html lang="{ctx['lang']}" dir="{ctx['dir']}"><head><meta charset="utf-8"><title>{e(ctx['title'])} {e(ctx['number'])}</title>
<style>
{qo._font_faces()}
@page {{ size: A4; margin: 16mm 14mm 18mm 14mm; }}
{qo.page_footer_css(c['footer'])}
* {{ box-sizing: border-box; }} html, body {{ margin: 0; padding: 0; }}
body {{ font-family: 'Vazirmatn', Tahoma, sans-serif; font-size: 10pt; color: #111; }}
header {{ border-bottom: 2px solid #1d4ed8; padding-bottom: 6px; }} header .name {{ font-size: 15pt; font-weight: 700; }}
header .small {{ font-size: 8.5pt; color: #444; }} h1 {{ font-size: 15pt; margin: 12px 0 6px; }}
.meta {{ display: flex; flex-wrap: wrap; gap: 4px 24px; margin-bottom: 10px; }} .meta span {{ color: #555; }}
table {{ width: 100%; border-collapse: collapse; }}
table.items th, table.items td {{ border: 1px solid #bbb; padding: 4px 6px; }} table.items th {{ background: #eef2ff; text-align: start; }}
td.n {{ text-align: end; white-space: nowrap; font-variant-numeric: tabular-nums; }}
table.totals {{ width: 55%; margin-inline-start: auto; margin-top: 8px; }} table.totals th {{ text-align: start; font-weight: 400; padding: 3px 6px; }}
table.totals td {{ padding: 3px 6px; }} table.totals tr.grand th, table.totals tr.grand td {{ font-weight: 700; border-top: 1px solid #333; }}
.words {{ margin-top: 6px; }} .terms {{ margin-top: 10px; white-space: pre-line; }}
.signer {{ margin-top: 18mm; text-align: end; }} .draft-note {{ color: #b91c1c; font-weight: 700; }}
.watermark {{ position: fixed; top: 38%; inset-inline: 0; text-align: center; font-size: 100pt; font-weight: 700; color: rgba(185,28,28,.12); transform: rotate(-20deg); }}
@media screen {{ body {{ max-width: 210mm; margin: 0 auto; padding: 12mm; background: #fff; }} }}
</style></head><body>
{f"<div class='watermark'>{e(lb['draft'])}</div>" if ctx['draft'] else ''}
<header><div class="name"><bdi>{e(c['name'])}</bdi></div>{f"<div class='small'><bdi>{e(head_small)}</bdi></div>" if head_small else ''}
{f"<div class='small'><bdi>{e(c['ids'])}</bdi></div>" if c['ids'] else ''}</header>
{f"<p class='draft-note'>{e(ctx['draft_note'])}</p>" if ctx['draft'] else ''}
<h1>{e(ctx['title'])}</h1>
<div class="meta"><div><span>{e(lb['number'])}:</span> <bdi>{e(ctx['number'])}</bdi></div>
<div><span>{e(lb['date'])}:</span> <bdi>{e(ctx['date'])}</bdi></div>
<div><span>{e(ctx['party_label'])}:</span> <bdi>{e(ctx['party'])}</bdi></div>{contact}{meta}</div>
<table class="items"><thead><tr><th>{e(lb['no'])}</th><th>{e(lb['description'])}</th><th>{e(lb['quantity'])}</th><th>{e(lb['unit'])}</th>
<th>{e(lb['unit_price'])} ({e(ctx['currency'])})</th><th>{e(lb['total'])} ({e(ctx['currency'])})</th></tr></thead><tbody>{rows}</tbody></table>
<table class="totals">{totals_html}</table>
{f"<p class='words'><b>{e(lb['in_words'])}:</b> {e(ctx['words'])}</p>" if ctx['words'] else ''}
{f"<div class='terms'><b>{e(lb['terms'])}</b><br>{e(ctx['terms'])}</div>" if ctx['terms'] else ''}
{f"<div class='signer'><b>{e(lb['signer'])}</b><br><bdi>{e(c['signer'])}</bdi></div>" if c['signer'] else f"<div class='signer'><b>{e(lb['signer'])}</b></div>"}
</body></html>"""


def render_docx(ctx: dict) -> bytes:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.shared import Pt, RGBColor

    rtl = ctx["dir"] == "rtl"
    lb, c = ctx["labels"], ctx["company"]
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name, style.font.size = ("Tahoma" if rtl else "Calibri"), Pt(10)

    def para(text: str = "", bold: bool = False, size: float | None = None, color=None):
        p = doc.add_paragraph()
        if rtl:
            p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
        r = p.add_run(text)
        r.bold = bold
        if size:
            r.font.size = Pt(size)
        if color is not None:
            r.font.color.rgb = color
        if rtl:
            r._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
        return p

    if ctx["draft"]:
        para(ctx["draft_note"], bold=True, size=16, color=RGBColor(0xB9, 0x1C, 0x1C))
    para(c["name"], bold=True, size=14)
    for line in (" · ".join(x for x in (c["address"], c["phone"], c["email"]) if x), c["ids"]):
        if line:
            para(line, size=9)
    para(ctx["title"], bold=True, size=15)
    for k, v in [(lb["number"], ctx["number"]), (lb["date"], ctx["date"]), (ctx["party_label"], ctx["party"]),
                 (lb["contact"], ctx["contact"])] + list(ctx["meta"]):
        if v:
            para(f"{k}: {v}")
    table = doc.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    if rtl:
        table._tbl.tblPr.append(OxmlElement("w:bidiVisual"))
    heads = [lb["no"], lb["description"], lb["quantity"], lb["unit"], f"{lb['unit_price']} ({ctx['currency']})",
             f"{lb['total']} ({ctx['currency']})"]
    for cell, text in zip(table.rows[0].cells, heads):
        cell.text = text
    for i, r in enumerate(ctx["lines"], start=1):
        for cell, text in zip(table.add_row().cells, [str(i), r["description"], r["quantity"], r["unit"], r["unit_price"],
                                                      r["total"]]):
            cell.text = text
    para(f"{lb['subtotal']}: {ctx['subtotal']} {ctx['currency']}")
    if ctx["show_vat"]:
        para(f"{lb['vat']}: {ctx['vat']} {ctx['currency']}")
    para(f"{lb['grand']}: {ctx['grand']} {ctx['currency']}", bold=True)
    if ctx["words"]:
        para(f"{lb['in_words']}: {ctx['words']}")
    if ctx["terms"]:
        para(lb["terms"], bold=True)
        for line in ctx["terms"].splitlines():
            para(line)
    para(lb["signer"], bold=True)
    if c["signer"]:
        para(c["signer"])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def generate(db: Session, entity_type: str, row, ctx: dict, fmt: str, source: str, actor: str | None) -> dict:
    """PDF or Word into the document store, linked to the order (``output``), with an event."""
    if fmt not in ("pdf", "docx"):
        raise AppError("invalid_format", "Format is pdf or docx", status=422)
    if fmt == "pdf":
        data, ext = qo.html_to_pdf(render_html(ctx), qo.find_browser(db)), "pdf"
    else:
        data, ext = render_docx(ctx), "docx"
    filename = f"{row.number}{'-DRAFT' if ctx['draft'] else ''}.{ext}"
    try:
        doc = documents.upload(db, io.BytesIO(data), filename, title=filename.rsplit(".", 1)[0], language=ctx["lang"],
                               source=source, actor=actor)
        document_id = doc.id
    except Conflict as exc:
        if exc.code != "duplicate_document":
            raise
        document_id = uuid.UUID(exc.details["id"])
    documents.link(db, document_id, entity_type, str(row.id), "output", source=source, actor=actor)
    events.record(db, entity_type, row.id, "output", {"format": fmt, "document_id": str(document_id),
                                                      "filename": filename, "draft": ctx["draft"],
                                                      "language": ctx["lang"]}, source, actor=actor)
    return {"document_id": str(document_id), "filename": filename, "format": fmt, "draft": ctx["draft"]}
