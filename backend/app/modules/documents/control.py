"""Document control on every output (v0.9.0 section 6.3): a status stamp (DRAFT / ISSUED / SUPERSEDED / VOID), a footer
(code, version, «صفحهٔ x از y» / "Page x of y", generation date) and a QR code with

    BOMS|{code}|v{n}|{issue date}|{verification code}

The verification code is a truncated HMAC-SHA256 over those fields, keyed with HKDF(session key, "doc-verify"). The
«تأیید سند» page checks it and shows the record with its current status (an older version shows as superseded).

Outputs register how to find and judge their records (``register``); the shared engine decorates the HTML (PDF and
print view) and the Word file."""
import base64
import hashlib
import hmac
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

LABEL = b"doc-verify"
CODE_LEN = 10
STAMPS = {"draft": ("پیش‌نویس", "DRAFT"), "issued": ("صادرشده", "ISSUED"),
          "superseded": ("جایگزین‌شده", "SUPERSEDED"), "void": ("باطل", "VOID")}
STAMP_COLORS = {"draft": "#9a6700", "issued": "#1a7f37", "superseded": "#6e7781", "void": "#cf222e"}
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


# ---- the verification code --------------------------------------------------------------------------------------------

def _hkdf(key: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF-SHA256 with an empty salt."""
    prk = hmac.new(b"\x00" * 32, key, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]


def _key() -> bytes:
    from app.core.secrets import get_secret

    return _hkdf(get_secret("session_key").encode(), LABEL)


def verification_code(code: str, version: int, issue_date: str) -> str:
    mac = hmac.new(_key(), f"BOMS|{code}|v{version}|{issue_date}".encode(), hashlib.sha256).digest()
    return base64.b32encode(mac).decode()[:CODE_LEN]


def payload(code: str, version: int, issue_date: date | str | None) -> str:
    day = issue_date.isoformat() if isinstance(issue_date, date) else (issue_date or "-")
    return f"BOMS|{code}|v{version}|{day}|{verification_code(code, version, day)}"


PAYLOAD_RE = re.compile(r"^BOMS\|(?P<code>[^|]{1,60})\|v(?P<version>\d{1,4})\|(?P<date>[0-9-]{1,10})\|(?P<vc>[A-Z2-7]{%d})$" % CODE_LEN)


def parse(text_: str) -> dict | None:
    m = PAYLOAD_RE.match((text_ or "").strip())
    return None if m is None else {"code": m["code"], "version": int(m["version"]), "issue_date": m["date"], "vc": m["vc"]}


# ---- records ---------------------------------------------------------------------------------------------------------

@dataclass
class Kind:
    kind: str
    find: Callable            # (db, code, version) -> row | None
    describe: Callable        # (db, row) -> dict(code, version, issue_date, status, title, link)


KINDS: dict[str, Kind] = {}


def register(kind: str, find: Callable, describe: Callable) -> None:
    KINDS[kind] = Kind(kind, find, describe)


def _ensure() -> None:
    if not KINDS:
        _register_builtin()


def control_for(db: Session, kind: str, row, lang: str) -> dict:
    """What a generated output carries: stamp, footer fields, QR payload."""
    _ensure()
    info = KINDS[kind].describe(db, row)
    return {**info, "kind": kind, "lang": lang, "generated_at": datetime.now().date(),
            "payload": payload(info["code"], info["version"], info["issue_date"])}


def verify(db: Session, text_: str | None = None, *, code: str | None = None, vc: str | None = None) -> dict:
    """The «تأیید سند» check: the QR text, or the code with its verification code typed."""
    _ensure()
    parsed = parse(text_) if text_ else None
    if parsed is None and code and vc:
        code = code.strip()
        m = re.match(r"^(?P<code>.+?)(?:\s*v(?P<v>\d+))?$", code)
        for kind in KINDS.values():
            row = kind.find(db, m["code"], int(m["v"]) if m["v"] else None)
            if row is not None:
                info = kind.describe(db, row)
                day = info["issue_date"].isoformat() if isinstance(info["issue_date"], date) else (info["issue_date"] or "-")
                parsed = {"code": info["code"], "version": info["version"], "issue_date": day, "vc": vc.strip().upper()}
                break
    if parsed is None:
        return {"valid": False, "reason": "unreadable"}
    expected = verification_code(parsed["code"], parsed["version"], parsed["issue_date"])
    if not hmac.compare_digest(expected, parsed["vc"]):
        return {"valid": False, "reason": "signature_mismatch", **{k: parsed[k] for k in ("code", "version", "issue_date")}}
    for kind in KINDS.values():
        row = kind.find(db, parsed["code"], parsed["version"])
        if row is None:
            continue
        info = kind.describe(db, row)
        status = info["status"]
        if info["version"] != parsed["version"]:
            status = "superseded"
        return {"valid": True, "kind": kind.kind, **{k: parsed[k] for k in ("code", "version", "issue_date")},
                "status": status, "current": _jsonable(info)}
    return {"valid": True, "kind": None, "status": "unknown", **{k: parsed[k] for k in ("code", "version", "issue_date")}}


def _jsonable(info: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in info.items()}


def _status(status: str | None, superseded: bool = False) -> str:
    if status in ("cancelled", "withdrawn", "void"):
        return "void"
    if superseded or status == "superseded":
        return "superseded"
    if status in (None, "draft"):
        return "draft"
    return "issued"


def _day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def _register_builtin() -> None:
    from sqlalchemy import select

    from app.modules.execution.models import PurchaseOrder, SalesOrder
    from app.modules.finance.models import SalesInvoice
    from app.modules.quotes.models import Quote
    from app.modules.tenders.models import Tender, TenderProposal

    def quote_find(db, code, version):
        return db.scalar(select(Quote).where(Quote.number == code))

    def quote_describe(db, q):
        newer = db.execute(text("SELECT 1 FROM ops.quote WHERE supersedes_id = :i"), {"i": q.id}).first() is not None
        return {"code": q.number or f"PI-DRAFT-{str(q.id)[:8]}", "version": q.version or 1,
                "issue_date": _day(q.approved_at), "status": _status(q.status, newer), "title": q.number,
                "link": f"/cases/{q.case_id}?tab=quotes"}

    def so_find(db, code, version):
        return db.scalar(select(SalesOrder).where(SalesOrder.number == code))

    def so_describe(db, o):
        return {"code": o.number, "version": 1, "issue_date": _day(o.confirmed_at), "status": _status(o.status),
                "title": o.number, "link": f"/cases/{o.case_id}?tab=execution"}

    def po_find(db, code, version):
        return db.scalar(select(PurchaseOrder).where(PurchaseOrder.number == code))

    def po_describe(db, o):
        return {"code": o.number, "version": 1, "issue_date": _day(o.approved_at), "status": _status(o.status),
                "title": o.number, "link": f"/cases/{o.case_id}?tab=execution"}

    def inv_find(db, code, version):
        return db.scalar(select(SalesInvoice).where(SalesInvoice.number == code))

    def inv_describe(db, inv):
        return {"code": inv.number or f"INV-DRAFT-{str(inv.id)[:8]}", "version": 1, "issue_date": inv.issue_date,
                "status": _status(inv.status), "title": inv.number, "link": f"/cases/{inv.case_id}?tab=finance"}

    def tp_find(db, code, version):
        tender = db.scalar(select(Tender).where(Tender.code == code))
        if tender is None:
            return None
        stmt = select(TenderProposal).where(TenderProposal.tender_id == tender.id)
        stmt = stmt.where(TenderProposal.version == version) if version else stmt.order_by(TenderProposal.version.desc())
        return db.scalar(stmt.limit(1))

    def tp_describe(db, p):
        tender = db.get(Tender, p.tender_id)
        latest = db.execute(text("SELECT max(version) FROM ops.tender_proposal WHERE tender_id = :t"), {"t": p.tender_id}).scalar()
        return {"code": tender.code or str(tender.id)[:8], "version": p.version, "issue_date": _day(p.approved_at),
                "status": _status(p.status, (latest or 0) > p.version), "title": tender.title if hasattr(tender, "title") else tender.code,
                "link": f"/cases/{tender.case_id}?tab=tender"}

    register("quote", quote_find, quote_describe)
    register("sales_order", so_find, so_describe)
    register("purchase_order", po_find, po_describe)
    register("sales_invoice", inv_find, inv_describe)
    register("tender_proposal", tp_find, tp_describe)


# ---- rendering ---------------------------------------------------------------------------------------------------------

def qr_svg_uri(data: str) -> str:
    import segno

    return segno.make(data, error="m").svg_data_uri(scale=3, border=1)


def qr_png(data: str) -> bytes:
    import segno

    buffer = io.BytesIO()
    segno.make(data, error="m").save(buffer, kind="png", scale=4, border=1)
    return buffer.getvalue()


def stamp_text(status: str, lang: str) -> str:
    fa, en = STAMPS.get(status, STAMPS["issued"])
    return fa if lang == "fa" else en


def footer_text(ctl: dict) -> str:
    """Code, version and generation date (the page numbers are added by the page itself)."""
    fa = ctl["lang"] == "fa"
    day = ctl["generated_at"]
    if fa:
        from app.modules.sourcing.jalali import to_jalali

        y, m, d = to_jalali(day)
        when = f"{y:04d}/{m:02d}/{d:02d}".translate(FA_DIGITS)
        return f"{ctl['code']} · نسخهٔ {str(ctl['version']).translate(FA_DIGITS)} · {when}"
    return f"{ctl['code']} · v{ctl['version']} · {day.isoformat()}"


def _css_text(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def decorate_html(page: str, ctl: dict) -> str:
    """The footer line with «صفحهٔ x از y» / "Page x of y" in the bottom corner margin box (the company footer keeps
    the centre; nothing is placed below the page box, which would add a blank page), and the stamp with the QR in a
    fixed box at the top corner, repeated on every page."""
    import html as h

    fa = ctl["lang"] == "fa"
    counter = 'counter(page, persian) " از " counter(pages, persian)' if fa else 'counter(page) " of " counter(pages)'
    footer = _css_text(footer_text(ctl) + (" · صفحهٔ " if fa else " · Page "))
    corner = "bottom-right" if fa else "bottom-left"
    side = "left" if fa else "right"
    color = STAMP_COLORS.get(ctl["status"], "#1a7f37")
    css = (f"<style id='boms-control'>@page {{ @{corner} {{ content: {footer} {counter}; "
           f"font: 7.5pt Vazirmatn, Tahoma, sans-serif; color: #555; vertical-align: top; padding-top: 3px; white-space: nowrap; }} }}"
           f".boms-control {{ position: fixed; top: 0; {side}: 0; display: flex; flex-direction: column; "
           f"align-items: center; gap: 1mm; z-index: 10; }}"
           f".boms-stamp {{ border: 2px solid {color}; color: {color}; padding: .5mm 2.5mm; border-radius: 2px; "
           f"font: bold 10pt Vazirmatn, Tahoma, sans-serif; background: rgba(255,255,255,.75); white-space: nowrap; }}"
           f".boms-qr {{ width: 16mm; height: 16mm; }}</style>")
    body = (f"<div class='boms-control'><div class='boms-stamp' data-status='{h.escape(ctl['status'])}'>"
            f"{h.escape(stamp_text(ctl['status'], ctl['lang']))}</div>"
            f"<img class='boms-qr' alt='QR' data-payload='{h.escape(ctl['payload'])}' src='{qr_svg_uri(ctl['payload'])}'></div>")
    page = page.replace("</head>", css + "</head>", 1) if "</head>" in page else css + page
    return page.replace("</body>", body + "</body>", 1) if "</body>" in page else page + body


def decorate_docx(data: bytes, ctl: dict) -> bytes:
    """Word: the stamp in the header, the footer line with PAGE / NUMPAGES fields and the QR picture."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    doc = Document(io.BytesIO(data))
    fa = ctl["lang"] == "fa"
    section = doc.sections[0]
    color = RGBColor.from_string(STAMP_COLORS.get(ctl["status"], "#1a7f37").lstrip("#").upper())

    def field(run, instr: str) -> None:
        for kind, value in (("begin", None), ("instr", instr), ("separate", None), ("end", None)):
            if kind == "instr":
                el = OxmlElement("w:instrText")
                el.set(qn("xml:space"), "preserve")
                el.text = value
            else:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), kind)
            run._r.append(el)

    header = section.header.add_paragraph() if section.header.paragraphs[0].text else section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT if fa else WD_ALIGN_PARAGRAPH.RIGHT
    run = header.add_run(stamp_text(ctl["status"], ctl["lang"]))
    run.bold, run.font.size, run.font.color.rgb = True, Pt(12), color
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    small = lambda r: setattr(r.font, "size", Pt(8))  # noqa: E731
    small(footer.add_run(footer_text(ctl) + " · " + ("صفحهٔ " if fa else "Page ")))
    small(footer.add_run())
    field(footer.runs[-1], "PAGE")
    small(footer.add_run(" از " if fa else " of "))
    small(footer.add_run())
    field(footer.runs[-1], "NUMPAGES")
    qr = section.footer.add_paragraph()
    qr.alignment = WD_ALIGN_PARAGRAPH.LEFT if fa else WD_ALIGN_PARAGRAPH.RIGHT
    qr.add_run().add_picture(io.BytesIO(qr_png(ctl["payload"])), width=Mm(16))
    out = io.BytesIO()
    doc.core_properties.comments = ctl["payload"]
    doc.save(out)
    return out.getvalue()


def with_html(page: str, ctx: dict) -> str:
    return decorate_html(page, ctx["control"]) if ctx.get("control") else page


def with_docx(data: bytes, ctx: dict) -> bytes:
    return decorate_docx(data, ctx["control"]) if ctx.get("control") else data
