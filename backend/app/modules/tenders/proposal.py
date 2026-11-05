"""Financial proposal of a tender in the buyer's-form mode (v0.6.0).

BOMS produces a summary sheet from the case's final cost sheet (Phase 6 pricing and gate rules apply): tender number,
organizer, our company data, lines with quantity, unit, unit price and total, total before VAT, VAT, total with VAT,
the total in Persian words, the proposal validity, and the note «این برگه برای تکمیل فرم پیشنهاد قیمت کارفرما تهیه شده
است». The owner fills in the buyer's own form from it and attaches the stamped scan to envelope C. Approval locks the
numbers (with the below-cost check of v0.5.0); a new version supersedes the old one. Outputs: print view, PDF (the
headless browser of the quotes) and Word, with a DRAFT mark until approved, stored and linked like quote outputs.
"""
import io
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.costing import service as costing
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.parties import service as parties
from app.modules.quotes import output as quote_output
from app.modules.sourcing import coverage as sourcing_coverage
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.system import settings
from app.modules.tenders import guarantees
from app.modules.tenders.common import get_tender
from app.modules.tenders.models import Tender, TenderProposal, TenderProposalLine

NOTE_FA = "این برگه برای تکمیل فرم پیشنهاد قیمت کارفرما تهیه شده است."
NOTE_EN = "This sheet was prepared for filling in the buyer's own price form."
LABELS = {
    "fa": {"title": "خلاصهٔ پیشنهاد مالی", "tender_no": "شمارهٔ مناقصه", "organizer": "برگزارکننده", "version": "نسخه",
           "date": "تاریخ", "valid_until": "اعتبار پیشنهاد تا", "no": "ردیف", "description": "شرح", "quantity": "مقدار",
           "unit": "واحد", "unit_price": "قیمت واحد", "total": "مبلغ کل", "before_vat": "جمع بدون مالیات",
           "vat": "مالیات بر ارزش افزوده", "with_vat": "جمع با مالیات", "in_words": "مبلغ به حروف", "draft": "پیش‌نویس",
           "draft_note": "پیش‌نویس - تأیید نشده", "national_id": "شناسه ملی", "economic_code": "کد اقتصادی",
           "signer": "مهر و امضا", "note": NOTE_FA},
    "en": {"title": "Financial proposal summary", "tender_no": "Tender no.", "organizer": "Organizer", "version": "Version",
           "date": "Date", "valid_until": "Valid until", "no": "#", "description": "Description", "quantity": "Quantity",
           "unit": "Unit", "unit_price": "Unit price", "total": "Total", "before_vat": "Total before VAT", "vat": "VAT",
           "with_vat": "Total with VAT", "in_words": "Amount in words", "draft": "DRAFT", "draft_note": "Draft - not approved",
           "national_id": "National ID", "economic_code": "Economic code", "signer": "Signature", "note": NOTE_EN},
}


def get_proposal(db: Session, proposal_id: uuid.UUID) -> TenderProposal:
    row = db.get(TenderProposal, proposal_id)
    if row is None:
        raise NotFound("not_found", "Financial proposal not found")
    return row


def lines_of(db: Session, proposal_id: uuid.UUID) -> list[TenderProposalLine]:
    return list(db.scalars(select(TenderProposalLine).where(TenderProposalLine.proposal_id == proposal_id)
                           .order_by(TenderProposalLine.position)))


def proposals_of(db: Session, tender_id: uuid.UUID) -> list[TenderProposal]:
    return list(db.scalars(select(TenderProposal).where(TenderProposal.tender_id == tender_id)
                           .order_by(TenderProposal.version.desc())))


def _draft(row: TenderProposal) -> None:
    if row.status != "draft":
        raise Conflict("proposal_locked", "The proposal is approved; make a new version to change it", {"status": row.status})


def _totals(db: Session, row: TenderProposal) -> None:
    lines = lines_of(db, row.id)
    row.subtotal = sum((x.total for x in lines), Decimal(0))
    row.vat_amount = sum((x.vat_amount for x in lines), Decimal(0))
    row.total = row.subtotal + row.vat_amount


def create_proposal(db: Session, tender_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> TenderProposal:
    """A new version from the final cost sheet (gate must pass; every line priced: tenders are priced as a whole).
    Earlier versions become ``superseded``."""
    tender = get_tender(db, tender_id)
    sheet = costing.get_sheet(db, data["cost_sheet_id"]) if data.get("cost_sheet_id") else costing.current_sheet(db, tender.case_id)
    if sheet is None or sheet.case_id != tender.case_id:
        raise Conflict("gate_failed", "The case has no final cost sheet", {"failures": [{"code": "sheet_not_final"}]})
    valid_until = data.get("valid_until") or guarantees.needed_until(db, tender)
    gate = costing.gate(db, sheet, valid_until)
    failures = [f for f in gate["failures"] if f["code"] != "validity_too_long"]
    if failures:
        raise Conflict("gate_failed", "The cost sheet does not pass the gate", {"failures": failures,
                                                                                "max_valid_until": gate["max_valid_until"]})
    computation = costing.compute_sheet(db, sheet)
    unpriced = [r["item_id"] for r in computation["items"] if r["total_price"] is None]
    if unpriced:
        raise Conflict("gate_failed", "Every line of a tender must be priced", {"failures": [{"code": "item_not_priced",
                                                                                               "item_ids": unpriced}]})
    version = (db.scalar(select(func.max(TenderProposal.version)).where(TenderProposal.tender_id == tender.id)) or 0) + 1
    previous = [p for p in proposals_of(db, tender.id) if p.status != "superseded"]
    row = TenderProposal(tender_id=tender.id, cost_sheet_id=sheet.id, version=version, status="draft",
                         price_basis=data.get("price_basis") or "before_vat", currency=sheet.pricing_currency,
                         valid_until=date.fromisoformat(gate["valid_until"]) if gate.get("valid_until") else valid_until,
                         supersedes_id=previous[0].id if previous else None, note=data.get("note"))
    db.add(row)
    flush(db, "invalid_proposal")
    for position, item in enumerate(computation["items"], start=1):
        db.add(TenderProposalLine(proposal_id=row.id, line_item_id=uuid.UUID(item["item_id"]), position=position,
                                  quantity=item["quantity"], unit_code=item.get("unit_code"), unit_text=item.get("unit_text"),
                                  unit_price=item["unit_price"], total=item["total_price"], vat_amount=item["vat"],
                                  unit_cost=item["unit_cost"]))
    flush(db, "invalid_proposal")
    _totals(db, row)
    for old in previous:
        old.status = "superseded"
    flush(db, "invalid_proposal")
    events.record(db, "tender", tender.id, "proposal_create", jsonable({
        "proposal_id": row.id, "version": version, "cost_sheet_id": sheet.id, "subtotal": row.subtotal, "vat": row.vat_amount,
        "total": row.total, "superseded": [p.id for p in previous]}), source, actor=actor)
    return row


def update_proposal(db: Session, proposal_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> TenderProposal:
    row = get_proposal(db, proposal_id)
    _draft(row)
    changed = {}
    for key in ("price_basis", "valid_until", "note"):
        if key in changes and changes[key] is not None and changes[key] != getattr(row, key):
            changed[key] = {"old": getattr(row, key), "new": changes[key]}
            setattr(row, key, changes[key])
    if changed:
        flush(db, "invalid_proposal")
        events.record(db, "tender", row.tender_id, "proposal_update", jsonable({"proposal_id": row.id, "changes": changed}),
                      source, actor=actor)
    return row


def update_line(db: Session, line_id: uuid.UUID, unit_price: Decimal, source: str, actor: str | None = None) -> TenderProposalLine:
    line = db.get(TenderProposalLine, line_id)
    if line is None:
        raise NotFound("not_found", "Proposal line not found")
    row = get_proposal(db, line.proposal_id)
    _draft(row)
    decimals = costing.currency_decimals(db, row.currency)
    step = Decimal(1).scaleb(-decimals)
    rate = (line.vat_amount / line.total) if line.total else Decimal(0)
    old = line.unit_price
    line.unit_price = Decimal(unit_price).quantize(step)
    line.total = (line.unit_price * line.quantity).quantize(step)
    line.vat_amount = (line.total * rate).quantize(step)
    flush(db, "invalid_proposal")
    _totals(db, row)
    flush(db, "invalid_proposal")
    events.record(db, "tender", row.tender_id, "proposal_line_update", jsonable({
        "proposal_id": row.id, "line_id": line.id, "old": old, "new": line.unit_price}), source, actor=actor)
    return line


def below_cost(db: Session, row: TenderProposal) -> list[dict]:
    names = {i.id: i.name for i in sourcing_items.items_of(db, case_id=get_tender(db, row.tender_id).case_id)}
    return jsonable([{"line_id": x.id, "line_item_id": x.line_item_id, "name": names.get(x.line_item_id),
                      "unit_price": x.unit_price, "unit_cost": x.unit_cost}
                     for x in lines_of(db, row.id) if x.unit_cost is not None and x.unit_price < x.unit_cost])


def approve(db: Session, proposal_id: uuid.UUID, source: str, actor: str | None = None, *, confirm_below_cost: bool = False,
            reason: str | None = None) -> TenderProposal:
    """Locks the numbers; prices below the landed cost need confirmation with a reason (v0.5.0 rule)."""
    row = get_proposal(db, proposal_id)
    _draft(row)
    sheet = costing.get_sheet(db, row.cost_sheet_id)
    gate = costing.gate(db, sheet, row.valid_until)
    failures = [f for f in gate["failures"] if f["code"] not in ("validity_too_long", "below_minimum", "item_below_minimum")]
    if failures:
        raise Conflict("gate_failed", "The proposal cannot be approved yet", {"failures": failures})
    below = below_cost(db, row)
    reason = (reason or "").strip() or None
    if below and not confirm_below_cost:
        raise Conflict("below_cost", "Some prices are below cost", {"items": below})
    if below and not reason:
        raise AppError("reason_required", "Approving below cost needs a reason", status=422)
    row.status, row.approved_at, row.approved_by = "approved", clock.now(), actor or "unknown"
    row.below_cost_reason = reason if below else None
    flush(db, "invalid_proposal")
    if below:
        events.record(db, "tender", row.tender_id, "proposal_approve_below_cost", {"reason": reason, "items": below},
                      source, actor=actor)
    events.record(db, "tender", row.tender_id, "proposal_approve", jsonable({
        "proposal_id": row.id, "version": row.version, "total": row.total}), source, actor=actor)
    return row


# ---- outputs --------------------------------------------------------------------------------------------------------

def build_context(db: Session, row: TenderProposal, calendar: str = "jalali", digits: str = "fa", language: str = "fa") -> dict:
    tender = get_tender(db, row.tender_id)
    lb = LABELS[language]
    calendar, digits = quote_output.output_style(language)  # v0.7.0: always Jalali / Persian digits in fa
    decimals = costing.currency_decimals(db, row.currency)
    units = sourcing_coverage.unit_index(db)
    names = {i.id: i.name for i in sourcing_items.items_of(db, case_id=tender.case_id)}
    fmt = lambda v: quote_output._fmt_num(v, decimals, digits)  # noqa: E731
    lines = []
    for x in lines_of(db, row.id):
        unit = units.get(x.unit_code or "")
        lines.append({"description": names.get(x.line_item_id, ""), "quantity": quote_output._fmt_qty(x.quantity, digits),
                      "unit": ((unit.name_fa if language == "fa" else unit.name_en) if unit else (x.unit_text or "")),
                      "unit_price": fmt(x.unit_price), "total": fmt(x.total)})
    organizer = parties.get_party(db, tender.organizer_party_id) if tender.organizer_party_id else None
    per_lang = lambda key: ((settings.get(db, key) or {}).get(language) or "").strip()  # noqa: E731
    pick = (lambda fa, en: (fa or en) if language == "fa" else (en or fa))  # noqa: E731
    return {
        "lang": language, "dir": "rtl" if language == "fa" else "ltr", "labels": lb, "draft": row.status == "draft",
        "company": {"name": pick(settings.get(db, "company.name_fa"), settings.get(db, "company.name_en"))
                    or settings.get(db, "company.name") or "",
                    "national_id": settings.get(db, "company.national_id") or "",
                    "economic_code": settings.get(db, "company.economic_code") or "",
                    "signer": " — ".join(x for x in (per_lang("company.signer_name"), per_lang("company.signer_title")) if x),
                    "footer": per_lang("company.footer")},
        "tender_no": tender.tender_no or "", "organizer": pick(organizer.name_fa, organizer.name_en) if organizer else "",
        "version": str(row.version), "date": quote_output._fmt_date((row.approved_at or row.created_at).date(), calendar, digits),
        "valid_until": quote_output._fmt_date(row.valid_until, calendar, digits) if row.valid_until else "",
        "currency": row.currency, "lines": lines, "subtotal": fmt(row.subtotal), "vat": fmt(row.vat_amount),
        "total": fmt(row.total), "words": quote_output.total_in_words(row.total, row.currency) if language == "fa" else "",
    }


def render_html(ctx: dict) -> str:
    lb, c, e = ctx["labels"], ctx["company"], quote_output._e
    ids = " · ".join(f"{lb[k]}: {c[k]}" for k in ("national_id", "economic_code") if c[k])
    rows = "".join(f"<tr><td class='n'>{i}</td><td><bdi>{e(r['description'])}</bdi></td><td class='n'>{e(r['quantity'])}</td>"
                   f"<td>{e(r['unit'])}</td><td class='n'>{e(r['unit_price'])}</td><td class='n'>{e(r['total'])}</td></tr>"
                   for i, r in enumerate(ctx["lines"], start=1))
    totals = "".join(f"<tr{' class=grand' if k == 'with_vat' else ''}><th>{e(lb[k])}</th><td class='n'>{e(ctx[v])} {e(ctx['currency'])}</td></tr>"
                     for k, v in (("before_vat", "subtotal"), ("vat", "vat"), ("with_vat", "total")))
    return f"""<!doctype html>
<html lang="{ctx['lang']}" dir="{ctx['dir']}"><head><meta charset="utf-8"><title>{e(lb['title'])} {e(ctx['tender_no'])}</title>
<style>
{quote_output._font_faces()}
@page {{ size: A4; margin: 16mm 14mm 18mm 14mm; }}
{quote_output.page_footer_css(c['footer'])}
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
.words {{ margin-top: 6px; }} .note {{ margin-top: 10px; color: #444; font-size: 9pt; }}
.signer {{ margin-top: 18mm; text-align: end; }} .draft-note {{ color: #b91c1c; font-weight: 700; }}
.watermark {{ position: fixed; top: 38%; inset-inline: 0; text-align: center; font-size: 100pt; font-weight: 700; color: rgba(185,28,28,.12); transform: rotate(-20deg); }}
@media screen {{ body {{ max-width: 210mm; margin: 0 auto; padding: 12mm; background: #fff; }} }}
</style></head><body>
{f"<div class='watermark'>{e(lb['draft'])}</div>" if ctx['draft'] else ''}
<header><div class="name"><bdi>{e(c['name'])}</bdi></div>{f"<div class='small'><bdi>{e(ids)}</bdi></div>" if ids else ''}</header>
{f"<p class='draft-note'>{e(lb['draft_note'])}</p>" if ctx['draft'] else ''}
<h1>{e(lb['title'])}</h1>
<div class="meta"><div><span>{e(lb['tender_no'])}:</span> <bdi>{e(ctx['tender_no'])}</bdi></div>
<div><span>{e(lb['organizer'])}:</span> <bdi>{e(ctx['organizer'])}</bdi></div>
<div><span>{e(lb['version'])}:</span> {e(ctx['version'])}</div><div><span>{e(lb['date'])}:</span> <bdi>{e(ctx['date'])}</bdi></div>
{f"<div><span>{e(lb['valid_until'])}:</span> <bdi>{e(ctx['valid_until'])}</bdi></div>" if ctx['valid_until'] else ''}</div>
<table class="items"><thead><tr><th>{e(lb['no'])}</th><th>{e(lb['description'])}</th><th>{e(lb['quantity'])}</th><th>{e(lb['unit'])}</th>
<th>{e(lb['unit_price'])} ({e(ctx['currency'])})</th><th>{e(lb['total'])} ({e(ctx['currency'])})</th></tr></thead><tbody>{rows}</tbody></table>
<table class="totals">{totals}</table>
{f"<p class='words' data-testid='total-words'><b>{e(lb['in_words'])}:</b> {e(ctx['words'])}</p>" if ctx['words'] else ''}
<p class="note">{e(lb['note'])}</p>
{f"<div class='signer'><b>{e(lb['signer'])}</b><br><bdi>{e(c['signer'])}</bdi></div>" if c['signer'] else ''}
</body></html>"""


def render_docx(ctx: dict) -> bytes:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
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
        para(f"{lb['draft']} — {lb['draft_note']}", bold=True, size=16, color=RGBColor(0xB9, 0x1C, 0x1C))
    para(c["name"], bold=True, size=14)
    for k in ("national_id", "economic_code"):
        if c[k]:
            para(f"{lb[k]}: {c[k]}", size=9)
    para(lb["title"], bold=True, size=15)
    for k, v in (("tender_no", ctx["tender_no"]), ("organizer", ctx["organizer"]), ("version", ctx["version"]),
                 ("date", ctx["date"]), ("valid_until", ctx["valid_until"])):
        if v:
            para(f"{lb[k]}: {v}")
    table = doc.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    if rtl:
        tbl_pr = table._tbl.tblPr
        bidi = OxmlElement("w:bidiVisual")
        tbl_pr.append(bidi)
    heads = [lb["no"], lb["description"], lb["quantity"], lb["unit"], f"{lb['unit_price']} ({ctx['currency']})",
             f"{lb['total']} ({ctx['currency']})"]
    for cell, text in zip(table.rows[0].cells, heads):
        cell.text = text
    for i, r in enumerate(ctx["lines"], start=1):
        for cell, text in zip(table.add_row().cells, [str(i), r["description"], r["quantity"], r["unit"], r["unit_price"], r["total"]]):
            cell.text = text
    for k, v in (("before_vat", "subtotal"), ("vat", "vat"), ("with_vat", "total")):
        para(f"{lb[k]}: {ctx[v]} {ctx['currency']}", bold=k == "with_vat")
    if ctx["words"]:
        para(f"{lb['in_words']}: {ctx['words']}")
    para(lb["note"], size=9)
    if c["signer"]:
        para(lb["signer"], bold=True)
        para(c["signer"])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def generate(db: Session, proposal_id: uuid.UUID, fmt: str, calendar: str, digits: str, source: str,
             actor: str | None = None) -> dict:
    row = get_proposal(db, proposal_id)
    tender = get_tender(db, row.tender_id)
    ctx = build_context(db, row, calendar, digits)
    if fmt == "pdf":
        data, ext = quote_output.html_to_pdf(render_html(ctx), quote_output.find_browser(db)), "pdf"
    else:
        data, ext = render_docx(ctx), "docx"
    number = (tender.tender_no or str(tender.id)[:8]).replace("/", "-")
    filename = f"Tender-{number}-proposal-v{row.version}{'-DRAFT' if ctx['draft'] else ''}.{ext}"
    try:
        doc = documents.upload(db, io.BytesIO(data), filename, title=filename.rsplit(".", 1)[0], language="fa",
                               source=source, actor=actor)
        document_id = doc.id
    except Conflict as exc:
        if exc.code != "duplicate_document":
            raise
        document_id = uuid.UUID(exc.details["id"])
    documents.link(db, document_id, "tender_proposal", str(row.id), "output", source=source, actor=actor)
    events.record(db, "tender", tender.id, "proposal_output", {"proposal_id": str(row.id), "format": fmt,
                                                               "document_id": str(document_id), "filename": filename,
                                                               "draft": ctx["draft"]}, source, actor=actor)
    return {"document_id": str(document_id), "filename": filename, "format": fmt, "draft": ctx["draft"]}


def outputs_of(db: Session, proposal_id: uuid.UUID) -> list[dict]:
    from app.modules.parties import service as party_service

    return party_service.linked_documents(db, "tender_proposal", [str(proposal_id)])


def proposal_out(db: Session, row: TenderProposal) -> dict:
    names = {i.id: i.name for i in sourcing_items.items_of(db, case_id=get_tender(db, row.tender_id).case_id)}
    return jsonable({**row_snapshot(row), "decimals": costing.currency_decimals(db, row.currency),
                     "lines": [{**row_snapshot(x), "name": names.get(x.line_item_id, "")} for x in lines_of(db, row.id)],
                     "below_cost": below_cost(db, row), "outputs": outputs_of(db, row.id),
                     "words": quote_output.total_in_words(row.total, row.currency)})


def proposals_for_product(db: Session, product_id: uuid.UUID) -> list[dict]:
    """Approved tender proposals with lines of the product (the product page "Quotes we sent", marked tender)."""
    from sqlalchemy import text

    rows = db.execute(text(
        """
        SELECT pl.id, pr.id AS quote_id, 'tender-' || coalesce(t.tender_no, '') || '-v' || pr.version AS number,
               t.case_id, pr.approved_at AS sent_at, pr.currency, NULL AS incoterm, NULL AS incoterm_place,
               pr.status, pl.quantity, pl.unit_code, pl.unit_text, pl.unit_price,
               CASE t.result WHEN 'won' THEN 'accepted' WHEN 'lost' THEN 'rejected' ELSE NULL END AS outcome,
               t.result_reason AS outcome_reason, t.organizer_party_id AS party_id, p.name_fa AS party_fa,
               p.name_en AS party_en
        FROM ops.tender_proposal_line pl
        JOIN ops.tender_proposal pr ON pr.id = pl.proposal_id
        JOIN ops.tender t ON t.id = pr.tender_id
        JOIN ops.line_item li ON li.id = pl.line_item_id
        LEFT JOIN core.party p ON p.id = t.organizer_party_id
        WHERE li.product_id = :p AND pr.status IN ('approved', 'superseded') AND pr.approved_at IS NOT NULL
        ORDER BY pr.approved_at DESC
        """), {"p": product_id}).mappings().all()
    return [dict(r) | {"kind": "tender"} for r in rows]
