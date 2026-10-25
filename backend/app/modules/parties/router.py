import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.schemas import Page, page_params
from app.core.web import request_source
from app.modules.parties import command_center, interactions, normalize, service
from app.modules.parties.schemas import (
    ArchiveIn,
    Channel,
    ContactCreate,
    ContactOut,
    ContactPatch,
    DeletePartyIn,
    DocumentLinkIn,
    DuplicateOut,
    FollowupCancel,
    FollowupCreate,
    FollowupDone,
    FollowupOut,
    FollowupReschedule,
    InteractionCreate,
    InteractionOut,
    InteractionPatch,
    MethodAdd,
    MethodOut,
    MethodPatch,
    PartyCreate,
    PartyOut,
    PartyPatch,
    Role,
    RoleIn,
    RoleOut,
    StageChange,
)
from app.modules.system.auth import CurrentUser
from app.modules.system.models import Country

Db = Annotated[Session, Depends(get_db)]
parties_router = APIRouter(prefix="/api/parties", tags=["parties"])
contacts_router = APIRouter(prefix="/api/contacts", tags=["parties"])
interactions_router = APIRouter(prefix="/api/interactions", tags=["parties"])
followups_router = APIRouter(prefix="/api/followups", tags=["parties"])
command_router = APIRouter(prefix="/api/command-center", tags=["parties"])


def _party_card(db: Session, parties: list) -> list[dict]:
    ids = [p.id for p in parties]
    roles = service.roles_for(db, ids)
    activity = service.activity_for(db, ids)
    return [{**PartyOut.model_validate(p).model_dump(),
             "roles": [RoleOut.model_validate(r).model_dump() for r in roles[p.id]], **activity[p.id]}
            for p in parties]


def _method_out(method) -> MethodOut:
    return MethodOut.model_validate(method).model_copy(
        update={"value_display": normalize.display_value(method.type, method.value, method.value_norm)})


def _contact_out(db: Session, contacts: list) -> list[dict]:
    methods = service.methods_of(db, [c.id for c in contacts])
    return [ContactOut.model_validate(c).model_copy(
        update={"methods": [_method_out(m) for m in methods[c.id]]}).model_dump() for c in contacts]


def party_detail(db: Session, party_id: uuid.UUID) -> dict:
    party = service.get_party(db, party_id)
    recent, _ = interactions.list_interactions(db, party_id=party_id, page_size=20)
    open_followups, _ = interactions.list_followups(db, status="open", party_id=party_id)
    return {
        **_party_card(db, [party])[0],
        "contacts": _contact_out(db, service.contacts_of(db, party_id)),
        "recent_interactions": [InteractionOut.model_validate(i).model_dump() for i in recent],
        "open_followups": [FollowupOut.model_validate(f).model_dump() for f in open_followups],
        "documents": service.party_documents(db, party_id),
    }


# ---- parties ------------------------------------------------------------------------

@parties_router.get("")
def list_parties(_: CurrentUser, db: Db, q: str | None = None, role: Role | None = None, stage: str | None = None,
                 country: str | None = None, status: Literal["active", "archived", "all"] = "active",
                 sort: Literal["name", "updated_at", "created_at"] = "updated_at",
                 order: Literal["asc", "desc"] = "desc", page: int = 1,
                 page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    rows, total = service.list_parties(db, q=q, role=role, stage=stage, country=country,
                                       status=None if status == "all" else status, sort=sort, order=order,
                                       page=page, page_size=page_size)
    return {"items": _party_card(db, rows), "total": total, "page": page, "page_size": page_size}


@parties_router.get("/stages")
def list_stages(_: CurrentUser, db: Db, role: Role | None = None):
    return [{"role": s.role, "code": s.code, "sort_order": s.sort_order, "label_fa": s.label_fa,
             "label_en": s.label_en, "is_terminal": s.is_terminal} for s in service.stages(db, role)]


@parties_router.get("/duplicates")
def duplicates(_: CurrentUser, db: Db, name_fa: str | None = None, name_en: str | None = None,
               exclude: uuid.UUID | None = None):
    return {"possible_duplicates": [DuplicateOut.model_validate(d).model_dump()
                                    for d in service.find_duplicates(db, name_fa, name_en, exclude)]}


@parties_router.get("/phone-regions")
def phone_regions(_: CurrentUser, db: Db):
    countries = db.execute(select(Country.iso2, Country.name_fa, Country.name_en).order_by(Country.sort_order, Country.name_en)).all()
    return normalize.phone_regions([tuple(c) for c in countries])


@parties_router.get("/funnel/{role}")
def funnel(role: Role, _: CurrentUser, db: Db):
    return command_center.funnel_board(db, role)


@parties_router.post("")
def create_party(body: PartyCreate, request: Request, response: Response, user: CurrentUser, db: Db):
    party, dups = service.create_party(db, body.model_dump(), request_source(request), actor=user.username)
    dup_out = [DuplicateOut.model_validate(d).model_dump() for d in dups]
    if party is None:
        response.status_code = 200
        return {"created": False, "possible_duplicates": dup_out}
    db.commit()
    response.status_code = 201
    return {"created": True, "possible_duplicates": dup_out, "party": party_detail(db, party.id)}


@parties_router.get("/{party_id}")
def get_party(party_id: uuid.UUID, _: CurrentUser, db: Db):
    return party_detail(db, party_id)


@parties_router.patch("/{party_id}")
def update_party(party_id: uuid.UUID, body: PartyPatch, request: Request, user: CurrentUser, db: Db):
    service.update_party(db, party_id, body.model_dump(exclude_unset=True), request_source(request), user.username)
    db.commit()
    return party_detail(db, party_id)


@parties_router.delete("/{party_id}")
def delete_party(party_id: uuid.UUID, request: Request, user: CurrentUser, db: Db, cascade: bool = False,
                 body: Annotated[DeletePartyIn | None, Body()] = None):
    counts = service.delete_party(db, party_id, request_source(request), user.username, cascade=cascade,
                                  confirm_name=body.confirm_name if body else None)
    db.commit()
    return {"deleted": True, "cascade": cascade, "counts": counts}


@parties_router.post("/{party_id}/archive")
def archive_party(party_id: uuid.UUID, request: Request, user: CurrentUser, db: Db,
                  body: Annotated[ArchiveIn | None, Body()] = None):
    service.set_status(db, party_id, "archived", request_source(request), user.username,
                       open_followups=body.open_followups if body else "cancel")
    db.commit()
    return party_detail(db, party_id)


@parties_router.post("/{party_id}/unarchive")
def unarchive_party(party_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.set_status(db, party_id, "active", request_source(request), user.username)
    db.commit()
    return party_detail(db, party_id)


@parties_router.post("/{party_id}/roles", status_code=201)
def add_role(party_id: uuid.UUID, body: RoleIn, request: Request, user: CurrentUser, db: Db):
    row = service.add_role(db, party_id, body.role, body.stage, request_source(request), user.username)
    db.commit()
    return RoleOut.model_validate(row)


@parties_router.delete("/{party_id}/roles/{role}", status_code=204)
def remove_role(party_id: uuid.UUID, role: Role, request: Request, user: CurrentUser, db: Db):
    service.remove_role(db, party_id, role, request_source(request), user.username)
    db.commit()


@parties_router.post("/{party_id}/roles/{role}/stage")
def change_stage(party_id: uuid.UUID, role: Role, body: StageChange, request: Request, user: CurrentUser, db: Db):
    row = service.change_stage(db, party_id, role, body.stage, body.reason, request_source(request), user.username)
    db.commit()
    return RoleOut.model_validate(row)


@parties_router.get("/{party_id}/documents")
def party_documents(party_id: uuid.UUID, _: CurrentUser, db: Db):
    service.get_party(db, party_id)
    return service.party_documents(db, party_id)


@parties_router.post("/{party_id}/documents", status_code=201)
def link_party_document(party_id: uuid.UUID, body: DocumentLinkIn, request: Request, user: CurrentUser, db: Db):
    service.get_party(db, party_id)
    link = service.link_document(db, "party", party_id, body.document_id, request_source(request), user.username)
    db.commit()
    return {"link_id": link.id}


@parties_router.delete("/{party_id}/documents/{link_id}", status_code=204)
def unlink_party_document(party_id: uuid.UUID, link_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.unlink_document(db, "party", party_id, link_id, request_source(request), user.username)
    db.commit()


# ---- contacts -----------------------------------------------------------------------

def _one_contact(db: Session, contact_id: uuid.UUID) -> dict:
    return _contact_out(db, [service.get_contact(db, contact_id)])[0]


@contacts_router.get("")
def list_contacts(party_id: uuid.UUID, _: CurrentUser, db: Db):
    return _contact_out(db, service.contacts_of(db, party_id))


@contacts_router.post("", status_code=201)
def create_contact(body: ContactCreate, request: Request, response: Response, user: CurrentUser, db: Db):
    """201 with the contact, or 200 ``{created: false, shared_with}`` when a number belongs to another contact
    and ``confirm_shared`` is not set (nothing is stored)."""
    data = body.model_dump()
    confirm = data.pop("confirm_shared")
    contact, shared = service.create_contact(db, data, request_source(request), user.username, confirm_shared=confirm)
    if contact is None:
        response.status_code = 200
        return {"created": False, "shared_with": shared}
    db.commit()
    return {**_one_contact(db, contact.id), "created": True, "shared_with": shared}


@contacts_router.patch("/{contact_id}")
def update_contact(contact_id: uuid.UUID, body: ContactPatch, request: Request, user: CurrentUser, db: Db):
    service.update_contact(db, contact_id, body.model_dump(exclude_unset=True), request_source(request),
                           user.username)
    db.commit()
    return _one_contact(db, contact_id)


@contacts_router.delete("/{contact_id}", status_code=204)
def delete_contact(contact_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_contact(db, contact_id, request_source(request), user.username)
    db.commit()


@contacts_router.post("/{contact_id}/archive")
def archive_contact(contact_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.set_contact_status(db, contact_id, "archived", request_source(request), user.username)
    db.commit()
    return _one_contact(db, contact_id)


@contacts_router.post("/{contact_id}/unarchive")
def unarchive_contact(contact_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.set_contact_status(db, contact_id, "active", request_source(request), user.username)
    db.commit()
    return _one_contact(db, contact_id)


def _method_result(db: Session, method, shared: list[dict], response: Response, created_status: int) -> dict:
    if method is None:
        response.status_code = 200
        return {"created": False, "shared_with": shared}
    db.commit()
    response.status_code = created_status
    return {**_method_out(method).model_dump(), "created": True, "shared_with": shared}


@contacts_router.post("/{contact_id}/methods", status_code=201)
def add_method(contact_id: uuid.UUID, body: MethodAdd, request: Request, response: Response, user: CurrentUser,
               db: Db):
    data = body.model_dump()
    confirm = data.pop("confirm_shared")
    method, shared = service.add_method(db, contact_id, data, request_source(request), user.username,
                                        confirm_shared=confirm)
    return _method_result(db, method, shared, response, 201)


@contacts_router.patch("/methods/{method_id}")
def update_method(method_id: uuid.UUID, body: MethodPatch, request: Request, response: Response, user: CurrentUser,
                  db: Db):
    data = body.model_dump(exclude_unset=True)
    confirm = data.pop("confirm_shared", False)
    method, shared = service.update_method(db, method_id, data, request_source(request), user.username,
                                           confirm_shared=confirm)
    return _method_result(db, method, shared, response, 200)


@contacts_router.delete("/methods/{method_id}", status_code=204)
def delete_method(method_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    service.delete_method(db, method_id, request_source(request), user.username)
    db.commit()


@contacts_router.post("/methods/{method_id}/archive")
def archive_method(method_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    method = service.set_method_status(db, method_id, "archived", request_source(request), user.username)
    db.commit()
    return _method_out(method)


@contacts_router.post("/methods/{method_id}/unarchive")
def unarchive_method(method_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    method = service.set_method_status(db, method_id, "active", request_source(request), user.username)
    db.commit()
    return _method_out(method)


# ---- interactions -------------------------------------------------------------------

def _interaction_detail(db: Session, interaction_id: uuid.UUID) -> dict:
    row = interactions.get_interaction(db, interaction_id)
    followups, _ = interactions.list_followups(db, status=None, party_id=row.party_id)
    return {**InteractionOut.model_validate(row).model_dump(),
            "followups": [FollowupOut.model_validate(f).model_dump() for f in followups
                          if f.interaction_id == row.id],
            "documents": service.linked_documents(db, "interaction", [str(row.id)])}


@interactions_router.get("", response_model=Page[InteractionOut])
def list_interactions(_: CurrentUser, db: Db, party_id: uuid.UUID | None = None, channel: Channel | None = None,
                      date_from: Annotated[datetime | None, Query(alias="from")] = None,
                      date_to: Annotated[datetime | None, Query(alias="to")] = None, q: str | None = None,
                      page: int = 1, page_size: Annotated[int, Query(le=200)] = 50):
    page, page_size = page_params(page, page_size, 200)
    try:
        rows, total = interactions.list_interactions(db, party_id=party_id, channel=channel, date_from=date_from,
                                                     date_to=date_to, q=q, page=page, page_size=page_size)
    except ValueError as exc:
        raise AppError("invalid_date", str(exc), status=422) from exc
    return Page(items=[InteractionOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@interactions_router.post("", status_code=201)
def create_interaction(body: InteractionCreate, request: Request, user: CurrentUser, db: Db):
    row, _ = interactions.create_interaction(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return _interaction_detail(db, row.id)


@interactions_router.get("/{interaction_id}")
def get_interaction(interaction_id: uuid.UUID, _: CurrentUser, db: Db):
    return _interaction_detail(db, interaction_id)


@interactions_router.patch("/{interaction_id}")
def correct_interaction(interaction_id: uuid.UUID, body: InteractionPatch, request: Request, user: CurrentUser,
                        db: Db):
    interactions.correct_interaction(db, interaction_id, body.model_dump(exclude_unset=True),
                                     request_source(request), user.username)
    db.commit()
    return _interaction_detail(db, interaction_id)


@interactions_router.post("/{interaction_id}/documents", status_code=201)
def link_interaction_document(interaction_id: uuid.UUID, body: DocumentLinkIn, request: Request, user: CurrentUser,
                              db: Db):
    interactions.get_interaction(db, interaction_id)
    link = service.link_document(db, "interaction", interaction_id, body.document_id, request_source(request),
                                 user.username)
    db.commit()
    return {"link_id": link.id}


@interactions_router.delete("/{interaction_id}/documents/{link_id}", status_code=204)
def unlink_interaction_document(interaction_id: uuid.UUID, link_id: uuid.UUID, request: Request, user: CurrentUser,
                                db: Db):
    service.unlink_document(db, "interaction", interaction_id, link_id, request_source(request), user.username)
    db.commit()


# ---- follow-ups -----------------------------------------------------------------------

@followups_router.get("", response_model=Page[FollowupOut])
def list_followups(_: CurrentUser, db: Db, status: Literal["open", "done", "cancelled", "all"] = "open",
                   party_id: uuid.UUID | None = None, due_from: date | None = None, due_to: date | None = None,
                   page: int = 1, page_size: Annotated[int, Query(le=200)] = 100):
    page, page_size = page_params(page, page_size, 200)
    rows, total = interactions.list_followups(db, status=None if status == "all" else status, party_id=party_id,
                                              due_from=due_from, due_to=due_to, page=page, page_size=page_size)
    return Page(items=[FollowupOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@followups_router.post("", status_code=201, response_model=FollowupOut)
def create_followup(body: FollowupCreate, request: Request, user: CurrentUser, db: Db):
    row = interactions.create_followup(db, body.model_dump(), request_source(request), user.username)
    db.commit()
    return row


@followups_router.post("/{followup_id}/done")
def complete_followup(followup_id: uuid.UUID, body: FollowupDone, request: Request, user: CurrentUser, db: Db):
    row, created = interactions.complete_followup(db, followup_id, body.note,
                                                  body.next.model_dump() if body.next else None,
                                                  request_source(request), user.username)
    db.commit()
    return {"followup": FollowupOut.model_validate(row),
            "next": FollowupOut.model_validate(created) if created else None}


@followups_router.post("/{followup_id}/reschedule", response_model=FollowupOut)
def reschedule_followup(followup_id: uuid.UUID, body: FollowupReschedule, request: Request, user: CurrentUser,
                        db: Db):
    row = interactions.reschedule_followup(db, followup_id, body.due_on, body.note, request_source(request),
                                           user.username)
    db.commit()
    return row


@followups_router.post("/{followup_id}/cancel", response_model=FollowupOut)
def cancel_followup(followup_id: uuid.UUID, body: FollowupCancel, request: Request, user: CurrentUser, db: Db):
    row = interactions.cancel_followup(db, followup_id, body.note, request_source(request), user.username)
    db.commit()
    return row


# ---- command center -------------------------------------------------------------------

@command_router.get("")
def get_command_center(_: CurrentUser, db: Db):
    return command_center.summary(db)


ROUTERS = [parties_router, contacts_router, interactions_router, followups_router, command_router]
