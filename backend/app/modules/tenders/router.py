"""Tenders API (v0.6.0): the tender part of a case, dates, addenda, envelopes, company documents, envelope templates,
guarantees, costs, the financial proposal, submission and result."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.core.db import get_db

from app.core.web import request_source
from app.modules.parties import service as parties
from app.modules.sourcing.common import jsonable, row_snapshot
from app.modules.tenders import (addenda, costs, dates, envelopes, guarantees, library, proposal, reminders, results,
                                 service)
from app.modules.tenders.common import DATE_LABELS, get_tender, tender_of_case
from app.modules.tenders.models import Tender, TenderResultReason
from app.modules.tenders.schemas import (AddendumIn, AddendumPatch, CompanyDocIn, CompanyDocPatch, CostIn, CostPatch, DateIn,
                                         DatePatch, FromTemplateIn, GuaranteeIn, GuaranteePatch, GuaranteeStatusIn, ItemIn,
                                         ItemPatch, OutputIn, ProposalApproveIn, ProposalCreate, ProposalLinePatch,
                                         ProposalPatch, ReasonsIn, RefreshApplyIn, ReorderIn, ResultIn, SetadDateApplyIn,
                                         SubmitIn, TemplateIn, TenderPatch)
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api/tenders", tags=["tenders"])
case_router = APIRouter(prefix="/api/cases", tags=["tenders"])
misc_router = APIRouter(prefix="/api", tags=["tenders"])


def _party(db: Session, party_id) -> dict | None:
    if party_id is None:
        return None
    p = parties.get_party(db, party_id)
    return {"id": p.id, "name_fa": p.name_fa, "name_en": p.name_en}


def guarantee_out(db: Session, g, tender: Tender | None = None) -> dict:
    return jsonable({**row_snapshot(g), "history": [row_snapshot(e) for e in guarantees.history(db, g.id)],
                     "beneficiary": _party(db, g.beneficiary_party_id), "reminder_party": _party(db, g.reminder_party_id),
                     "coverage": guarantees.coverage_problem(db, tender, g) if tender is not None else None,
                     "reminders": [{"id": f.id, "due_on": f.due_on, "action": f.action, "purpose": link.purpose}
                                   for link, f in reminders.links(db, ref_id=g.id)]})


def tender_detail(db: Session, tender_id: uuid.UUID) -> dict:
    tender = get_tender(db, tender_id)
    items = envelopes.items_of(db, tender.id)
    date_rows = dates.dates_of(db, tender.id)
    reminder_links = reminders.links(db, tender_id=tender.id)
    by_date: dict = {}
    for link, f in reminder_links:
        if link.purpose == "date_reminder":
            by_date.setdefault(link.ref_id, []).append({"id": f.id, "due_on": f.due_on, "days_before": link.days_before})
    nxt = dates.next_date(db, tender.id)
    bid = results.bid_bond(db, tender)
    cost_rows = costs.costs_of(db, tender.id)
    return jsonable({
        **row_snapshot(tender), "organizer": _party(db, tender.organizer_party_id), "stage_hint": service.stage_hint(db, tender),
        "dates": [{**row_snapshot(d), "reminders": by_date.get(d.id, [])} for d in date_rows],
        "date_changes": [row_snapshot(c) for c in dates.changes_of(db, tender.id)],
        "next_date": None if nxt is None else {"id": nxt.id, "kind": nxt.kind, "label": nxt.label, "at": nxt.at},
        "setad_date_changes": service.setad_date_changes(db, tender), "new_appendices": service.new_appendices(db, tender),
        "addenda": [row_snapshot(a) for a in addenda.addenda_of(db, tender.id)],
        "envelope_items": [envelopes.item_out(db, i) for i in items], "envelope_progress": envelopes.progress(items),
        "guarantees": [guarantee_out(db, g, tender) for g in guarantees.guarantees_of(db, case_id=tender.case_id)],
        "bid_bond": None if bid is None else {"id": bid.id, "status": bid.status, "valid_until": bid.valid_until},
        "needed_until": guarantees.needed_until(db, tender), "tied_up": guarantees.tied_up(db, tender.case_id),
        "costs": [row_snapshot(c) for c in cost_rows], "cost_totals": costs.totals(cost_rows),
        "proposals": [proposal.proposal_out(db, p) for p in proposal.proposals_of(db, tender.id)],
        "blockers": results.blockers(db, tender),
        "other_reminders": [{"id": f.id, "due_on": f.due_on, "action": f.action, "purpose": link.purpose}
                            for link, f in reminder_links if link.purpose in ("opening", "contract")],
    })


# ---- the tender of a case --------------------------------------------------------------------------------------------

@case_router.get("/{case_id}/tender")
def case_tender(case_id: uuid.UUID, _: CurrentUser, db: Db):
    tender = tender_of_case(db, case_id)
    return None if tender is None else tender_detail(db, tender.id)


@case_router.post("/{case_id}/tender", status_code=201)
def make_tender(case_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    """"Make this a tender" on any case."""
    tender = service.create_for_case(db, case_id, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender.id)


@case_router.get("/{case_id}/guarantees/tied-up")
def tied_up(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return guarantees.tied_up(db, case_id)


@router.get("/by-listing/{listing_id}")
def by_listing(listing_id: uuid.UUID, _: CurrentUser, db: Db):
    """The tender stage of a converted Setad listing (screening panel), or null."""
    from sqlalchemy import select

    tender = db.scalar(select(Tender).where(Tender.listing_id == listing_id))
    return None if tender is None else {"id": tender.id, "case_id": tender.case_id, "stage": tender.stage,
                                        "result": tender.result}


@router.get("/date-kinds")
def date_kinds(_: CurrentUser):
    return [{"kind": k, "label_fa": fa, "label_en": en} for k, (fa, en) in DATE_LABELS.items()] + \
        [{"kind": "other", "label_fa": "سایر", "label_en": "Other"}]


@router.get("/{tender_id}")
def get_one(tender_id: uuid.UUID, _: CurrentUser, db: Db):
    return tender_detail(db, tender_id)


@router.patch("/{tender_id}")
def patch_tender(tender_id: uuid.UUID, body: TenderPatch, request: Request, user: CurrentUser, db: Db):
    service.update_tender(db, tender_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


# ---- Setad --------------------------------------------------------------------------------------------------------

@router.get("/{tender_id}/setad-refresh")
def refresh_preview(tender_id: uuid.UUID, _: CurrentUser, db: Db):
    return {"changes": service.refresh_preview(db, tender_id)}


@router.post("/{tender_id}/setad-refresh")
def refresh_apply(tender_id: uuid.UUID, body: RefreshApplyIn, request: Request, user: CurrentUser, db: Db):
    service.refresh_apply(db, tender_id, body.fields, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@router.post("/{tender_id}/setad-dates/apply")
def apply_setad_dates(tender_id: uuid.UUID, body: SetadDateApplyIn, request: Request, user: CurrentUser, db: Db):
    if body.kind:
        service.apply_setad_date(db, tender_id, body.kind, request_source(request), user.username)
    else:
        service.apply_all_setad_dates(db, tender_id, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@router.post("/{tender_id}/appendices/seen")
def appendices_seen(tender_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.acknowledge_appendices(db, get_tender(db, tender_id), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


# ---- dates and addenda ----------------------------------------------------------------------------------------------

@router.post("/{tender_id}/dates", status_code=201)
def add_date(tender_id: uuid.UUID, body: DateIn, request: Request, user: CurrentUser, db: Db):
    dates.add_date(db, tender_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@misc_router.patch("/tender-dates/{date_id}")
def patch_date(date_id: uuid.UUID, body: DatePatch, request: Request, user: CurrentUser, db: Db):
    row = dates.update_date(db, date_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return tender_detail(db, row.tender_id)


@misc_router.delete("/tender-dates/{date_id}")
def delete_date(date_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    tender_id = dates.get_date(db, date_id).tender_id
    dates.delete_date(db, date_id, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@router.post("/{tender_id}/addenda", status_code=201)
def add_addendum(tender_id: uuid.UUID, body: AddendumIn, request: Request, user: CurrentUser, db: Db):
    addenda.add_addendum(db, tender_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@misc_router.patch("/tender-addenda/{addendum_id}")
def patch_addendum(addendum_id: uuid.UUID, body: AddendumPatch, request: Request, user: CurrentUser, db: Db):
    row = addenda.update_addendum(db, addendum_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return tender_detail(db, row.tender_id)


@misc_router.delete("/tender-addenda/{addendum_id}")
def delete_addendum(addendum_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    tender_id = addenda.get_addendum(db, addendum_id).tender_id
    addenda.delete_addendum(db, addendum_id, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


# ---- envelopes ---------------------------------------------------------------------------------------------------

@router.post("/{tender_id}/envelope-items", status_code=201)
def add_item(tender_id: uuid.UUID, body: ItemIn, request: Request, user: CurrentUser, db: Db):
    envelopes.add_item(db, tender_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@router.post("/{tender_id}/envelope-items/from-template")
def items_from_template(tender_id: uuid.UUID, body: FromTemplateIn, request: Request, user: CurrentUser, db: Db):
    envelopes.copy_template(db, tender_id, body.template_id, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@router.post("/{tender_id}/envelope-items/reorder")
def reorder_items(tender_id: uuid.UUID, body: ReorderIn, request: Request, user: CurrentUser, db: Db):
    envelopes.reorder(db, tender_id, body.envelope, body.item_ids, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@misc_router.patch("/envelope-items/{item_id}")
def patch_item(item_id: uuid.UUID, body: ItemPatch, request: Request, user: CurrentUser, db: Db):
    row = envelopes.update_item(db, item_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return tender_detail(db, row.tender_id)


@misc_router.delete("/envelope-items/{item_id}")
def delete_item(item_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    tender_id = envelopes.get_item(db, item_id).tender_id
    envelopes.remove_item(db, item_id, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


# ---- company documents and envelope templates -------------------------------------------------------------------------

@misc_router.get("/company-documents")
def list_company_documents(_: CurrentUser, db: Db, expiry: str | None = None, include_archived: bool = False):
    return library.list_documents(db, expiry=expiry, include_archived=include_archived)


@misc_router.get("/company-documents/suggestions")
def company_document_suggestions(_: CurrentUser):
    return [{"title": t, "category": c} for t, c in library.SUGGESTIONS]


@misc_router.post("/company-documents", status_code=201)
def create_company_document(body: CompanyDocIn, request: Request, user: CurrentUser, db: Db):
    row = library.create_document(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return library.document_out(row)


@misc_router.patch("/company-documents/{doc_id}")
def patch_company_document(doc_id: uuid.UUID, body: CompanyDocPatch, request: Request, user: CurrentUser, db: Db):
    row = library.update_document(db, doc_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return library.document_out(row)


@misc_router.delete("/company-documents/{doc_id}", status_code=204)
def delete_company_document(doc_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    library.delete_document(db, doc_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


@misc_router.get("/envelope-templates")
def list_templates(_: CurrentUser, db: Db):
    return library.list_templates(db)


@misc_router.post("/envelope-templates", status_code=201)
def create_template(body: TemplateIn, request: Request, user: CurrentUser, db: Db):
    row = library.save_template(db, None, body.model_dump(), request_source(request), user.username)
    db.commit()
    return library.template_out(db, row)


@misc_router.put("/envelope-templates/{template_id}")
def save_template(template_id: uuid.UUID, body: TemplateIn, request: Request, user: CurrentUser, db: Db):
    row = library.save_template(db, template_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return library.template_out(db, row)


@misc_router.delete("/envelope-templates/{template_id}", status_code=204)
def delete_template(template_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    library.delete_template(db, template_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


# ---- guarantees -----------------------------------------------------------------------------------------------------

@misc_router.get("/guarantees")
def list_guarantees(_: CurrentUser, db: Db, status: str | None = None, purpose: str | None = None,
                    expiring_within: int | None = None):
    return guarantees.list_all(db, status=status, purpose=purpose, expiring_within=expiring_within)


@misc_router.post("/guarantees", status_code=201)
def create_guarantee(body: GuaranteeIn, request: Request, user: CurrentUser, db: Db):
    row = guarantees.create_guarantee(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return guarantee_out(db, row, db.get(Tender, row.tender_id) if row.tender_id else None)


@misc_router.get("/guarantees/{guarantee_id}")
def get_guarantee(guarantee_id: uuid.UUID, _: CurrentUser, db: Db):
    row = guarantees.get_guarantee(db, guarantee_id)
    return guarantee_out(db, row, db.get(Tender, row.tender_id) if row.tender_id else None)


@misc_router.patch("/guarantees/{guarantee_id}")
def patch_guarantee(guarantee_id: uuid.UUID, body: GuaranteePatch, request: Request, user: CurrentUser, db: Db):
    row = guarantees.update_guarantee(db, guarantee_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return guarantee_out(db, row, db.get(Tender, row.tender_id) if row.tender_id else None)


@misc_router.post("/guarantees/{guarantee_id}/status")
def guarantee_status(guarantee_id: uuid.UUID, body: GuaranteeStatusIn, request: Request, user: CurrentUser, db: Db):
    row = guarantees.set_status(db, guarantee_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return guarantee_out(db, row, db.get(Tender, row.tender_id) if row.tender_id else None)


@misc_router.delete("/guarantees/{guarantee_id}", status_code=204)
def delete_guarantee(guarantee_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    guarantees.delete_guarantee(db, guarantee_id, request_source(request), user.username)
    db.commit()
    return Response(status_code=204)


# ---- costs --------------------------------------------------------------------------------------------------------

@router.post("/{tender_id}/costs", status_code=201)
def add_cost(tender_id: uuid.UUID, body: CostIn, request: Request, user: CurrentUser, db: Db):
    costs.add_cost(db, tender_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@router.post("/{tender_id}/costs/to-sheet")
def costs_to_sheet(tender_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    result = costs.add_to_cost_sheet(db, tender_id, request_source(request), user.username)
    db.commit()
    return result


@misc_router.patch("/tender-costs/{cost_id}")
def patch_cost(cost_id: uuid.UUID, body: CostPatch, request: Request, user: CurrentUser, db: Db):
    row = costs.update_cost(db, cost_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return tender_detail(db, row.tender_id)


@misc_router.delete("/tender-costs/{cost_id}")
def delete_cost(cost_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    tender_id = costs.get_cost(db, cost_id).tender_id
    costs.delete_cost(db, cost_id, request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


# ---- financial proposal -----------------------------------------------------------------------------------------------

@router.post("/{tender_id}/proposals", status_code=201)
def create_proposal(tender_id: uuid.UUID, body: ProposalCreate, request: Request, user: CurrentUser, db: Db):
    row = proposal.create_proposal(db, tender_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return proposal.proposal_out(db, row)


@misc_router.get("/tender-proposals/{proposal_id}")
def get_proposal(proposal_id: uuid.UUID, _: CurrentUser, db: Db):
    return proposal.proposal_out(db, proposal.get_proposal(db, proposal_id))


@misc_router.patch("/tender-proposals/{proposal_id}")
def patch_proposal(proposal_id: uuid.UUID, body: ProposalPatch, request: Request, user: CurrentUser, db: Db):
    row = proposal.update_proposal(db, proposal_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return proposal.proposal_out(db, row)


@misc_router.patch("/tender-proposal-lines/{line_id}")
def patch_proposal_line(line_id: uuid.UUID, body: ProposalLinePatch, request: Request, user: CurrentUser, db: Db):
    line = proposal.update_line(db, line_id, body.unit_price, request_source(request), user.username)
    db.commit()
    return proposal.proposal_out(db, proposal.get_proposal(db, line.proposal_id))


@misc_router.post("/tender-proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: uuid.UUID, request: Request, user: CurrentUser, db: Db,
                     body: ProposalApproveIn | None = None):
    row = proposal.approve(db, proposal_id, request_source(request), user.username,
                           confirm_below_cost=bool(body and body.confirm_below_cost), reason=body.reason if body else None)
    db.commit()
    return proposal.proposal_out(db, row)


@misc_router.get("/tender-proposals/{proposal_id}/print", response_class=HTMLResponse)
def print_proposal(proposal_id: uuid.UUID, user: CurrentUser, db: Db):
    row = proposal.get_proposal(db, proposal_id)
    return HTMLResponse(proposal.render_html(proposal.build_context(db, row, user.calendar, user.digits)))


@misc_router.post("/tender-proposals/{proposal_id}/outputs", status_code=201)
def proposal_output(proposal_id: uuid.UUID, body: OutputIn, request: Request, user: CurrentUser, db: Db):
    result = proposal.generate(db, proposal_id, body.format, user.calendar, user.digits, request_source(request), user.username)
    db.commit()
    return result


# ---- submission and result ------------------------------------------------------------------------------------------

@router.get("/{tender_id}/blockers")
def blockers(tender_id: uuid.UUID, _: CurrentUser, db: Db):
    return {"blockers": results.blockers(db, get_tender(db, tender_id))}


@router.post("/{tender_id}/submit")
def submit(tender_id: uuid.UUID, body: SubmitIn, request: Request, user: CurrentUser, db: Db):
    results.mark_submitted(db, tender_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@router.post("/{tender_id}/result")
def set_result(tender_id: uuid.UUID, body: ResultIn, request: Request, user: CurrentUser, db: Db):
    results.set_result(db, tender_id, body.model_dump(), request_source(request), user.username)
    db.commit()
    return tender_detail(db, tender_id)


@misc_router.get("/tender-result-reasons")
def result_reasons(_: CurrentUser, db: Db, include_inactive: bool = False):
    return [jsonable(row_snapshot(r)) for r in results.result_reasons(db, include_inactive)]


@misc_router.put("/tender-result-reasons")
def save_result_reasons(body: ReasonsIn, request: Request, user: CurrentUser, db: Db):
    """Settings: edit the result reasons (labels, active; new codes are added, none is deleted)."""
    from app.modules.events import service as events

    for i, r in enumerate(body.reasons, start=1):
        row = db.get(TenderResultReason, r.code)
        if row is None:
            row = TenderResultReason(code=r.code, label_fa=r.label_fa, label_en=r.label_en, sort_order=i * 10, active=r.active)
            db.add(row)
        else:
            row.label_fa, row.label_en, row.active, row.sort_order = r.label_fa, r.label_en, r.active, i * 10
    db.flush()
    events.record(db, "tender_result_reason", "all", "update", {"codes": [r.code for r in body.reasons]},
                  request_source(request), actor=user.username)
    db.commit()
    return [jsonable(row_snapshot(r)) for r in results.result_reasons(db, True)]



ROUTERS = [router, case_router, misc_router]
