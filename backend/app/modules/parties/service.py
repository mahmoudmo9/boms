"""Public service of the parties module: parties, roles/stages, contacts, contact methods, documents.

Every write records an event in the caller's transaction and flushes, so constraint problems become
409/422 before the router commits.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select, text, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.text import WORD_SIMILARITY, normalize_fa
from app.modules.documents import service as documents
from app.modules.documents.models import Document, DocumentLink
from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.parties.models import (
    Contact,
    ContactMethod,
    Followup,
    FunnelStage,
    Interaction,
    Party,
    PartyRole,
)
from app.modules.parties.normalize import InvalidPhone, known_region, normalize_method

DUPLICATE_SIMILARITY = 0.6
PARTY_SORTS = {"name": Party.name_norm, "updated_at": Party.updated_at, "created_at": Party.created_at}


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    return value


def _diff(obj, changes: dict) -> dict:
    diff = {}
    for field, value in changes.items():
        if getattr(obj, field) != value:
            diff[field] = {"old": getattr(obj, field), "new": value}
            setattr(obj, field, value)
    return diff


# ---- stages ------------------------------------------------------------------------

def stages(db: Session, role: str | None = None) -> list[FunnelStage]:
    query = select(FunnelStage).order_by(FunnelStage.role, FunnelStage.sort_order)
    if role:
        query = query.where(FunnelStage.role == role)
    return list(db.scalars(query))


def _check_stage(db: Session, role: str, stage: str | None) -> str:
    valid = [s.code for s in stages(db, role)]
    if stage is None:
        return valid[0]
    if stage not in valid:
        raise AppError("invalid_stage", f"Stage {stage!r} is not valid for role {role!r}",
                       {"role": role, "stage": stage, "valid": valid}, status=422)
    return stage


# ---- parties -------------------------------------------------------------------------

def get_party(db: Session, party_id: uuid.UUID) -> Party:
    party = db.get(Party, party_id)
    if party is None:
        raise NotFound("not_found", "Party not found")
    return party


def find_duplicates(db: Session, name_fa: str | None, name_en: str | None,
                    exclude_id: uuid.UUID | None = None, limit: int = 10) -> list[dict]:
    """Parties whose name is similar (pg_trgm similarity >= 0.6, per language or combined)."""
    q_fa = normalize_fa(name_fa or "") or ""
    q_en = normalize_fa(name_en or "") or ""
    q_all = normalize_fa(f"{name_fa or ''} {name_en or ''}") or ""
    if not q_all:
        return []
    rows = db.execute(text(
        """
        SELECT id, name_fa, name_en, status, do_not_contact, score FROM (
          SELECT id, name_fa, name_en, status, do_not_contact, greatest(
            similarity(name_norm, :q_all),
            CASE WHEN :q_fa <> '' THEN similarity(core.normalize_fa(coalesce(name_fa, '')), :q_fa) ELSE 0 END,
            CASE WHEN :q_en <> '' THEN similarity(core.normalize_fa(coalesce(name_en, '')), :q_en) ELSE 0 END
          ) AS score
          FROM core.party WHERE (CAST(:exclude AS uuid) IS NULL OR id <> CAST(:exclude AS uuid))
        ) s WHERE score >= :threshold ORDER BY score DESC LIMIT :limit
        """
    ), {"q_all": q_all, "q_fa": q_fa, "q_en": q_en, "exclude": str(exclude_id) if exclude_id else None,
        "threshold": DUPLICATE_SIMILARITY, "limit": limit}).all()
    return [{"id": r.id, "name_fa": r.name_fa, "name_en": r.name_en, "status": r.status,
             "do_not_contact": r.do_not_contact, "reason": "similar_name", "score": round(float(r.score), 3)}
            for r in rows]


def create_party(db: Session, data: dict, source: str, actor: str | None = None) -> tuple[Party | None, list[dict]]:
    """Returns (party, []) when created, or (None, duplicates) when confirmation is needed."""
    duplicates = find_duplicates(db, data.get("name_fa"), data.get("name_en"))
    if duplicates and not data.get("confirm_duplicate"):
        return None, duplicates
    roles = list(dict.fromkeys(data.get("roles") or []))
    fields = {k: v for k, v in data.items() if k not in {"roles", "confirm_duplicate"}}
    if fields.get("country_iso2"):
        fields["country_iso2"] = fields["country_iso2"].upper()
    party = Party(**fields)
    db.add(party)
    _flush(db, "invalid_party")
    events.record(db, "party", party.id, "create", jsonable({
        "name_fa": party.name_fa, "name_en": party.name_en, "kind": party.kind,
        "confirmed_duplicates": [d["id"] for d in duplicates]}), source, actor=actor)
    for role in roles:
        add_role(db, party.id, role, None, source, actor)
    return party, duplicates


def _flush(db: Session, code: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        detail = str(exc.orig).splitlines()[0] if exc.orig else str(exc)
        if "foreign key" in detail.lower() and "country" in detail.lower():
            raise AppError("unknown_country", "Unknown country code", status=422) from None
        raise Conflict(code, detail) from None


def update_party(db: Session, party_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Party:
    party = get_party(db, party_id)
    if "country_iso2" in changes and changes["country_iso2"]:
        changes["country_iso2"] = changes["country_iso2"].upper()
    if changes.get("do_not_contact") is False:
        changes["do_not_contact_reason"] = None
    name_fa = changes.get("name_fa", party.name_fa) if "name_fa" in changes else party.name_fa
    name_en = changes.get("name_en", party.name_en) if "name_en" in changes else party.name_en
    if not (name_fa or name_en):
        raise AppError("name_required", "The party needs a Persian or English name", status=422)
    dnc = changes.get("do_not_contact", party.do_not_contact)
    reason = changes.get("do_not_contact_reason", party.do_not_contact_reason)
    if dnc and not (reason or "").strip():
        raise AppError("dnc_reason_required", "A reason is required for do-not-contact", status=422)
    diff = _diff(party, changes)
    if diff:
        _flush(db, "invalid_party")
        events.record(db, "party", party.id, "update", jsonable({"changes": diff}), source, actor=actor)
    return party


def set_status(db: Session, party_id: uuid.UUID, status: str, source: str, actor: str | None = None,
               open_followups: str = "cancel") -> Party:
    """Archive/unarchive. On archive, open follow-ups are cancelled ("party archived") or kept."""
    party = get_party(db, party_id)
    if party.status != status:
        party.status = status
        db.flush()
        cancelled = []
        if status == "archived" and open_followups == "cancel":
            for row in db.scalars(select(Followup).where(Followup.party_id == party_id, Followup.status == "open")):
                row.status, row.done_at, row.done_note = "cancelled", clock.now(), "party archived"
                db.flush()
                events.record(db, "followup", row.id, "cancel", {"note": "party archived"}, source, actor=actor)
                cancelled.append(str(row.id))
        data = {"open_followups": open_followups, "cancelled": cancelled} if status == "archived" else {}
        events.record(db, "party", party.id, "archive" if status == "archived" else "unarchive", data, source,
                      actor=actor)
    return party


def roles_of(db: Session, party_id: uuid.UUID) -> list[PartyRole]:
    return list(db.scalars(select(PartyRole).where(PartyRole.party_id == party_id).order_by(PartyRole.created_at)))


def add_role(db: Session, party_id: uuid.UUID, role: str, stage: str | None, source: str,
             actor: str | None = None) -> PartyRole:
    get_party(db, party_id)
    stage = _check_stage(db, role, stage)
    if db.scalar(select(PartyRole).where(PartyRole.party_id == party_id, PartyRole.role == role)):
        raise Conflict("duplicate_role", f"The party already has the role {role}", {"role": role})
    row = PartyRole(party_id=party_id, role=role, stage=stage, stage_changed_at=clock.now())
    db.add(row)
    _flush(db, "duplicate_role")
    events.record(db, "party", party_id, "role_add", {"role": role, "stage": stage}, source, actor=actor)
    return row


def remove_role(db: Session, party_id: uuid.UUID, role: str, source: str, actor: str | None = None) -> None:
    row = db.scalar(select(PartyRole).where(PartyRole.party_id == party_id, PartyRole.role == role))
    if row is None:
        raise NotFound("not_found", "Role not found")
    data = {"role": role, "stage": row.stage}
    db.delete(row)
    db.flush()
    events.record(db, "party", party_id, "role_remove", data, source, actor=actor)


def change_stage(db: Session, party_id: uuid.UUID, role: str, stage: str, reason: str | None, source: str,
                 actor: str | None = None) -> PartyRole:
    get_party(db, party_id)
    row = db.scalar(select(PartyRole).where(PartyRole.party_id == party_id, PartyRole.role == role))
    if row is None:
        raise AppError("role_not_assigned", f"The party does not have the role {role}", {"role": role}, status=422)
    stage = _check_stage(db, role, stage)
    if row.stage == stage:
        return row
    old = row.stage
    row.stage = stage
    row.stage_changed_at = clock.now()
    db.flush()
    events.record(db, "party", party_id, "stage_change",
                  {"role": role, "old_stage": old, "new_stage": stage, "reason": reason}, source, actor=actor)
    return row


def list_parties(db: Session, *, q: str | None = None, role: str | None = None, stage: str | None = None,
                 country: str | None = None, status: str | None = "active", sort: str = "updated_at",
                 order: str = "desc", page: int = 1, page_size: int = 50,
                 ids: set[uuid.UUID] | None = None) -> tuple[list[Party], int]:
    query = select(Party)
    if ids is not None:  # e.g. the capability filter (Phase 5)
        query = query.where(Party.id.in_(ids or [uuid.uuid4()]))
    if status:
        query = query.where(Party.status == status)
    if country:
        query = query.where(Party.country_iso2 == country.upper())
    if role or stage:
        sub = select(PartyRole.party_id)
        if role:
            sub = sub.where(PartyRole.role == role)
        if stage:
            sub = sub.where(PartyRole.stage == stage)
        query = query.where(Party.id.in_(sub))
    needle = normalize_fa(q or "")
    if needle:
        db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"),
                   {"v": str(WORD_SIMILARITY)})
        like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        method_match = select(Contact.party_id).join(ContactMethod, ContactMethod.contact_id == Contact.id).where(
            ContactMethod.value_norm.like(like))
        query = query.where(Party.name_norm.like(like) | Party.name_norm.op("%>")(needle)
                            | Party.id.in_(method_match))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    column = PARTY_SORTS.get(sort, Party.updated_at)
    query = query.order_by(column.asc() if order == "asc" else column.desc(), Party.id)
    rows = db.scalars(query.offset((page - 1) * page_size).limit(page_size))
    return list(rows), total


def roles_for(db: Session, party_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PartyRole]]:
    result: dict[uuid.UUID, list[PartyRole]] = {pid: [] for pid in party_ids}
    if party_ids:
        for row in db.scalars(select(PartyRole).where(PartyRole.party_id.in_(party_ids))
                              .order_by(PartyRole.created_at)):
            result[row.party_id].append(row)
    return result


def activity_for(db: Session, party_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Last interaction time and next open follow-up per party."""
    result = {pid: {"last_interaction_at": None, "next_followup": None} for pid in party_ids}
    if not party_ids:
        return result
    for pid, last in db.execute(select(Interaction.party_id, func.max(Interaction.occurred_at))
                                .where(Interaction.party_id.in_(party_ids)).group_by(Interaction.party_id)):
        result[pid]["last_interaction_at"] = last
    rows = db.scalars(
        select(Followup).where(Followup.party_id.in_(party_ids), Followup.status == "open")
        .order_by(Followup.party_id, Followup.due_on, Followup.created_at)
    )
    for f in rows:  # ordered by due date: keep the first per party
        if result[f.party_id]["next_followup"] is None:
            result[f.party_id]["next_followup"] = {"id": f.id, "action": f.action, "due_on": f.due_on}
    return result


# ---- contacts -----------------------------------------------------------------------

def get_contact(db: Session, contact_id: uuid.UUID) -> Contact:
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise NotFound("not_found", "Contact not found")
    return contact


def contacts_of(db: Session, party_id: uuid.UUID) -> list[Contact]:
    return list(db.scalars(select(Contact).where(Contact.party_id == party_id)
                           .order_by(Contact.is_primary.desc(), Contact.created_at)))


def methods_of(db: Session, contact_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ContactMethod]]:
    result: dict[uuid.UUID, list[ContactMethod]] = {cid: [] for cid in contact_ids}
    if contact_ids:
        for m in db.scalars(select(ContactMethod).where(ContactMethod.contact_id.in_(contact_ids))
                            .order_by(ContactMethod.is_primary.desc(), ContactMethod.created_at)):
            result[m.contact_id].append(m)
    return result


def _clear_primary_contact(db: Session, party_id: uuid.UUID, keep: uuid.UUID | None) -> None:
    db.execute(update(Contact).where(Contact.party_id == party_id, Contact.is_primary,
                                     Contact.id != keep if keep else true()).values(is_primary=False))


def _normalize(method_type: str, value: str, region: str | None) -> str:
    try:
        value_norm = normalize_method(method_type, value, region)
    except InvalidPhone as exc:
        raise AppError("invalid_phone", f"Not a possible phone number ({exc.reason})", {"reason": exc.reason},
                       status=422) from None
    if not value_norm:
        raise AppError("invalid_contact_value", "The value is empty after normalization", status=422)
    return value_norm


def _region_for(db: Session, contact: Contact, requested: str | None) -> str | None:
    """Region for numbers typed without "+"/"00": the client's choice, else the party's country (else IR)."""
    return known_region(requested) or known_region(db.get(Party, contact.party_id).country_iso2)


def _shared_with(db: Session, contact_id: uuid.UUID | None, method_type: str, value_norm: str,
                 exclude: uuid.UUID | None = None) -> list[dict]:
    """Active methods with the same value. Same contact -> 409; other contacts -> returned as a warning."""
    query = (select(ContactMethod, Contact, Party)
             .join(Contact, Contact.id == ContactMethod.contact_id)
             .join(Party, Party.id == Contact.party_id)
             .where(ContactMethod.type == method_type, ContactMethod.value_norm == value_norm,
                    ContactMethod.status == "active"))
    if exclude:
        query = query.where(ContactMethod.id != exclude)
    shared = []
    for method, contact, party in db.execute(query):
        if contact_id and contact.id == contact_id:
            raise Conflict("duplicate_contact_method", f"This contact already has this {method_type}",
                           jsonable({"type": method_type, "value": method.value, "contact_id": contact.id}))
        shared.append(jsonable({"type": method_type, "value": method.value, "contact_id": contact.id,
                                "contact_name": contact.name_fa or contact.name_en, "party_id": party.id,
                                "party_name": party.name_fa or party.name_en}))
    return shared


def _insert_method(db: Session, contact: Contact, data: dict, value_norm: str, source: str,
                   actor: str | None) -> ContactMethod:
    value = data["value"].strip()
    if data.get("is_primary"):
        db.execute(update(ContactMethod).where(ContactMethod.contact_id == contact.id, ContactMethod.is_primary)
                   .values(is_primary=False))
    method = ContactMethod(contact_id=contact.id, type=data["type"], value=value, value_norm=value_norm,
                           is_primary=bool(data.get("is_primary")))
    db.add(method)
    _flush(db, "duplicate_contact_method")
    events.record(db, "contact", contact.id, "method_add",
                  {"type": method.type, "value": value, "value_norm": value_norm,
                   "party_id": str(contact.party_id)}, source, actor=actor)
    return method


def create_contact(db: Session, data: dict, source: str, actor: str | None = None,
                   confirm_shared: bool = False) -> tuple[Contact | None, list[dict]]:
    """Returns (contact, shared_with); (None, shared_with) when a number is used elsewhere and not confirmed."""
    party = get_party(db, data["party_id"])
    methods = data.pop("methods", [])
    region_default = known_region(party.country_iso2)
    prepared, shared, seen = [], [], set()
    for method in methods:
        value_norm = _normalize(method["type"], method["value"], known_region(method.get("region")) or region_default)
        if (method["type"], value_norm) in seen:
            raise Conflict("duplicate_contact_method", "The same value is given twice",
                           {"type": method["type"], "value": method["value"]})
        seen.add((method["type"], value_norm))
        shared += _shared_with(db, None, method["type"], value_norm)
        prepared.append((method, value_norm))
    if shared and not confirm_shared:
        return None, shared
    if data.get("is_primary"):
        _clear_primary_contact(db, data["party_id"], None)
    contact = Contact(**data)
    db.add(contact)
    _flush(db, "invalid_contact")
    events.record(db, "contact", contact.id, "create", jsonable({
        "party_id": contact.party_id, "name_fa": contact.name_fa, "name_en": contact.name_en,
        "confirmed_shared": shared}), source, actor=actor)
    events.record(db, "party", contact.party_id, "contact_add", jsonable({"contact_id": contact.id}), source,
                  actor=actor)
    for method, value_norm in prepared:
        _insert_method(db, contact, method, value_norm, source, actor)
    return contact, shared


def update_contact(db: Session, contact_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Contact:
    contact = get_contact(db, contact_id)
    name_fa = changes["name_fa"] if "name_fa" in changes else contact.name_fa
    name_en = changes["name_en"] if "name_en" in changes else contact.name_en
    if not (name_fa or name_en):
        raise AppError("name_required", "The contact needs a Persian or English name", status=422)
    if changes.get("is_primary"):
        _clear_primary_contact(db, contact.party_id, contact.id)
    diff = _diff(contact, changes)
    if diff:
        _flush(db, "invalid_contact")
        events.record(db, "contact", contact.id, "update", jsonable({"changes": diff}), source, actor=actor)
    return contact


def set_contact_status(db: Session, contact_id: uuid.UUID, status: str, source: str,
                       actor: str | None = None) -> Contact:
    contact = get_contact(db, contact_id)
    if contact.status != status:
        contact.status = status
        if status == "archived":
            contact.is_primary = False
        _flush(db, "invalid_contact")
        events.record(db, "contact", contact.id, "archive" if status == "archived" else "unarchive", {}, source,
                      actor=actor)
    return contact


def add_method(db: Session, contact_id: uuid.UUID, data: dict, source: str, actor: str | None = None,
               confirm_shared: bool = False) -> tuple[ContactMethod | None, list[dict]]:
    contact = get_contact(db, contact_id)
    value_norm = _normalize(data["type"], data["value"], _region_for(db, contact, data.get("region")))
    shared = _shared_with(db, contact.id, data["type"], value_norm)
    if shared and not confirm_shared:
        return None, shared
    return _insert_method(db, contact, data, value_norm, source, actor), shared


def get_method(db: Session, method_id: uuid.UUID) -> ContactMethod:
    method = db.get(ContactMethod, method_id)
    if method is None:
        raise NotFound("not_found", "Contact method not found")
    return method


def update_method(db: Session, method_id: uuid.UUID, changes: dict, source: str, actor: str | None = None,
                  confirm_shared: bool = False) -> tuple[ContactMethod | None, list[dict]]:
    method = get_method(db, method_id)
    region = changes.pop("region", None)
    shared: list[dict] = []
    if changes.get("value") is not None:
        value = changes["value"].strip()
        value_norm = _normalize(method.type, value, _region_for(db, get_contact(db, method.contact_id), region))
        if method.status == "active":
            shared = _shared_with(db, method.contact_id, method.type, value_norm, exclude=method.id)
            if shared and not confirm_shared:
                return None, shared
        changes["value"], changes["value_norm"] = value, value_norm
    if changes.get("is_primary"):
        db.execute(update(ContactMethod).where(ContactMethod.contact_id == method.contact_id,
                                               ContactMethod.id != method.id).values(is_primary=False))
    diff = _diff(method, {k: v for k, v in changes.items() if v is not None})
    if diff:
        _flush(db, "duplicate_contact_method")
        events.record(db, "contact", method.contact_id, "method_update",
                      jsonable({"method_id": method.id, "changes": diff}), source, actor=actor)
    return method, shared


def set_method_status(db: Session, method_id: uuid.UUID, status: str, source: str,
                      actor: str | None = None) -> ContactMethod:
    method = get_method(db, method_id)
    if method.status != status:
        method.status = status
        if status == "archived":
            method.is_primary = False
        _flush(db, "duplicate_contact_method")  # restoring may collide with an active copy on the same contact
        events.record(db, "contact", method.contact_id, f"method_{'archive' if status == 'archived' else 'unarchive'}",
                      jsonable({"method_id": method.id}), source, actor=actor)
    return method


# ---- deletes (real deletes when nothing depends on the row; snapshot in the event) -----------

def _row(obj) -> dict:
    return jsonable({c.key: getattr(obj, c.key) for c in obj.__table__.columns if c.key not in {"name_norm", "body_norm"}})


def delete_method(db: Session, method_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    method = get_method(db, method_id)
    snapshot = _row(method)
    db.delete(method)
    db.flush()
    events.record(db, "contact", method.contact_id, "method_delete", {"deleted": snapshot}, source, actor=actor)


def delete_contact(db: Session, contact_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    contact = get_contact(db, contact_id)
    used = db.scalar(select(func.count()).select_from(Interaction).where(Interaction.contact_id == contact.id)) or 0
    if used:
        raise Conflict("in_use", "The contact is referenced by interactions", {"interactions": used})
    methods = list(db.scalars(select(ContactMethod).where(ContactMethod.contact_id == contact.id)))
    snapshot = {**_row(contact), "methods": [_row(m) for m in methods]}
    for method in methods:
        db.delete(method)
    db.flush()
    db.delete(contact)
    db.flush()
    events.record(db, "contact", contact.id, "delete", {"deleted": snapshot}, source, actor=actor)
    events.record(db, "party", contact.party_id, "contact_delete", jsonable({"contact_id": contact.id}), source,
                  actor=actor)


def dependency_counts(db: Session, party_id: uuid.UUID) -> dict[str, int]:
    interaction_ids = [str(i) for i in db.scalars(select(Interaction.id).where(Interaction.party_id == party_id))]
    docs = db.scalar(select(func.count()).select_from(DocumentLink).where(
        ((DocumentLink.entity_type == "party") & (DocumentLink.entity_id == str(party_id)))
        | ((DocumentLink.entity_type == "interaction") & DocumentLink.entity_id.in_(interaction_ids or [""])))) or 0
    return {
        "interactions": len(interaction_ids),
        "followups": db.scalar(select(func.count()).select_from(Followup).where(Followup.party_id == party_id)) or 0,
        "documents": docs,
    }


def delete_party(db: Session, party_id: uuid.UUID, source: str, actor: str | None = None, *,
                 cascade: bool = False, confirm_name: str | None = None) -> dict:
    """Delete a party. Without ``cascade`` only when nothing depends on it (else 409 in_use with counts).

    ``cascade`` (test-data cleanup) also deletes its interactions, follow-ups and document links, and needs
    the exact party name. Interaction deletes are allowed by a transaction-local flag only.
    """
    party = get_party(db, party_id)
    counts = dependency_counts(db, party_id)
    if cascade:
        names = {(party.name_fa or "").strip(), (party.name_en or "").strip()} - {""}
        if (confirm_name or "").strip() not in names:
            raise AppError("confirm_name_mismatch", "Type the exact party name to confirm", status=422)
    elif any(counts.values()):
        raise Conflict("in_use", "The party has interactions, follow-ups or documents", counts)

    contacts = list(db.scalars(select(Contact).where(Contact.party_id == party_id)))
    methods = list(db.scalars(select(ContactMethod).where(ContactMethod.contact_id.in_([c.id for c in contacts]))))
    roles = roles_of(db, party_id)
    interactions = list(db.scalars(select(Interaction).where(Interaction.party_id == party_id)))
    followups = list(db.scalars(select(Followup).where(Followup.party_id == party_id)))
    links = party_documents(db, party_id)
    snapshot = {
        "party": _row(party),
        "roles": [_row(r) for r in roles],
        "contacts": [{**_row(c), "methods": [_row(m) for m in methods if m.contact_id == c.id]} for c in contacts],
        "interactions": [_row(i) for i in interactions],
        "followups": [_row(f) for f in followups],
        "document_links": jsonable(links),
    }

    if cascade:
        db.execute(text("SELECT set_config('boms.allow_interaction_delete', 'on', true)"))
        for link in links:
            documents.unlink(db, link["document_id"], link["link_id"], source=source, actor=actor)
        for row in followups:
            db.delete(row)
        db.flush()
        for row in interactions:
            db.delete(row)
        db.flush()
    for row in methods:
        db.delete(row)
    db.flush()
    for row in contacts + roles:
        db.delete(row)
    db.flush()
    db.delete(party)
    _flush(db, "in_use")
    events.record(db, "party", party_id, "delete", {"cascade": cascade, "counts": counts, "deleted": snapshot},
                  source, actor=actor)
    return counts


# ---- documents (core.document_link, owned by the documents module) ---------------------

def linked_documents(db: Session, entity_type: str, entity_ids: list[str]) -> list[dict]:
    if not entity_ids:
        return []
    rows = db.execute(
        select(DocumentLink, Document)
        .join(Document, Document.id == DocumentLink.document_id)
        .where(DocumentLink.entity_type == entity_type, DocumentLink.entity_id.in_(entity_ids))
        .order_by(DocumentLink.created_at.desc())
    ).all()
    return [{"link_id": link.id, "entity_type": link.entity_type, "entity_id": link.entity_id,
             "document_id": doc.id, "title": doc.title, "original_filename": doc.original_filename,
             "mime_type": doc.mime_type, "size_bytes": doc.size_bytes, "linked_at": link.created_at}
            for link, doc in rows]


def party_documents(db: Session, party_id: uuid.UUID) -> list[dict]:
    interaction_ids = [str(i) for i in db.scalars(select(Interaction.id).where(Interaction.party_id == party_id))]
    return linked_documents(db, "party", [str(party_id)]) + linked_documents(db, "interaction", interaction_ids)


def link_document(db: Session, entity_type: str, entity_id: uuid.UUID, document_id: uuid.UUID, source: str,
                  actor: str | None = None):
    return documents.link(db, document_id, entity_type, str(entity_id), "attachment", source=source, actor=actor)


def unlink_document(db: Session, entity_type: str, entity_id: uuid.UUID, link_id: uuid.UUID, source: str,
                    actor: str | None = None) -> None:
    link = db.get(DocumentLink, link_id)
    if link is None or link.entity_type != entity_type or link.entity_id != str(entity_id):
        raise NotFound("not_found", "Link not found")
    documents.unlink(db, link.document_id, link_id, source=source, actor=actor)
