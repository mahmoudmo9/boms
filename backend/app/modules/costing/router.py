"""Costing API: tax parameters, cost templates, cost sheets (lines, FX, computation, gate)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from app.modules.costing import service
from app.modules.costing.schemas import (
    FxIn,
    LineIn,
    LinePatch,
    OverrideIn,
    SheetCreate,
    SheetPatch,
    TaxParameterIn,
    TaxParameterPatch,
    TemplateIn,
    TemplatePatch,
)
from app.modules.sourcing.common import jsonable, row_snapshot
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]


def _json_shares(data: dict) -> dict:
    if data.get("manual_shares") is not None:
        data["manual_shares"] = {str(k): str(v) for k, v in data["manual_shares"].items()}
    return data


# ---- tax parameters ----------------------------------------------------------------------------------------

tax_router = APIRouter(prefix="/api/tax-parameters", tags=["costing"])


@tax_router.get("/kinds")
def tax_kinds(_: CurrentUser, db: Db):
    return [jsonable(row_snapshot(k)) for k in service.tax_kinds(db)]


@tax_router.get("")
def list_parameters(_: CurrentUser, db: Db, kind: str | None = None):
    return [jsonable(row_snapshot(p)) for p in service.list_parameters(db, kind)]


@tax_router.get("/in-force")
def parameter_in_force(_: CurrentUser, db: Db, kind: str, deal_type: str, on: date):
    row = service.parameter_in_force(db, kind, deal_type, on)
    return jsonable(row_snapshot(row)) if row else None


@tax_router.post("", status_code=201)
def create_parameter(body: TaxParameterIn, request: Request, user: CurrentUser, db: Db):
    row = service.create_parameter(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return jsonable(row_snapshot(row))


@tax_router.patch("/{parameter_id}")
def update_parameter(parameter_id: uuid.UUID, body: TaxParameterPatch, request: Request, user: CurrentUser, db: Db):
    row = service.update_parameter(db, parameter_id, body.model_dump(exclude_unset=True), request_source(request),
                                   user.username)
    db.commit()
    return jsonable(row_snapshot(row))


@tax_router.delete("/{parameter_id}", status_code=204)
def delete_parameter(parameter_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_parameter(db, parameter_id, request_source(request), user.username)
    db.commit()


# ---- templates -----------------------------------------------------------------------------------------------

templates_router = APIRouter(prefix="/api/cost-templates", tags=["costing"])


def template_out(db: Session, template) -> dict:
    return jsonable({**row_snapshot(template),
                     "lines": [row_snapshot(r) for r in service.template_lines(db, template.id)]})


@templates_router.get("")
def list_templates(_: CurrentUser, db: Db, include_archived: bool = False):
    return [template_out(db, t) for t in service.list_templates(db, include_archived)]


@templates_router.get("/{template_id}")
def get_template(template_id: uuid.UUID, _: CurrentUser, db: Db):
    return template_out(db, service.get_template(db, template_id))


@templates_router.post("", status_code=201)
def create_template(body: TemplateIn, request: Request, user: CurrentUser, db: Db):
    row = service.create_template(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return template_out(db, row)


@templates_router.patch("/{template_id}")
def update_template(template_id: uuid.UUID, body: TemplatePatch, request: Request, user: CurrentUser, db: Db):
    row = service.update_template(db, template_id, body.model_dump(exclude_unset=True), request_source(request),
                                  user.username)
    db.commit()
    return template_out(db, row)


@templates_router.delete("/{template_id}", status_code=204)
def delete_template(template_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_template(db, template_id, request_source(request), user.username)
    db.commit()


# ---- cost sheets -------------------------------------------------------------------------------------------

sheets_router = APIRouter(prefix="/api/cost-sheets", tags=["costing"])


def sheet_detail(db: Session, sheet_id: uuid.UUID, valid_until: date | None = None) -> dict:
    from app.core.errors import AppError

    sheet = service.get_sheet(db, sheet_id)
    computation, error = None, None
    try:
        computation = service.compute_sheet(db, sheet)
    except AppError as exc:
        error = {"code": exc.code, "message": exc.message, "details": exc.details}
    items = service.sheet_items(db, sheet)
    return jsonable({
        **row_snapshot(sheet),
        "decimals": service.currency_decimals(db, sheet.pricing_currency),
        "lines": [row_snapshot(r) for r in service.lines_of(db, sheet.id)],
        "fx": [row_snapshot(r) for r in service.fx_of(db, sheet.id)],
        "items": [{"id": i.id, "name": i.name, "quantity": i.quantity, "unit_code": i.unit_code,
                   "unit_text": i.unit_text, "status": i.status, "selected_offer_item_id": i.selected_offer_item_id}
                  for i in items],
        "computation": computation,
        "compute_error": error,
        "warnings": service.warnings(db, sheet, computation),
        "gate": service.gate(db, sheet, valid_until),
    })


@sheets_router.get("/rate-kinds")
def rate_kinds(_: CurrentUser, db: Db):
    return service.rate_kind_suggestions(db)


@sheets_router.post("", status_code=201)
def create_sheet(body: SheetCreate, request: Request, user: CurrentUser, db: Db):
    row = service.create_sheet(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return sheet_detail(db, row.id)


@sheets_router.get("/{sheet_id}")
def get_sheet(sheet_id: uuid.UUID, _: CurrentUser, db: Db, valid_until: date | None = None):
    return sheet_detail(db, sheet_id, valid_until)


@sheets_router.get("/{sheet_id}/computation")
def computation(sheet_id: uuid.UUID, _: CurrentUser, db: Db):
    """The computation alone; 422 fx_missing (with the pair) when a rate is missing."""
    return jsonable(service.compute_sheet(db, service.get_sheet(db, sheet_id)))


@sheets_router.get("/{sheet_id}/gate")
def sheet_gate(sheet_id: uuid.UUID, _: CurrentUser, db: Db, valid_until: Annotated[date | None, Query()] = None):
    return service.gate(db, service.get_sheet(db, sheet_id), valid_until)


@sheets_router.patch("/{sheet_id}")
def update_sheet(sheet_id: uuid.UUID, body: SheetPatch, request: Request, user: CurrentUser, db: Db):
    service.update_sheet(db, sheet_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return sheet_detail(db, sheet_id)


@sheets_router.delete("/{sheet_id}", status_code=204)
def delete_sheet(sheet_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_sheet(db, sheet_id, request_source(request), user.username)
    db.commit()


@sheets_router.post("/{sheet_id}/new-version", status_code=201)
def new_version(sheet_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    row = service.new_version(db, sheet_id, request_source(request), user.username)
    db.commit()
    return sheet_detail(db, row.id)


@sheets_router.post("/{sheet_id}/finalize")
def finalize(sheet_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.finalize(db, sheet_id, request_source(request), user.username)
    db.commit()
    return sheet_detail(db, sheet_id)


@sheets_router.post("/{sheet_id}/override")
def override(sheet_id: uuid.UUID, body: OverrideIn, request: Request, user: CurrentUser, db: Db):
    service.override(db, sheet_id, body.kind, body.reason, request_source(request), user.username)
    db.commit()
    return sheet_detail(db, sheet_id)


@sheets_router.post("/{sheet_id}/lines", status_code=201)
def add_line(sheet_id: uuid.UUID, body: LineIn, request: Request, user: CurrentUser, db: Db):
    row = service.add_line(db, sheet_id, _json_shares(body.model_dump()), request_source(request), user.username)
    db.commit()
    return jsonable(row_snapshot(row))


@sheets_router.patch("/lines/{line_id}")
def update_line(line_id: uuid.UUID, body: LinePatch, request: Request, user: CurrentUser, db: Db):
    row = service.update_line(db, line_id, _json_shares(body.model_dump(exclude_unset=True)), request_source(request),
                              user.username)
    db.commit()
    return jsonable(row_snapshot(row))


@sheets_router.delete("/lines/{line_id}", status_code=204)
def delete_line(line_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_line(db, line_id, request_source(request), user.username)
    db.commit()


@sheets_router.put("/{sheet_id}/fx")
def set_fx(sheet_id: uuid.UUID, body: FxIn, request: Request, user: CurrentUser, db: Db):
    row = service.set_fx(db, sheet_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return jsonable(row_snapshot(row))


@sheets_router.delete("/fx/{fx_id}", status_code=204)
def delete_fx(fx_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_fx(db, fx_id, request_source(request), user.username)
    db.commit()


# ---- per case ---------------------------------------------------------------------------------------------

case_router = APIRouter(prefix="/api/cases", tags=["costing"])


@case_router.get("/{case_id}/costing")
def case_costing(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return service.case_summary(db, case_id)


ROUTERS = [tax_router, templates_router, sheets_router, case_router]
