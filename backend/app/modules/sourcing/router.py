import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, File, Query, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.schemas import page_params
from app.core.web import request_source
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.parties import service as parties
from app.modules.sourcing import (
    capabilities,
    coverage,
    extract,
    importing,
    inquiries,
    items,
    offers,
    rfq,
    templates,
)
from app.modules.sourcing.common import jsonable, linked_documents, row_snapshot
from app.modules.sourcing.schemas import (
    CancelIn,
    CapabilityIn,
    CapabilitySet,
    ConfirmSubjectIn,
    ConfirmTitleIn,
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
    MarkSentIn,
    NoCoverageIn,
    NoteIn,
    OfferCreate,
    OfferHeader,
    OfferItemPatch,
    OfferStatusIn,
    ProductFromItemIn,
    RecipientIn,
    RecipientPatch,
    RejectIn,
    RfqCreate,
    RfqPatch,
    SelectOfferIn,
    TemplateIn,
    TemplatePatch,
    TemplatePreviewIn,
)
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
inquiries_router = APIRouter(prefix="/api/inquiries", tags=["sourcing"])
cases_router = APIRouter(prefix="/api/cases", tags=["sourcing"])
items_router = APIRouter(prefix="/api/line-items", tags=["sourcing"])


def _items_out(rows) -> list[dict]:
    return [LineItemOut.model_validate(r).model_dump(mode="json") for r in rows]


def _party_names(db: Session, party_ids) -> dict:
    out = {}
    for pid in {p for p in party_ids if p}:
        party = parties.get_party(db, pid)
        out[pid] = {"party_name_fa": party.name_fa, "party_name_en": party.name_en}
    return out


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
        **_party_names(db, [row.party_id]).get(row.party_id, {}),
    }


@inquiries_router.get("")
def list_inquiries(_: CurrentUser, db: Db, q: str | None = None,
                   status: Literal["new", "needs_info", "ready_for_screening", "rejected", "no_reply",
                                   "converted"] | None = None,
                   party_id: uuid.UUID | None = None, page: int = 1,
                   page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    rows, total = inquiries.list_inquiries(db, q=q, status=status, party_id=party_id, page=page, page_size=page_size)
    names = _party_names(db, [r.party_id for r in rows])
    return {"items": [{**InquiryOut.model_validate(r).model_dump(mode="json"), **names.get(r.party_id, {})} for r in rows],
            "total": total, "page": page, "page_size": page_size}


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


@inquiries_router.delete("/{inquiry_id}")
def delete_inquiry(inquiry_id: uuid.UUID, request: Request, user: CurrentUser, db: Db, cascade: bool = False,
                   body: Annotated[ConfirmSubjectIn | None, Body()] = None):
    if cascade:
        counts = inquiries.cascade_delete_inquiry(db, inquiry_id, body.confirm_subject if body else None,
                                                  request_source(request), user.username)
        db.commit()
        return {"deleted": True, "counts": counts}
    inquiries.delete_inquiry(db, inquiry_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


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
        **_party_names(db, [case.party_id]).get(case.party_id, {}),
    }


@cases_router.get("")
def list_cases(_: CurrentUser, db: Db, q: str | None = None,
               status: Literal["open", "won", "lost", "closed", "cancelled"] | None = None,
               party_id: uuid.UUID | None = None, page: int = 1, page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    rows, total = inquiries.list_cases(db, q=q, status=status, party_id=party_id, page=page, page_size=page_size)
    names = _party_names(db, [r.party_id for r in rows])
    return {"items": [{**CaseOut.model_validate(r).model_dump(mode="json"), **names.get(r.party_id, {})} for r in rows],
            "total": total, "page": page, "page_size": page_size}


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


@cases_router.delete("/{case_id}")
def delete_case(case_id: uuid.UUID, request: Request, user: CurrentUser, db: Db, cascade: bool = False,
                body: Annotated[ConfirmTitleIn | None, Body()] = None):
    if cascade:
        counts = inquiries.cascade_delete_case(db, case_id, body.confirm_title if body else None,
                                               request_source(request), user.username)
        db.commit()
        return {"deleted": True, "counts": counts}
    inquiries.delete_case(db, case_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


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


@items_router.post("/{item_id}/select")
def select_offer(item_id: uuid.UUID, body: SelectOfferIn, request: Request, user: CurrentUser, db: Db):
    coverage.select_offer(db, item_id, body.offer_item_id, body.reason, request_source(request), user.username)
    db.commit()
    return item_detail(db, item_id)


@items_router.post("/{item_id}/create-product")
def create_product_from_item(item_id: uuid.UUID, body: ProductFromItemIn, request: Request, response: Response,
                             user: CurrentUser, db: Db):
    """"Create product from this item": name (Persian or English by script), unit and HS code; links the item."""
    from app.modules.catalog import service as catalog

    item = items.get_item(db, item_id)
    persian = any("\u0600" <= ch <= "\u06ff" for ch in item.name)
    data = {"name_fa": body.name_fa or (item.name if persian else None),
            "name_en": body.name_en or (None if persian else item.name),
            "default_unit_code": item.unit_code, "hs_code": item.hs_code, "confirm_duplicate": body.confirm_duplicate}
    product, duplicates = catalog.create_product(db, data, request_source(request), user.username)
    if product is None:
        response.status_code = 200
        return {"created": False, "possible_duplicates": duplicates}
    items.update_item(db, item.id, {"product_id": product.id}, request_source(request), user.username)
    db.commit()
    response.status_code = 201
    return {"created": True, "product_id": str(product.id), "possible_duplicates": duplicates,
            "item": item_detail(db, item.id)}


@cases_router.get("/{case_id}/coverage")
def case_coverage(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return coverage.coverage(db, case_id)


@cases_router.get("/{case_id}/comparison")
def case_comparison(case_id: uuid.UUID, _: CurrentUser, db: Db, item_id: uuid.UUID | None = None):
    return coverage.comparison(db, case_id, item_id)


# ---- RFQs -----------------------------------------------------------------------------------------

rfqs_router = APIRouter(prefix="/api/rfqs", tags=["sourcing"])


def rfq_detail(db: Session, rfq_id: uuid.UUID) -> dict:
    row = rfq.get_rfq(db, rfq_id)
    return {
        **jsonable(row_snapshot(row)),
        "items": [{**jsonable(row_snapshot(ri)), "line_item": LineItemOut.model_validate(li).model_dump(mode="json")}
                  for ri, li in rfq.rfq_items(db, row.id)],
        "recipients": [rfq.recipient_out(db, r) for r in rfq.recipients_of(db, row.id)],
    }


@rfqs_router.get("")
def list_rfqs(_: CurrentUser, db: Db, case_id: uuid.UUID | None = None,
              status: Literal["draft", "sent", "answered", "no_response", "expired", "cancelled"] | None = None):
    return [rfq_detail(db, r.id) for r in rfq.list_rfqs(db, case_id, status)]


@rfqs_router.get("/suppliers")
def rfq_suppliers(_: CurrentUser, db: Db, q: str | None = None, page_size: Annotated[int, Query(le=200)] = 50):
    """Parties with the supplier role (active), with their funnel stage and default channel/language."""
    rows, _total = parties.list_parties(db, q=q, role="supplier", status="active", sort="name", order="asc",
                                        page=1, page_size=page_size)
    roles = parties.roles_for(db, [p.id for p in rows])
    return [{"party_id": str(p.id), "name_fa": p.name_fa, "name_en": p.name_en, "country_iso2": p.country_iso2,
             "do_not_contact": p.do_not_contact,
             "supplier_stage": next((r.stage for r in roles[p.id] if r.role == "supplier"), None),
             **rfq.defaults_for_party(p)} for p in rows]


@rfqs_router.get("/supplier-suggestions")
def rfq_supplier_suggestions(_: CurrentUser, db: Db, item_ids: Annotated[list[uuid.UUID], Query()],
                             exclude: Annotated[list[uuid.UUID] | None, Query()] = None):
    codes = [items.get_item(db, i).hs_code for i in item_ids]
    return capabilities.suggest_suppliers(db, [c for c in codes if c], set(exclude or []))


@rfqs_router.post("", status_code=201)
def create_rfq(body: RfqCreate, request: Request, user: CurrentUser, db: Db):
    row = rfq.create_rfq(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return rfq_detail(db, row.id)


@rfqs_router.get("/{rfq_id}")
def get_rfq(rfq_id: uuid.UUID, _: CurrentUser, db: Db):
    return rfq_detail(db, rfq_id)


@rfqs_router.patch("/{rfq_id}")
def update_rfq(rfq_id: uuid.UUID, body: RfqPatch, request: Request, user: CurrentUser, db: Db):
    changes = body.model_dump(exclude_unset=True)
    if "items" in changes and changes["items"] is None:
        changes.pop("items")
    rfq.update_rfq(db, rfq_id, changes, request_source(request), user.username)
    db.commit()
    return rfq_detail(db, rfq_id)


@rfqs_router.post("/{rfq_id}/cancel")
def cancel_rfq(rfq_id: uuid.UUID, body: CancelIn, request: Request, user: CurrentUser, db: Db):
    rfq.cancel_rfq(db, rfq_id, body.reason, request_source(request), user.username)
    db.commit()
    return rfq_detail(db, rfq_id)


@rfqs_router.delete("/{rfq_id}", status_code=204)
def delete_rfq(rfq_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    rfq.delete_rfq(db, rfq_id, request_source(request), user.username)
    db.commit()


@rfqs_router.get("/{rfq_id}/export.xlsx")
def export_rfq(rfq_id: uuid.UUID, _: CurrentUser, db: Db, language: Literal["en", "fa"] = "en"):
    data = rfq.export_xlsx(db, rfq_id, language)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="rfq-{rfq_id}.xlsx"'})


@rfqs_router.post("/{rfq_id}/recipients", status_code=201)
def add_recipient(rfq_id: uuid.UUID, body: RecipientIn, request: Request, user: CurrentUser, db: Db):
    rfq.add_recipient(db, rfq_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return rfq_detail(db, rfq_id)


@rfqs_router.patch("/recipients/{recipient_id}")
def update_recipient(recipient_id: uuid.UUID, body: RecipientPatch, request: Request, user: CurrentUser, db: Db):
    row = rfq.update_recipient(db, recipient_id, body.model_dump(exclude_unset=True), request_source(request),
                               user.username)
    db.commit()
    return rfq.recipient_out(db, row)


@rfqs_router.delete("/recipients/{recipient_id}", status_code=204)
def remove_recipient(recipient_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    rfq.remove_recipient(db, recipient_id, request_source(request), user.username)
    db.commit()


@rfqs_router.post("/recipients/{recipient_id}/mark-sent")
def mark_sent(recipient_id: uuid.UUID, body: MarkSentIn, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump()
    if data.get("followup") is None:
        data.pop("followup")
    row = rfq.mark_sent(db, recipient_id, data, request_source(request), user.username)
    db.commit()
    return rfq.recipient_out(db, row)


@rfqs_router.post("/recipients/{recipient_id}/decline")
def decline_recipient(recipient_id: uuid.UUID, body: NoteIn, request: Request, user: CurrentUser, db: Db):
    row = rfq.decline(db, recipient_id, body.note, request_source(request), user.username)
    db.commit()
    return rfq.recipient_out(db, row)


# ---- message templates -------------------------------------------------------------------------------

templates_router = APIRouter(prefix="/api/message-templates", tags=["sourcing"])


@templates_router.get("")
def list_templates(_: CurrentUser, db: Db, include_archived: bool = False,
                   kind: Literal["rfq", "quote_terms"] = "rfq"):
    return {"placeholders": list(templates.PLACEHOLDERS_BY_KIND[kind]),
            "items": [jsonable(row_snapshot(t)) for t in templates.list_templates(db, include_archived, kind)]}


@templates_router.post("", status_code=201)
def create_template(body: TemplateIn, request: Request, user: CurrentUser, db: Db):
    row = templates.create_template(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return jsonable(row_snapshot(row))


@templates_router.post("/preview")
def preview_template(body: TemplatePreviewIn, _: CurrentUser, db: Db):
    templates.validate_template(body.subject_template, body.body_template, body.kind)
    if body.kind == "quote_terms":
        values = {"buyer_name": "ACME Trading", "valid_until": templates.format_date(date.today(), body.language),
                  "payment_terms": "30% advance, 70% before shipment", "incoterm": "CIF Bandar Abbas",
                  "lead_time": "45 days", "bank_details": "Bank / account / IBAN"}
        return {"subject": templates.render(body.subject_template, values),
                "body": templates.render(body.body_template, values)}
    sample = templates.items_table([{"name": "Polyethylene HD", "quantity": Decimal("20"), "unit": "t",
                                     "specs": [{"key": "Grade", "value": "PE100"}], "incoterm": "CIF Bandar Abbas"}],
                                   body.language)
    values = {"supplier_name": "ACME Trading", "contact_name": "Mr. Smith", "case_title": "Sample case",
              "items_table": sample, "respond_by": templates.format_date(date.today(), body.language),
              "signature": rfq.signature(db, body.language)}
    return {"subject": templates.render(body.subject_template, values),
            "body": templates.render(body.body_template, values)}


@templates_router.patch("/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplatePatch, request: Request, user: CurrentUser, db: Db):
    row = templates.update_template(db, template_id, body.model_dump(exclude_unset=True), request_source(request),
                                    user.username)
    db.commit()
    return jsonable(row_snapshot(row))


@templates_router.delete("/{template_id}", status_code=204)
def delete_template(template_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    templates.delete_template(db, template_id, request_source(request), user.username)
    db.commit()


# ---- offers -------------------------------------------------------------------------------------------

offers_router = APIRouter(prefix="/api/offers", tags=["sourcing"])


def offer_detail(db: Session, offer_id: uuid.UUID) -> dict:
    row = offers.get_offer(db, offer_id)
    party = parties.get_party(db, row.party_id)
    contact = parties.get_contact(db, row.contact_id) if row.contact_id else None
    status_note = None
    if row.status == "withdrawn":  # the note given when withdrawing (v0.4.0), from the offer history
        last, _ = events.list_events(db, entity_type="offer", entity_id=str(row.id), action="status", page_size=1)
        status_note = (last[0].data or {}).get("note") if last else None
    return {**jsonable(row_snapshot(row)), "party_name_fa": party.name_fa, "party_name_en": party.name_en,
            "status_note": status_note,
            "contact_name_fa": contact.name_fa if contact else None,
            "contact_name_en": contact.name_en if contact else None,
            "valid": offers.is_valid(row),
            "items": [jsonable(row_snapshot(i)) for i in offers.offer_items(db, row.id)],
            "documents": _documents(db, "offer", row.id)}


@offers_router.get("")
def list_offers(_: CurrentUser, db: Db, case_id: uuid.UUID | None = None, party_id: uuid.UUID | None = None):
    return [offer_detail(db, o.id) for o in offers.list_offers(db, case_id, party_id)]


@offers_router.post("", status_code=201)
def record_offer(body: OfferCreate, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump()
    if data.get("followup") is None:
        data.pop("followup")
    row = offers.record_offer(db, data, request_source(request), user.username)
    db.commit()
    return offer_detail(db, row.id)


@offers_router.get("/{offer_id}")
def get_offer(offer_id: uuid.UUID, _: CurrentUser, db: Db):
    return offer_detail(db, offer_id)


@offers_router.patch("/{offer_id}")
def update_offer(offer_id: uuid.UUID, body: OfferHeader, request: Request, user: CurrentUser, db: Db):
    offers.update_offer(db, offer_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return offer_detail(db, offer_id)


@offers_router.patch("/items/{offer_item_id}")
def update_offer_item(offer_item_id: uuid.UUID, body: OfferItemPatch, request: Request, user: CurrentUser, db: Db):
    row = offers.update_offer_item(db, offer_item_id, body.model_dump(exclude_unset=True), request_source(request),
                                   user.username)
    db.commit()
    return offer_detail(db, row.offer_id)


@offers_router.post("/{offer_id}/status")
def set_offer_status(offer_id: uuid.UUID, body: OfferStatusIn, request: Request, user: CurrentUser, db: Db):
    offers.set_offer_status(db, offer_id, body.status, body.note, request_source(request), user.username)
    db.commit()
    return offer_detail(db, offer_id)


@offers_router.delete("/{offer_id}", status_code=204)
def delete_offer(offer_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    offers.delete_offer(db, offer_id, request_source(request), user.username)
    db.commit()


@offers_router.post("/{offer_id}/documents", status_code=201)
def link_offer_document(offer_id: uuid.UUID, body: DocumentLinkIn, request: Request, user: CurrentUser, db: Db):
    offers.get_offer(db, offer_id)
    return _link(db, "offer", offer_id, body.document_id, request, user)


@offers_router.delete("/{offer_id}/documents/{link_id}", status_code=204)
def unlink_offer_document(offer_id: uuid.UUID, link_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    _unlink(db, "offer", offer_id, link_id, request, user)


# ---- capabilities -------------------------------------------------------------------------------------

capabilities_router = APIRouter(prefix="/api/capabilities", tags=["sourcing"])


@capabilities_router.get("/codes")
def capability_codes(_: CurrentUser, db: Db, kind: Literal["hs", "isic"], q: str | None = None,
                     parent: str | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 30):
    return capabilities.search_codes(db, kind, q, parent, limit)


@capabilities_router.get("/party/{party_id}")
def party_capabilities(party_id: uuid.UUID, _: CurrentUser, db: Db):
    parties.get_party(db, party_id)
    return capabilities.capabilities_of(db, party_id)


@capabilities_router.post("/party/{party_id}", status_code=201)
def add_capability(party_id: uuid.UUID, body: CapabilityIn, request: Request, user: CurrentUser, db: Db):
    capabilities.add(db, party_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return capabilities.capabilities_of(db, party_id)


@capabilities_router.put("/party/{party_id}")
def set_capabilities(party_id: uuid.UUID, body: CapabilitySet, request: Request, user: CurrentUser, db: Db):
    result = capabilities.replace(db, party_id, [i.model_dump() for i in body.items], request_source(request),
                                  user.username)
    db.commit()
    return result


@capabilities_router.delete("/{capability_id}", status_code=204)
def remove_capability(capability_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    capabilities.remove(db, capability_id, request_source(request), user.username)
    db.commit()


ROUTERS = [inquiries_router, cases_router, items_router, rfqs_router, templates_router, offers_router,
           capabilities_router]
