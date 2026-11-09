"""File and subject naming (v0.9.0 section 6.2).

Outputs: ``{code}_{type}_{party}_{date}[_v{n}][_DRAFT].{ext}`` in the document's language — fa: Jalali date
``14050810``, Persian type and party name; en: ISO date ``20261101``, English type and party name::

    PI-1405-0005_پیش‌فاکتور_نفت‌وگازپارس_14050810_v2.pdf
    PO-1405-0007_PurchaseOrder_ShanghaiValve_20261101.pdf

The pattern is the setting ``naming.output``; uploaded files keep their original names."""
import re
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.documents.folders import sanitize

DEFAULT_PATTERN = "{code}_{type}_{party}_{date}{version}{draft}"
TOKENS = {"code", "type", "party", "date", "version", "draft"}
TYPES = {
    "quote": ("پیش‌فاکتور", "ProformaInvoice"),
    "sales_order": ("سفارش‌فروش", "SalesOrder"),
    "purchase_order": ("سفارش‌خرید", "PurchaseOrder"),
    "sales_invoice": ("فاکتور", "Invoice"),
    "credit_note": ("اعلامیه‌بستانکار", "CreditNote"),
    "debit_note": ("اعلامیه‌بدهکار", "DebitNote"),
    "tender_proposal": ("پیشنهاد‌مناقصه", "TenderProposal"),
    "rfq": ("استعلام", "RFQ"),
}
# Persian letters that never join the next letter: a word ending in one needs no zero-width non-joiner
NON_JOINING = set("ادذرزژوآأإؤۀة")
ZWNJ = "‌"


def check(pattern: Any) -> str:
    if not isinstance(pattern, str) or not pattern or len(pattern) > 120:
        raise ValueError("expected a naming pattern")
    unknown = set(re.findall(r"\{([a-z]+)\}", pattern)) - TOKENS
    if unknown:
        raise ValueError(f"unknown token(s): {', '.join(sorted(unknown))}")
    if "{code}" not in pattern:
        raise ValueError("a naming pattern contains {code}")
    return pattern


def party_short(name: str | None, lang: str, words: list[str] | None = None) -> str:
    """«نفت و گاز پارس» -> «نفت‌وگازپارس»; "Shanghai Valve Co., Ltd." -> "ShanghaiValve"."""
    from app.modules.reference.service import strip_legal_form

    text = strip_legal_form(name or "", words or []) if words is not None else (name or "")
    parts = [p for p in re.split(r"[\s\-_.,()]+", text) if p]
    if lang == "fa":
        out = ""
        for p in parts:
            if out and out[-1] not in NON_JOINING and not out[-1].isascii():
                out += ZWNJ
            out += p
        return out[:40]
    return "".join(p[:1].upper() + p[1:] for p in parts)[:40]


def date_part(on: date | None, lang: str) -> str:
    from app.modules.sourcing.jalali import to_jalali

    if on is None:
        return ""
    if lang == "fa":
        y, m, d = to_jalali(on)
        return f"{y:04d}{m:02d}{d:02d}"
    return on.strftime("%Y%m%d")


def output_name(db: Session, *, kind: str, code: str, party: str | None, on: date | None, lang: str, ext: str,
                version: int | None = None, draft: bool = False, extra: str | None = None) -> str:
    from app.modules.reference.service import legal_form_words
    from app.modules.system import settings

    pattern = settings.get(db, "naming.output") or DEFAULT_PATTERN
    fa, en = TYPES.get(kind, (kind, kind))
    values = {"code": code, "type": fa if lang == "fa" else en,
              "party": "_".join(x for x in (party_short(party, lang, legal_form_words(db)), extra) if x),
              "date": date_part(on, lang),
              "version": f"_v{version}" if version and version > 1 else "", "draft": "_DRAFT" if draft else ""}
    stem = pattern
    for token, value in values.items():
        stem = stem.replace("{" + token + "}", value)
    stem = re.sub(r"_{2,}", "_", stem).strip("_")
    return sanitize(f"{stem}.{ext}", 180)


# ---- subjects ---------------------------------------------------------------------------------------------------------

def subject(code: str | None, text: str) -> str:
    """``[RFQ-1405-0009] Request for Quotation – …``: generated subjects start with the code in brackets."""
    text = (text or "").strip()
    if not code or text.startswith(f"[{code}]"):
        return text
    return f"[{code}] {text}"


def party_name(db: Session, party_id, lang: str) -> str:
    from app.modules.parties.models import Party

    p = db.get(Party, party_id) if party_id else None
    if p is None:
        return ""
    return (p.name_fa or p.name_en or "") if lang == "fa" else (p.name_en or p.name_fa or "")


def base_code(number: str | None) -> str:
    """The code without a revision suffix: ``PI-1405-0005-v2`` -> ``PI-1405-0005`` (the version is its own part)."""
    return re.sub(r"-v\d+$", "", number or "")


def content_disposition(filename: str, kind: str = "attachment") -> str:
    """A header that carries a Persian file name (RFC 6266 / 5987) with an ASCII fallback."""
    from urllib.parse import quote

    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "file"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"
