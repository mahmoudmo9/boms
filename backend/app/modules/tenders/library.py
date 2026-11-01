"""The company documents library (registration notice, VAT certificate, ...: recorded once, reused in envelopes)
and the envelope templates (a default seeded from SetadSuite's DEFAULT_TEMPLATE)."""
import uuid
from datetime import date, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.sourcing.common import flush, jsonable, row_snapshot
from app.modules.tenders.common import today
from app.modules.tenders.models import CompanyDocument, EnvelopeItem, EnvelopeTemplate, EnvelopeTemplateLine

EXPIRY_SOON_DAYS = 30
# SetadSuite COMPANY_DOC_SUGGESTIONS, categories mapped to BOMS codes
SUGGESTIONS = [
    ("آگهی تأسیس و آخرین تغییرات (روزنامه رسمی)", "registration"), ("اساسنامه", "registration"),
    ("گواهی ثبت‌نام ارزش افزوده", "tax"), ("گواهی یا اظهارنامه مالیاتی", "tax"),
    ("مفاصا حساب بیمه / فهرست بیمه", "insurance"), ("گواهینامه‌ها (ISO / ایمنی)", "certificates"),
    ("فهرست سوابق کاری و تأییدیه‌ها", "track_record"), ("گواهی رتبه / صلاحیت (در صورت درخواست)", "qualification"),
]


def doc_expiry(expires_on: date | None, on: date | None = None) -> tuple[str, int | None]:
    """(state, days left): ok / soon (within 30 days) / expired / none (SetadSuite doc_expiry)."""
    if expires_on is None:
        return "none", None
    days = (expires_on - (on or today())).days
    if days < 0:
        return "expired", days
    if days <= EXPIRY_SOON_DAYS:
        return "soon", days
    return "ok", days


def get_document(db: Session, doc_id: uuid.UUID) -> CompanyDocument:
    row = db.get(CompanyDocument, doc_id)
    if row is None:
        raise NotFound("not_found", "Company document not found")
    return row


def document_out(row: CompanyDocument) -> dict:
    state, days = doc_expiry(row.expires_on)
    return jsonable({**row_snapshot(row), "expiry": state, "days_left": days})


def list_documents(db: Session, *, expiry: str | None = None, include_archived: bool = False) -> list[dict]:
    query = select(CompanyDocument)
    if not include_archived:
        query = query.where(CompanyDocument.status == "active")
    rows = [document_out(r) for r in db.scalars(query.order_by(CompanyDocument.category, CompanyDocument.title))]
    return [r for r in rows if r["expiry"] == expiry] if expiry else rows


def create_document(db: Session, data: dict, source: str, actor: str | None = None) -> CompanyDocument:
    if data.get("document_id"):
        documents.get(db, data["document_id"])
    row = CompanyDocument(**{k: data.get(k) for k in ("title", "category", "document_id", "issued_on", "expires_on",
                                                      "note") if data.get(k) is not None})
    row.title = (row.title or "").strip()
    db.add(row)
    flush(db, "invalid_company_document")
    events.record(db, "company_document", row.id, "create", jsonable(row_snapshot(row)), source, actor=actor)
    return row


def update_document(db: Session, doc_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> CompanyDocument:
    row = get_document(db, doc_id)
    if changes.get("document_id"):
        documents.get(db, changes["document_id"])
    changed = {}
    for key in ("title", "category", "document_id", "issued_on", "expires_on", "note", "status"):
        if key in changes and changes[key] != getattr(row, key):
            if key in ("title", "category", "status") and changes[key] is None:
                continue
            changed[key] = {"old": getattr(row, key), "new": changes[key]}
            setattr(row, key, changes[key])
    if changed:
        flush(db, "invalid_company_document")
        events.record(db, "company_document", row.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return row


def usage_count(db: Session, doc_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(EnvelopeItem).where(EnvelopeItem.company_document_id == doc_id)) or 0


def delete_document(db: Session, doc_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    """A library document used by an envelope item cannot be deleted (archive it instead)."""
    row = get_document(db, doc_id)
    used = usage_count(db, row.id)
    if used:
        raise Conflict("in_use", "The document is used in tender envelopes; archive it instead", {"envelope_items": used})
    snapshot = row_snapshot(row)
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "company_document", doc_id, "delete", jsonable({"deleted": snapshot}), source, actor=actor)


def expiring(db: Session, within_days: int = EXPIRY_SOON_DAYS) -> list[dict]:
    """Active library documents expired or expiring within ``within_days`` (command center)."""
    until = today() + timedelta(days=within_days)
    rows = db.scalars(select(CompanyDocument).where(CompanyDocument.status == "active",
                                                    CompanyDocument.expires_on.is_not(None),
                                                    CompanyDocument.expires_on <= until)
                      .order_by(CompanyDocument.expires_on))
    return [document_out(r) for r in rows]


# ---- envelope templates -------------------------------------------------------------------------------------------

def get_template(db: Session, template_id: uuid.UUID) -> EnvelopeTemplate:
    row = db.get(EnvelopeTemplate, template_id)
    if row is None:
        raise NotFound("not_found", "Envelope template not found")
    return row


def default_template(db: Session) -> EnvelopeTemplate | None:
    return db.scalar(select(EnvelopeTemplate).where(EnvelopeTemplate.is_default, EnvelopeTemplate.status == "active"))


def template_lines(db: Session, template_id: uuid.UUID) -> list[EnvelopeTemplateLine]:
    return list(db.scalars(select(EnvelopeTemplateLine).where(EnvelopeTemplateLine.template_id == template_id)
                           .order_by(EnvelopeTemplateLine.envelope, EnvelopeTemplateLine.position)))


def template_out(db: Session, row: EnvelopeTemplate) -> dict:
    return jsonable({**row_snapshot(row), "lines": [row_snapshot(x) for x in template_lines(db, row.id)]})


def list_templates(db: Session) -> list[dict]:
    rows = db.scalars(select(EnvelopeTemplate).where(EnvelopeTemplate.status == "active")
                      .order_by(EnvelopeTemplate.is_default.desc(), EnvelopeTemplate.name))
    return [template_out(db, r) for r in rows]


def _write_lines(db: Session, template: EnvelopeTemplate, lines: list[dict]) -> None:
    for old in template_lines(db, template.id):
        db.delete(old)
    db.flush()
    positions: dict[str, int] = {}
    for line in lines:
        env = line["envelope"]
        positions[env] = positions.get(env, 0) + 1
        title = (line.get("title") or "").strip()
        if not title:
            raise AppError("title_required", "Every template line needs a title", status=422)
        db.add(EnvelopeTemplateLine(template_id=template.id, envelope=env, position=positions[env], title=title,
                                    kind=line.get("kind") or "document"))
    flush(db, "invalid_template_line")


def save_template(db: Session, template_id: uuid.UUID | None, data: dict, source: str, actor: str | None = None) -> EnvelopeTemplate:
    """Create or replace a template (name, default flag, its lines in order)."""
    row = get_template(db, template_id) if template_id else EnvelopeTemplate(name="", is_default=False)
    name = (data.get("name") or row.name or "").strip()
    if not name:
        raise AppError("name_required", "The template needs a name", status=422)
    row.name = name
    if template_id is None:
        db.add(row)
    if data.get("is_default"):
        db.execute(update(EnvelopeTemplate).where(EnvelopeTemplate.id != row.id).values(is_default=False))
        row.is_default = True
    flush(db, "invalid_template")
    if data.get("lines") is not None:
        _write_lines(db, row, data["lines"])
    events.record(db, "envelope_template", row.id, "create" if template_id is None else "update",
                  jsonable({"name": row.name, "is_default": row.is_default, "lines": len(data.get("lines") or [])}),
                  source, actor=actor)
    return row


def delete_template(db: Session, template_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = get_template(db, template_id)
    if row.is_default:
        raise Conflict("default_template", "Make another template the default first")
    for line in template_lines(db, row.id):
        db.delete(line)
    db.flush()
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "envelope_template", template_id, "delete", {"name": row.name}, source, actor=actor)
