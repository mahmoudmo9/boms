"""Fill the proforma (پیش‌فاکتور) Word template and convert it to PDF."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import jalali
import pipeline as P


def default_template(resource_dir: Path) -> Path:
    return resource_dir / "templates" / "proforma_template.docx"


def build_context(*, number: str, date_j: str, addressee: str, need, info: dict | None, seller: dict,
                  plan: P.PricePlan, vat_pct: float, validity: str, delivery: str, payment: str,
                  shipping: str, notes: str = "", attachment: str = "ندارد") -> dict:
    fa = P.fa_digits
    rows = []
    for i, line in enumerate(plan.lines, start=1):
        rows.append({
            "ردیف": fa(i), "شرح": P.fa_text(line.item.name), "تعداد": fa(P._qty(line.item.qty)), "واحد": line.item.unit or "—",
            "فی": P.money_fa(line.final_unit), "مبلغ": P.money_fa(line.final_total),
        })
    published = P.detail_field(info, "تاریخ و ساعت اعلان") or need.published_date
    published = (jalali.from_date(jalali.to_date(published)) if jalali.to_date(published) else published)
    return {
        "شماره": fa(number), "تاریخ": fa(date_j), "پیوست": attachment,
        "خطاب": P.fa_text(addressee),
        "شماره_نیاز": fa(need.need_no),
        "شرح_نیاز": P.fa_text((info or {}).get("description") or need.description),
        "تاریخ_اعلان": fa(published),
        "نام_فروشنده": seller.get("seller_name", ""),
        "شناسه_ملی": fa(seller.get("national_id") or "………………"),
        "کد_اقتصادی": fa(seller.get("economic_code") or "………………"),
        "امضاکننده": seller.get("signer") or "………………",
        "خریدار": need.organization,
        "اقلام": rows,
        "جمع": P.money_fa(plan.sale_total),
        "نرخ_مالیات": fa(f"{vat_pct:g}"),
        "مالیات": P.money_fa(plan.vat),
        "جمع_کل": P.money_fa(plan.grand_total),
        "جمع_به_حروف": P.number_words(int(round(plan.grand_total))),
        "اعتبار_تا": fa(validity),
        "زمان_تحویل": P.fa_text(delivery),
        "محل_تحویل": fa(P.detail_field(info, "شهر محل تحویل") and
                        "، ".join(x for x in (P.detail_field(info, "استان محل تحویل"), P.detail_field(info, "شهر محل تحویل")) if x)
                        or need.province),
        "نحوه_پرداخت": P.fa_text(payment),
        "هزینه_حمل": P.fa_text(shipping),
        "توضیحات": P.fa_text(notes),
    }


def render_docx(template: Path, context: dict, out_docx: Path) -> Path:
    from docxtpl import DocxTemplate
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    tpl = DocxTemplate(str(template))
    tpl.render(context)
    tpl.save(str(out_docx))
    return out_docx


def to_pdf(docx: Path) -> tuple[Path | None, str]:
    """Convert with Microsoft Word on Windows (exact rendering); fall back to LibreOffice if available."""
    pdf = docx.with_suffix(".pdf")
    err = ""
    if os.name == "nt":
        try:
            _word_to_pdf(docx, pdf)
            if pdf.exists():
                return pdf, ""
            err = "Word فایل PDF را نساخت"
        except Exception as exc:  # Word missing or COM failure
            err = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
                           check=True, capture_output=True, timeout=120)
            if pdf.exists():
                return pdf, ""
        except Exception as exc:
            err = err or str(exc)
    return None, err or "برای ساخت PDF، Microsoft Word لازم است."


def _word_to_pdf(docx: Path, pdf: Path):
    """Export with Microsoft Word through COM (exact fonts and RTL layout)."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx.resolve()), ReadOnly=True, AddToRecentFiles=False)
        try:
            doc.ExportAsFixedFormat(str(pdf.resolve()), 17)  # 17 = wdExportFormatPDF
        finally:
            doc.Close(False)
    finally:
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()


def open_path(path: Path):
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
