"""Message templates (``ops.message_template``) and rendering: RFQ texts and, since v0.4.0, quote terms
(kind ``quote_terms``, used by the quotes module through these functions).

Placeholders are a fixed set; any other ``{name}`` is rejected when a template is saved. Literal braces are
written ``{{`` and ``}}``.
"""

import re
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.events import service as events
from app.modules.sourcing.common import diff, flush, jsonable, row_snapshot
from app.modules.sourcing.models import MessageTemplate, RfqRecipient

PLACEHOLDERS = ("supplier_name", "contact_name", "case_title", "items_table", "respond_by", "signature")
QUOTE_PLACEHOLDERS = ("buyer_name", "valid_until", "payment_terms", "incoterm", "lead_time", "bank_details")
PLACEHOLDERS_BY_KIND = {"rfq": PLACEHOLDERS, "quote_terms": QUOTE_PLACEHOLDERS}
_TOKEN = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[{}]")

LABELS = {
    "en": {"no": "No", "item": "Item", "qty": "Quantity", "specs": "Specs", "packaging": "Packaging",
           "destination": "Destination", "incoterm": "Incoterm", "required_by": "Required by", "note": "Note"},
    "fa": {"no": "ردیف", "item": "کالا", "qty": "مقدار", "specs": "مشخصات", "packaging": "بسته‌بندی",
           "destination": "مقصد", "incoterm": "شرایط تحویل", "required_by": "مهلت تحویل", "note": "توضیح"},
}
MAX_SPECS_IN_TABLE = 4


def placeholders_in(template: str) -> list[str]:
    """Names of every ``{name}`` in the text; raises for stray single braces."""
    names = []
    for match in _TOKEN.finditer(template or ""):
        token = match.group(0)
        if token in ("{{", "}}"):
            continue
        if match.group(1) is None:
            raise AppError("invalid_template", "Unbalanced brace in template; write {{ or }} for a literal brace",
                           {"position": match.start()}, status=422)
        names.append(match.group(1).strip())
    return names


def validate_template(subject: str, body: str, kind: str = "rfq") -> None:
    allowed = PLACEHOLDERS_BY_KIND[kind]
    unknown = sorted({n for n in placeholders_in(subject) + placeholders_in(body) if n not in allowed})
    if unknown:
        raise AppError("unknown_placeholder", f"Unknown placeholder(s): {', '.join(unknown)}",
                       {"unknown": unknown, "allowed": list(allowed)}, status=422)


_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+")


def _drop_sentences_with(template: str, name: str) -> str:
    """Remove every sentence that uses ``{name}`` (a line left empty is removed too)."""
    token = re.compile(r"\{\s*" + name + r"\s*\}")
    lines = []
    for line in template.split("\n"):
        if not token.search(line):
            lines.append(line)
            continue
        kept = [part for part in _SENTENCE_END.split(line) if not token.search(part)]
        if kept:
            lines.append(" ".join(kept))
    return "\n".join(lines)


_LABEL_ONLY = re.compile(r"^\s*[^\n:{}]{1,60}[:：]\s*$")


def drop_empty_labels(text: str) -> str:
    """Omit "Label:" lines whose value is empty (v0.5.0): a line that is only a label, followed by an empty line
    or the end. Runs of blank lines collapse to one; trailing blank lines go."""
    lines = (text or "").split("\n")
    out: list[str] = []
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if _LABEL_ONLY.match(line) and not nxt.strip():
            continue
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _drop_empty_value_lines(template: str, values: dict[str, str]) -> str:
    """Template lines whose placeholders all render empty are left out, so "Payment terms: {payment_terms}"
    disappears when there are no payment terms (v0.5.0)."""
    kept = []
    for line in template.split("\n"):
        names = [n.strip() for n in placeholders_in(line)]
        if names and all(n in values and not values[n] for n in names):
            continue
        kept.append(line)
    return "\n".join(kept)


def render(template: str, values: dict[str, str], drop_empty_lines: bool = False) -> str:
    """Fill the placeholders. Without a reply-by date the sentence asking for a reply by that date is omitted
    (v0.3.2) instead of rendering "reply by ." with an empty date. With ``drop_empty_lines`` (quote terms,
    v0.5.0) lines whose values are all empty, and labels left without a value, are omitted."""
    template = template or ""
    if "respond_by" in values and not values["respond_by"]:
        template = _drop_sentences_with(template, "respond_by")
    if drop_empty_lines:
        template = _drop_empty_value_lines(template, values)

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        return values.get((match.group(1) or "").strip(), token)

    text = _TOKEN.sub(replace, template or "")
    return drop_empty_labels(text) if drop_empty_lines else text


def _num(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value.normalize(), "f")
    return text


def items_table(rows: list[dict], language: str, digits: str | None = None) -> str:
    """Plain-text table: one block per item (no, name, quantity + unit, key specs, packaging, destination,
    Incoterm, required by). Blocks read well in e-mail, WhatsApp and letters, in both directions."""
    labels = LABELS.get(language, LABELS["en"])
    lines = []
    for index, row in enumerate(rows, start=1):
        head = f"{localize_digits(str(index), language, digits)}. {row['name']}"
        number = localize_digits(_num(row.get("quantity")), language, digits)
        quantity = " ".join(x for x in (number, row.get("unit") or "") if x)
        if quantity:
            head += f" — {labels['qty']}: {quantity}"
        lines.append(head)
        specs = [s for s in row.get("specs") or [] if s.get("key")][:MAX_SPECS_IN_TABLE]
        if specs:
            text = "; ".join(f"{s['key']}: {s.get('value', '')}{(' ' + s['unit']) if s.get('unit') else ''}"
                             for s in specs)
            lines.append(f"   {labels['specs']}: {text}")
        for key in ("packaging", "destination", "incoterm", "required_by", "note"):
            if row.get(key):
                lines.append(f"   {labels[key]}: {row[key]}")
    return "\n".join(lines)


_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def owner_digits(db) -> str:
    """The digit setting of the (single) user: "fa" or "latin"; Persian digits when nobody is set up yet."""
    from app.modules.system import users

    user = users.get_user(db)
    return (user.digits if user is not None and user.digits else None) or "fa"


def localize_digits(text: str, language: str, digits: str | None = None) -> str:
    """Persian digits in Persian texts unless the user chose Latin digits (v0.5.0). Only dates and numbers are
    passed through here; codes, e-mails and part numbers are never converted."""
    if language == "fa" and digits != "latin":
        return text.translate(_FA_DIGITS)
    return text


def format_date(value: date | None, language: str, digits: str | None = None) -> str:
    if value is None:
        return ""
    if language == "fa":
        from app.modules.sourcing.jalali import to_jalali

        y, m, d = to_jalali(value)
        return localize_digits(f"{y:04d}/{m:02d}/{d:02d}", language, digits)
    return value.isoformat()


# ---- CRUD ---------------------------------------------------------------------------------------

def get_template(db: Session, template_id: uuid.UUID) -> MessageTemplate:
    row = db.get(MessageTemplate, template_id)
    if row is None:
        raise NotFound("not_found", "Template not found")
    return row


def list_templates(db: Session, include_archived: bool = False, kind: str = "rfq") -> list[MessageTemplate]:
    query = select(MessageTemplate).where(MessageTemplate.kind == kind).order_by(
        MessageTemplate.language, MessageTemplate.channel, MessageTemplate.name)
    if not include_archived:
        query = query.where(MessageTemplate.status == "active")
    return list(db.scalars(query))


def default_template(db: Session, language: str, channel: str) -> MessageTemplate | None:
    """The default for (language, channel); phone/other use WhatsApp, letter falls back to e-mail, a missing
    language falls back to English."""
    channels = {"phone": ["whatsapp", "email"], "other": ["whatsapp", "email"], "letter": ["letter", "email"]}
    for lang in dict.fromkeys([language, "en"]):
        for ch in channels.get(channel, [channel]):
            row = db.scalar(select(MessageTemplate).where(
                MessageTemplate.kind == "rfq", MessageTemplate.language == lang, MessageTemplate.channel == ch,
                MessageTemplate.status == "active").order_by(MessageTemplate.is_default.desc(),
                                                             MessageTemplate.created_at))
            if row is not None:
                return row
    return None


def default_of_kind(db: Session, kind: str, language: str) -> MessageTemplate | None:
    """The active default of ``kind`` in ``language`` (English as fallback), e.g. the quote terms."""
    for lang in dict.fromkeys([language, "en"]):
        row = db.scalar(select(MessageTemplate).where(
            MessageTemplate.kind == kind, MessageTemplate.language == lang, MessageTemplate.status == "active")
            .order_by(MessageTemplate.is_default.desc(), MessageTemplate.created_at))
        if row is not None:
            return row
    return None


def _clear_default(db: Session, row: MessageTemplate, language: str | None = None, channel: str | None = None) -> None:
    """Only one default per (kind, language, channel): clear the others before this one becomes default."""
    query = update(MessageTemplate).where(
        MessageTemplate.kind == (row.kind or "rfq"), MessageTemplate.language == (language or row.language),
        MessageTemplate.channel == (channel or row.channel))
    if row.id is not None:
        query = query.where(MessageTemplate.id != row.id)
    db.execute(query.values(is_default=False))


def create_template(db: Session, data: dict, source: str, actor: str | None = None) -> MessageTemplate:
    kind = data.pop("kind", None) or "rfq"
    validate_template(data.get("subject_template") or "", data["body_template"], kind)
    row = MessageTemplate(kind=kind, **data)
    if row.is_default:
        _clear_default(db, row)
    db.add(row)
    flush(db, "invalid_template")
    events.record(db, "message_template", row.id, "create", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def update_template(db: Session, template_id: uuid.UUID, changes: dict, source: str,
                    actor: str | None = None) -> MessageTemplate:
    row = get_template(db, template_id)
    changes = {k: v for k, v in changes.items() if v is not None or k == "subject_template"}
    if changes.get("subject_template") is None and "subject_template" in changes:
        changes["subject_template"] = ""
    validate_template(changes.get("subject_template", row.subject_template),
                      changes.get("body_template", row.body_template), row.kind)
    if changes.get("is_default") or (row.is_default and ("language" in changes or "channel" in changes)):
        _clear_default(db, row, changes.get("language"), changes.get("channel"))
    changed = diff(row, changes)
    if changed:
        flush(db, "invalid_template")
        events.record(db, "message_template", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return row


def delete_template(db: Session, template_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_template(db, template_id)
    used = db.scalar(select(RfqRecipient.id).where(RfqRecipient.template_id == row.id).limit(1))
    if used:
        raise Conflict("in_use", "The template was used for RFQs; archive it instead", {"rfq_recipients": 1})
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "message_template", template_id, "delete", {"deleted": snapshot}, source, actor=actor)
