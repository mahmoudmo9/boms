"""Quotes API: proforma invoices, approval, outputs (HTML / PDF / Word), sending, outcomes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from app.modules.costing import service as costing
from app.modules.parties import service as parties
from app.modules.quotes import output, service
from app.modules.quotes.schemas import (
    CaseResultIn,
    MarkSentIn,
    OutcomesIn,
    OutputIn,
    QuoteCreate,
    QuoteItemPatch,
    QuotePatch,
    ReasonIn,
    ReviseIn,
)
from app.modules.sourcing import items as sourcing_items
from app.modules.sourcing.common import jsonable, row_snapshot
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api/quotes", tags=["quotes"])


def quote_detail(db: Session, quote_id: uuid.UUID) -> dict:
    quote = service.get_quote(db, quote_id)
    names = {i.id: i.name for i in sourcing_items.items_of(db, case_id=quote.case_id)}
    buyer = parties.get_party(db, quote.buyer_party_id) if quote.buyer_party_id else None
    contact = parties.get_contact(db, quote.contact_id) if quote.contact_id else None
    sheet = costing.get_sheet(db, quote.cost_sheet_id)
    return jsonable({
        **row_snapshot(quote),
        "decimals": costing.currency_decimals(db, quote.currency),
        "buyer_name_fa": buyer.name_fa if buyer else None, "buyer_name_en": buyer.name_en if buyer else None,
        "contact_name_fa": contact.name_fa if contact else None, "contact_name_en": contact.name_en if contact else None,
        "cost_sheet": {"id": sheet.id, "version": sheet.version, "status": sheet.status},
        "items": [{**row_snapshot(r), "name": names.get(r.line_item_id, "")} for r in service.items_of(db, quote.id)],
        "outputs": output.outputs_of(db, quote.id),
        "approval": service.approval_check(db, quote) if quote.status == "draft" else None,
        "default_followup": service.default_followup(quote) if quote.status == "approved" else None,
    })


def quote_row(db: Session, quote) -> dict:
    buyer = parties.get_party(db, quote.buyer_party_id) if quote.buyer_party_id else None
    return jsonable({**{k: getattr(quote, k) for k in ("id", "case_id", "number", "version", "status", "currency",
                                                       "subtotal", "total", "valid_until", "sent_at", "created_at",
                                                       "price_basis", "language")},
                     "buyer_party_id": quote.buyer_party_id,
                     "buyer_name_fa": buyer.name_fa if buyer else None, "buyer_name_en": buyer.name_en if buyer else None})


@router.get("")
def list_quotes(_: CurrentUser, db: Db, case_id: uuid.UUID | None = None, party_id: uuid.UUID | None = None,
                status: str | None = None):
    return [quote_row(db, q) for q in service.list_quotes(db, case_id=case_id, party_id=party_id, status=status)]


@router.get("/outcome-reasons")
def outcome_reasons(_: CurrentUser, db: Db):
    return [jsonable(row_snapshot(r)) for r in service.outcome_reasons(db)]


@router.get("/by-product/{product_id}")
def quotes_for_product(product_id: uuid.UUID, _: CurrentUser, db: Db):
    return service.quotes_for_product(db, product_id)


@router.post("", status_code=201)
def create_quote(body: QuoteCreate, request: Request, user: CurrentUser, db: Db):
    row = service.create_quote(db, body.model_dump(), user.calendar, request_source(request), user.username)
    db.commit()
    return quote_detail(db, row.id)


@router.get("/{quote_id}")
def get_quote(quote_id: uuid.UUID, _: CurrentUser, db: Db):
    return quote_detail(db, quote_id)


@router.patch("/{quote_id}")
def update_quote(quote_id: uuid.UUID, body: QuotePatch, request: Request, user: CurrentUser, db: Db):
    service.update_quote(db, quote_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return quote_detail(db, quote_id)


@router.delete("/{quote_id}", status_code=204)
def delete_quote(quote_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_quote(db, quote_id, request_source(request), user.username)
    db.commit()


@router.post("/{quote_id}/terms")
def regenerate_terms(quote_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.regenerate_terms(db, quote_id, request_source(request), user.username)
    db.commit()
    return quote_detail(db, quote_id)


@router.post("/{quote_id}/recalculate")
def recalculate(quote_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.recalculate(db, quote_id, request_source(request), user.username)
    db.commit()
    return quote_detail(db, quote_id)


@router.patch("/items/{quote_item_id}")
def update_item(quote_item_id: uuid.UUID, body: QuoteItemPatch, request: Request, user: CurrentUser, db: Db):
    row = service.update_item(db, quote_item_id, body.model_dump(exclude_unset=True), request_source(request),
                              user.username)
    db.commit()
    return quote_detail(db, row.quote_id)


@router.delete("/items/{quote_item_id}", status_code=204)
def remove_item(quote_item_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.remove_item(db, quote_item_id, request_source(request), user.username)
    db.commit()


@router.post("/{quote_id}/approve")
def approve(quote_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.approve(db, quote_id, request_source(request), user.username)
    db.commit()
    return quote_detail(db, quote_id)


@router.post("/{quote_id}/mark-sent")
def mark_sent(quote_id: uuid.UUID, body: MarkSentIn, request: Request, user: CurrentUser, db: Db):
    data = body.model_dump()
    if data.get("followup") is None:
        data.pop("followup")
    service.mark_sent(db, quote_id, data, request_source(request), user.username)
    db.commit()
    return quote_detail(db, quote_id)


@router.post("/{quote_id}/withdraw")
def withdraw(quote_id: uuid.UUID, body: ReasonIn, request: Request, user: CurrentUser, db: Db):
    service.withdraw(db, quote_id, body.reason, request_source(request), user.username)
    db.commit()
    return quote_detail(db, quote_id)


@router.post("/{quote_id}/revise", status_code=201)
def revise(quote_id: uuid.UUID, body: ReviseIn, request: Request, user: CurrentUser, db: Db):
    row = service.revise(db, quote_id, body.model_dump(), user.calendar, request_source(request), user.username)
    db.commit()
    return quote_detail(db, row.id)


@router.put("/{quote_id}/outcomes")
def set_outcomes(quote_id: uuid.UUID, body: OutcomesIn, request: Request, user: CurrentUser, db: Db):
    service.set_outcomes(db, quote_id, [r.model_dump() for r in body.items], request_source(request), user.username)
    db.commit()
    return quote_detail(db, quote_id)


@router.get("/{quote_id}/print", response_class=HTMLResponse)
def print_view(quote_id: uuid.UUID, user: CurrentUser, db: Db):
    """The print HTML (also the fallback when no browser can make the PDF: use the browser's Print to PDF)."""
    quote = service.get_quote(db, quote_id)
    return HTMLResponse(output.render_html(output.build_context(db, quote, user.calendar, user.digits)))


@router.post("/{quote_id}/outputs", status_code=201)
def generate_output(quote_id: uuid.UUID, body: OutputIn, request: Request, user: CurrentUser, db: Db):
    result = output.generate(db, quote_id, body.format, user.calendar, user.digits, request_source(request),
                             user.username)
    db.commit()
    return result


case_router = APIRouter(prefix="/api/cases", tags=["quotes"])


@case_router.get("/{case_id}/quotes")
def case_quotes(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return {"summary": service.case_summary(db, case_id),
            "items": [quote_row(db, q) for q in service.list_quotes(db, case_id=case_id)]}


@case_router.post("/{case_id}/quote-result")
def case_result(case_id: uuid.UUID, body: CaseResultIn, request: Request, user: CurrentUser, db: Db):
    service.set_case_result(db, case_id, body.result, request_source(request), user.username)
    db.commit()
    return service.case_summary(db, case_id)


ROUTERS = [router, case_router]
