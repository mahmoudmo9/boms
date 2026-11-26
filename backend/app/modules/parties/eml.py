"""v0.10.1 section 0.4.6: an e-mail saved as ``.eml`` becomes an interaction on the case.

Read with the Python standard library (``email``): from, to, cc, date, subject (encoded headers in any charset),
the body (plain text preferred, HTML turned into text) and the attachments. ``[CODE]`` in the subject finds the
record and its case; the sender's address finds the contact (normalised contact methods). Nothing is sent and no
mailbox is opened: the owner saves the message from his mail client («Download message» in Gmail, «Download» in
Outlook on the web) and drops the file here. A ``.msg`` (Outlook's own format) is refused with those steps.
"""
from __future__ import annotations

import email
import email.policy
import html
import io
import re
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CODE_RE = re.compile(r"\[([A-Z]{2,5}-\d{4}-\d{3,6})\]")
MAX_BODY = 50_000


class _Text(HTMLParser):
    """HTML -> readable text: block elements become line breaks, scripts and styles are dropped."""
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    p = _Text()
    p.feed(markup)
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in html.unescape("".join(p.parts)).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def refuse_msg(filename: str, head: bytes) -> None:
    if filename.lower().endswith(".msg") or head[:8] == OLE_MAGIC:
        raise AppError("msg_not_supported", "Outlook .msg files are not read; save the message as .eml", {
            "gmail": "Gmail: open the message › ⋮ › Download message",
            "outlook": "Outlook on the web: open the message › … › Save / Download (.eml)"}, status=415)


def parse(raw: bytes, filename: str = "message.eml") -> dict:
    """The parts of an e-mail. Raises ``msg_not_supported`` for Outlook's .msg and ``not_an_email`` for anything else."""
    refuse_msg(filename, raw[:8])
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    if not (msg.get("From") or msg.get("Subject") or msg.get("Date")):
        raise AppError("not_an_email", "The file is not an e-mail (.eml)", status=422)
    name, address = parseaddr(str(msg.get("From", "")))
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body, body_kind = "", None
    if body_part is not None:
        content = body_part.get_content()
        body_kind = body_part.get_content_subtype()
        body = html_to_text(content) if body_kind == "html" else content.strip()
    attachments = []
    for part in msg.iter_attachments():
        data = part.get_payload(decode=True) or b""
        attachments.append({"filename": part.get_filename() or "attachment", "content_type": part.get_content_type(),
                            "size": len(data), "data": data})
    try:
        sent = parsedate_to_datetime(str(msg["Date"])) if msg.get("Date") else None
    except (TypeError, ValueError):
        sent = None
    subject = str(msg.get("Subject", "") or "").strip()
    return {"from_name": name or None, "from_address": (address or "").lower() or None,
            "to": [a.lower() for _n, a in getaddresses([str(v) for v in msg.get_all("To", [])]) if a],
            "cc": [a.lower() for _n, a in getaddresses([str(v) for v in msg.get_all("Cc", [])]) if a],
            "date": sent, "subject": subject or None, "body": body[:MAX_BODY], "body_kind": body_kind,
            "codes": CODE_RE.findall(subject), "attachments": attachments}


# where a code in the subject leads: the record, its case, and which interaction link it gives
CODE_TARGETS = {
    "case": ("SELECT id AS case_id, NULL::uuid AS ref_id FROM ops.case WHERE code = :c", None),
    "rfq": ("SELECT case_id, id AS ref_id FROM ops.rfq WHERE code = :c", "rfq"),
    "quote": ("SELECT case_id, id AS ref_id FROM ops.quote WHERE number = :c", "quote"),
    "purchase_order": ("SELECT case_id, id AS ref_id FROM ops.purchase_order WHERE number = :c", "purchase_order"),
    "shipment": ("SELECT case_id, id AS ref_id FROM ops.shipment WHERE code = :c", "shipment"),
}


def match(db: Session, parsed: dict, party_id=None) -> dict:
    """The case and record from «[CODE]» in the subject, and the party and contact from the sender's address. For an
    RFQ code the link is the sender party's recipient of that RFQ."""
    sender = None
    if parsed.get("from_address"):
        sender = db.execute(text("""
            SELECT c.id AS contact_id, c.party_id, c.name_fa, c.name_en FROM core.contact_method m JOIN core.contact c ON c.id = m.contact_id
            WHERE m.type = 'email' AND lower(m.value_norm) = :a AND m.status = 'active' AND c.status = 'active' LIMIT 1"""),
            {"a": parsed["from_address"]}).first()
    party = party_id or (sender.party_id if sender else None)
    found = {"case_id": None, "ref_type": None, "ref_id": None, "code": None, "code_kind": None}
    for code in parsed.get("codes") or []:
        for kind, (sql, ref) in CODE_TARGETS.items():
            row = db.execute(text(sql), {"c": code}).first()
            if row is None:
                continue
            found.update(case_id=row.case_id, code=code, code_kind=kind)
            if ref == "rfq" and party:
                rec = db.execute(text("SELECT id FROM ops.rfq_recipient WHERE rfq_id = :r AND party_id = :p LIMIT 1"),
                                 {"r": row.ref_id, "p": party}).first()
                if rec:
                    found.update(ref_type="rfq_recipient", ref_id=rec.id)
            elif ref and ref != "rfq":
                found.update(ref_type=ref, ref_id=row.ref_id)
            break
        if found["code"]:
            break
    return {**found, "party_id": party, "contact_id": sender.contact_id if sender else None,
            "contact_name_fa": sender.name_fa if sender else None, "contact_name_en": sender.name_en if sender else None,
            "known_sender": sender is not None}


def preview(db: Session, document_id) -> dict:
    """What a stored .eml says and what it matches — shown for confirmation; nothing is recorded."""
    from app.modules.documents import service as documents

    doc = documents.get(db, document_id)
    raw = documents.file_path(doc).read_bytes()
    parsed = parse(raw, doc.original_filename)
    return {**{k: v for k, v in parsed.items() if k != "attachments"},
            "attachments": [{k: v for k, v in a.items() if k != "data"} for a in parsed["attachments"]],
            "match": match(db, parsed), "document_id": doc.id}


def store_attachments(db: Session, document_id, entity_type: str, entity_id, source: str, actor: str | None) -> list:
    """The .eml and its attachments in the document store, linked to the interaction (an attachment already stored —
    same content — is linked, not stored twice)."""
    from app.core.errors import Conflict
    from app.modules.documents import service as documents

    doc = documents.get(db, document_id)
    documents.link(db, doc.id, entity_type, str(entity_id), "source", source=source, actor=actor)
    ids = []
    for a in parse(documents.file_path(doc).read_bytes(), doc.original_filename)["attachments"]:
        try:
            stored = documents.upload(db, io.BytesIO(a["data"]), a["filename"], source=source, actor=actor)
            att_id = stored.id
        except Conflict as dup:                      # the same file is already in the store
            att_id = dup.details.get("id") if isinstance(dup.details, dict) else None
            if att_id is None:
                raise
        except AppError as blocked:                  # a blocked type (an .exe in a mail) is left out, never stored
            if blocked.code == "blocked_file_type":
                continue
            raise
        documents.link(db, att_id, entity_type, str(entity_id), "attachment", source=source, actor=actor)
        ids.append(att_id)
    return ids
