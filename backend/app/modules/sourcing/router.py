import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.schemas import page_params
from app.core.web import request_source
from app.modules.documents import service as documents
from app.modules.parties import service as parties
from app.modules.sourcing import extract, importing, inquiries, items
from app.modules.sourcing.common import linked_documents
from app.modules.sourcing.schemas import (
    CancelIn,
    CaseCreate,
    CaseOut,
    CasePatch,
    ConvertIn,
    DecisionIn,
    DecisionOut,
    DocumentLinkIn,
    ImportParseIn,
    ImportPreviewIn,
    InquiryCreate,
    InquiryOut,
    InquiryPatch,
    LineItemAdd,
    LineItemBulk,
    LineItemFields,
    LineItemOut,
    NoCoverageIn,
    RejectIn,
)
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
inquiries_router = APIRouter(prefix="/api/inquiries", tags=["sourcing"])
cases_router = APIRouter(prefix="/api/cases", tags=["sourcing"])
items_router = APIRouter(prefix="/api/line-items", tags=["sourcing"])


def _items_out(rows) -> list[dict]:
    return [LineItemOut.model_validate(r).model_dump(mode="json") for r in rows]


def _documents(db: Session, entity_type: str, entity_id) -> list[dict]:
    return linked_documents(db, entity_type, [entity_id])


def _link(db: Session, entity_type: str, entity_id, document_id, request: Request, user) -> dict:
    link = parties.link_document(db, entity_type, entity_id, document_id, request_source(request), user.username)
    db.commit()
    return {"link_id": link.id}


def _unlink(db: Session, entity_type: str, entity_id, link_id, request: Request, user) -> None:
    parties.unlink_document(db, entity_type, entity_id, link_id, request_source(request), user.username)
    db.commit()


# ---- inquiries ------------------------------------------------------------------------------

def inquiry_detail(db: Session, inquiry_id: uuid.UUID) -> dict:
    row = inquiries.get_inquiry(db, inquiry_id)
    decision = inquiries.get_decision(db, row.id)
    item_rows = items.items_of(db, inquiry_id=row.id)
    case = inquiries.case_of(db, row.id)
    return {
        **InquiryOut.model_validate(row).model_dump(mode="json"),
        "items": _items_out(item_rows),
        "warnings": items.duplicate_warnings(item_rows),
        "decision": DecisionOut.model_validate(decision).model_dump(mode="json") if decision else None,
        "gate": inquiries.gate(db, row),
        "case_id": str(case.id) if case else None,
        "documents": _documents(db, "inquiry", row.id),
    }


@inquiries_router.get("")
def list_inquiries(_: CurrentUser, db: Db, q: str | None = None,
                   status: Literal["new", "needs_info", "ready_for_screening", "rejected", "no_reply",
                                   "converted"] | None = None,
                   party_id: uuid.UUID | None = None, page: int = 1,
                   page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    rows, total = inquiries.list_inquiries(db, q=q, status=status, party_id=party_id, page=page, page_size=page_size)
    return {"items": [InquiryOut.model_validate(r).model_dump(mode="json") for r in rows], "total": total,
            "page": page, "page_size": page_size}


@inquiries_router.get("/prefill")
def prefill(interaction_id: uuid.UUID, _: CurrentUser, db: Db):
    return inquiries.prefill_from_interaction(db, interaction_id)


@inquiries_router.get("/payment-terms")
def payment_terms(_: CurrentUser, db: Db):
    return [{"code": t.code, "label_fa": t.label_fa, "label_en": t.label_en, "requires_reason": t.requires_reason}
            for t in inquiries.payment_terms(db)]


@inquiries_router.post("", status_code=201)
def create_inquiry(body: InquiryCreate, request: Request, user: CurrentUser, db: Db):
    row = inquiries.create_inquiry(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return inquiry_detail(db, row.id)


@inquiries_router.get("/{inquiry_id}")
def get_inquiry(inquiry_id: uuid.UUID, _: CurrentUser, db: Db):
    return inquiry_detail(db, inquiry_id)


@inquiries_router.patch("/{inquiry_id}")
def update_inquiry(inquiry_id: uuid.UUID, body: InquiryPatch, request: Request, user: CurrentUser, db: Db):
    inquiries.update_inquiry(db, inquiry_id, body.model_dump(exclude_unset=True), request_source(request),
                             user.username)
    db.commit()
    return inquiry_detail(db, inquiry_id)


@inquiries_router.post("/{inquiry_id}/reject")
def reject_inquiry(inquiry_id: uuid.UUID, body: RejectIn, request: Request, user: CurrentUser, db: Db):
    inquiries.reject_inquiry(db, inquiry_id, body.reason, request_source(request), user.username)
    db.commit()
    return inquiry_detail(db, inquiry_id)


@inquiries_router.delete("/{inquiry_id}", status_code=204)
def delete_inquiry(inquiry_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    inquiries.delete_inquiry(db, inquiry_id, request_source(request), user.username)
    db.commit()


@inquiries_router.put("/{inquiry_id}/decision")
def set_decision(inquiry_id: uuid.UUID, body: DecisionIn, request: Request, user: CurrentUser, db: Db):
    inquiries.set_decision(db, inquiry_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return inquiry_detail(db, inquiry_id)


@inquiries_router.post("/{inquiry_id}/convert", status_code=201)
def convert(inquiry_id: uuid.UUID, body: ConvertIn, request: Request, user: CurrentUser, db: Db):
    case = inquiries.convert(db, inquiry_id, body.title, request_source(request), user.username)
    db.commit()
    return case_detail(db, case.id)


@inquiries_router.post("/{inquiry_id}/documents", status_code=201)
def link_inquiry_document(inquiry_id: uuid.UUID, body: DocumentLinkIn, request: Request, user: CurrentUser, db: Db):
    inquiries.get_inquiry(db, inquiry_id)
    return _link(db, "inquiry", inquiry_id, body.document_id, request, user)


@inquiries_router.delete("/{inquiry_id}/documents/{link_id}", status_code=204)
def unlink_inquiry_document(inquiry_id: uuid.UUID, link_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    _unlink(db, "inquiry", inquiry_id, link_id, request, user)


# ---- cases ----------------------------------------------------------------------------------

def case_detail(db: Session, case_id: uuid.UUID) -> dict:
    case = inquiries.get_case(db, case_id)
    item_rows = items.items_of(db, case_id=case.id)
    return {
        **CaseOut.model_validate(case).model_dump(mode="json"),
        "items": _items_out(item_rows),
        "warnings": items.duplicate_warnings(item_rows),
        "documents": _documents(db, "case", case.id),
    }


@cases_router.get("")
def list_cases(_: CurrentUser, db: Db, q: str | None = None,
               status: Literal["open", "won", "lost", "closed", "cancelled"] | None = None,
               party_id: uuid.UUID | None = None, page: int = 1, page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    rows, total = inquiries.list_cases(db, q=q, status=status, party_id=party_id, page=page, page_size=page_size)
    return {"items": [CaseOut.model_validate(r).model_dump(mode="json") for r in rows], "total": total, "page": page,
            "page_size": page_size}


@cases_router.post("", status_code=201)
def create_case(body: CaseCreate, request: Request, user: CurrentUser, db: Db):
    case = inquiries.create_case(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return case_detail(db, case.id)


@cases_router.get("/{case_id}")
def get_case(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return case_detail(db, case_id)


@cases_router.patch("/{case_id}")
def update_case(case_id: uuid.UUID, body: CasePatch, request: Request, user: CurrentUser, db: Db):
    inquiries.update_case(db, case_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return case_detail(db, case_id)


@cases_router.delete("/{case_id}", status_code=204)
def delete_case(case_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    inquiries.delete_case(db, case_id, request_source(request), user.username)
    db.commit()


@cases_router.post("/{case_id}/documents", status_code=201)
def link_case_document(case_id: uuid.UUID, body: DocumentLinkIn, request: Request, user: CurrentUser, db: Db):
    inquiries.get_case(db, case_id)
    return _link(db, "case", case_id, body.document_id, request, user)


@cases_router.delete("/{case_id}/documents/{link_id}", status_code=204)
def unlink_case_document(case_id: uuid.UUID, link_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    _unlink(db, "case", case_id, link_id, request, user)


# ---- line items -----------------------------------------------------------------------------

def item_detail(db: Session, item_id: uuid.UUID) -> dict:
    row = items.get_item(db, item_id)
    return {**LineItemOut.model_validate(row).model_dump(mode="json"), "documents": _documents(db, "line_item", row.id)}


@items_router.post("", status_code=201)
def add_item(body: LineItemAdd, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump(exclude_none=True)
    inquiry_id, case_id = data.pop("inquiry_id", None), data.pop("case_id", None)
    (row,) = items.add_items(db, inquiry_id, case_id, [data], request_source(request), user.username)
    db.commit()
    return item_detail(db, row.id)


@items_router.post("/bulk", status_code=201)
def add_items(body: LineItemBulk, request: Request, user: CurrentUser, db: Db):
    rows = items.add_items(db, body.inquiry_id, body.case_id, [i.model_dump(exclude_none=True) for i in body.items],
                           request_source(request), user.username)
    db.commit()
    owner_rows = items.items_of(db, inquiry_id=rows[0].inquiry_id, case_id=rows[0].case_id)
    return {"items": _items_out(rows), "warnings": items.duplicate_warnings(owner_rows)}


@items_router.get("/spec-keys")
def spec_keys(_: CurrentUser, db: Db, q: str | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    return items.spec_key_suggestions(db, q, limit)


@items_router.post("/import/parse")
def import_parse(body: ImportParseIn, _: CurrentUser,
                 delimiter: Literal["auto", "tab", "comma", "semicolon", "lines"] = "auto"):
    rows = importing.parse_text(body.text, delimiter)
    mapping, header = importing.suggest_mapping(rows)
    return {"rows": rows, "mapping": mapping, "has_header": header}


@items_router.post("/import/upload")
async def import_upload(_: CurrentUser, file: Annotated[UploadFile, File()]):
    data = await file.read(importing.MAX_XLSX_BYTES + 1)
    rows = importing.parse_upload(file.filename or "", data)
    mapping, header = importing.suggest_mapping(rows)
    return {"rows": rows, "mapping": mapping, "has_header": header}


@items_router.post("/import/preview")
def import_preview(body: ImportPreviewIn, _: CurrentUser, db: Db):
    result = importing.preview(db, body.rows, [m.model_dump() for m in body.mapping], body.skip_header)
    existing = items.items_of(db, inquiry_id=body.inquiry_id, case_id=body.case_id)
    names = {(i.name or "").strip().lower() for i in existing if i.status != "cancelled"}
    seen: set[str] = set()
    for row in result:
        name = (row["item"].get("name") or "").strip().lower()
        if name and (name in names or name in seen):
            row["warnings"] = [{"code": "duplicate_name"}]
        seen.add(name)
    return {"rows": result, "errors": sum(1 for r in result if r["errors"])}


@items_router.get("/extractor")
def extractor_status(_: CurrentUser):
    ex = extract.get_extractor()
    return {"name": ex.name, "configured": ex.is_configured()}


@items_router.post("/extract")
def extract_items(body: ImportParseIn, _: CurrentUser):
    ex = extract.get_extractor()
    if not ex.is_configured():
        raise AppError("extractor_not_configured", "Item extraction is not configured", status=409)
    result = ex.extract(body.text)
    return {"items": result.items, "message": result.message}


@items_router.get("/document-text/{document_id}")
def document_text(document_id: uuid.UUID, _: CurrentUser, db: Db):
    """Extracted text of an attached PDF/document, shown beside the item form ("copy line into item")."""
    doc = documents.get(db, document_id)
    return {"document_id": str(doc.id), "title": doc.title, "text_status": doc.text_status,
            "text": doc.text_content or ""}


@items_router.get("/{item_id}")
def get_item(item_id: uuid.UUID, _: CurrentUser, db: Db):
    return item_detail(db, item_id)


@items_router.patch("/{item_id}")
def update_item(item_id: uuid.UUID, body: LineItemFields, request: Request, user: CurrentUser, db: Db):
    items.update_item(db, item_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return item_detail(db, item_id)


@items_router.delete("/{item_id}", status_code=204)
def delete_item(item_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    items.delete_item(db, item_id, request_source(request), user.username)
    db.commit()


@items_router.post("/{item_id}/cancel")
def cancel_item(item_id: uuid.UUID, body: CancelIn, request: Request, user: CurrentUser, db: Db):
    items.cancel_item(db, item_id, body.reason, request_source(request), user.username)
    db.commit()
    return item_detail(db, item_id)


@items_router.post("/{item_id}/no-coverage")
def mark_no_coverage(item_id: uuid.UUID, body: NoCoverageIn, request: Request, user: CurrentUser, db: Db):
    items.set_no_coverage(db, item_id, body.reason, request_source(request), user.username)
    db.commit()
    return item_detail(db, item_id)


@items_router.delete("/{item_id}/no-coverage")
def clear_no_coverage(item_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    items.set_no_coverage(db, item_id, None, request_source(request), user.username)
    db.commit()
    return item_detail(db, item_id)


@items_router.post("/{item_id}/documents", status_code=201)
def link_item_document(item_id: uuid.UUID, body: DocumentLinkIn, request: Request, user: CurrentUser, db: Db):
    items.get_item(db, item_id)
    return _link(db, "line_item", item_id, body.document_id, request, user)


@items_router.delete("/{item_id}/documents/{link_id}", status_code=204)
def unlink_item_document(item_id: uuid.UUID, link_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    _unlink(db, "line_item", item_id, link_id, request, user)


ROUTERS = [inquiries_router, cases_router, items_router]
