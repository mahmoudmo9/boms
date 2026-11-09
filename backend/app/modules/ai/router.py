"""AI API (v0.9.0): Settings → «هوش مصنوعی» (providers with status and test, keys in Credential Manager, prices, routes
per task, cap and spending, the privacy log «چه چیزی کجا رفت»), a case's «فقط محلی», and the drafts of the review
screen."""
import sys
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.web import request_source
from app.modules.ai import adapters, drafts, service
from app.modules.ai.models import Call, Price, Provider, Route
from app.modules.events import service as events
from app.core.schemas import InputModel
from app.modules.sourcing.common import jsonable
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api/ai", tags=["ai"])
ModelId = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:/\-]+$")]


def provider_out(db: Session, p: Provider) -> dict:
    from app.core import secrets

    has_key = bool(p.secret_name and secrets.get_named_secret(p.secret_name))
    return jsonable({"id": p.id, "kind": p.kind, "label": p.label, "enabled": p.enabled, "base_url": p.base_url,
                     "models": p.models, "secret_name": p.secret_name, "has_key": has_key, "status": p.status,
                     "status_detail": p.status_detail, "last_checked_at": p.last_checked_at,
                     "last_latency_ms": p.last_latency_ms, "local": service.is_local(p),
                     "api": p.kind in adapters.API_KINDS, "missing_prices": service.missing_prices(db, p),
                     "cli": adapters.cli_status() if p.kind == "claude_subscription" else None})


class ProviderIn(InputModel):
    label: Annotated[str, Field(min_length=1, max_length=100)]
    base_url: Annotated[str, Field(max_length=300, pattern=r"^https?://")]
    models: list[ModelId] = []


class ProviderPatch(InputModel):
    label: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    enabled: bool | None = None
    base_url: Annotated[str, Field(max_length=300, pattern=r"^https?://")] | None = None
    models: Annotated[list[ModelId], Field(max_length=20)] | None = None
    secret_name: Annotated[str, Field(pattern=r"^ai\.[a-z0-9_.-]{1,60}$")] | None = None


class KeyIn(InputModel):
    value: Annotated[str, Field(min_length=8, max_length=500)] | None = None


class PriceIn(InputModel):
    provider_id: uuid.UUID
    model: ModelId
    input_per_mtok: Annotated[Decimal, Field(ge=0, le=10000)]
    output_per_mtok: Annotated[Decimal, Field(ge=0, le=10000)]


class RoutePatch(InputModel):
    primary_provider_id: uuid.UUID | None = None
    primary_model: ModelId | None = None
    fallback_provider_id: uuid.UUID | None = None
    fallback_model: ModelId | None = None
    privacy: Literal["cloud", "cloud_redacted", "local_only"] | None = None


class PrivacyIn(InputModel):
    local_only: bool


class DecisionIn(InputModel):
    decision: Literal["accepted", "edited", "rejected", "undecided"]
    value: Any = None


# ---- providers -------------------------------------------------------------------------------------------------------

@router.get("/providers")
def list_providers(_: CurrentUser, db: Db):
    rows = db.scalars(select(Provider).order_by(Provider.created_at))
    return [provider_out(db, p) for p in rows]


@router.post("/providers", status_code=201)
def add_provider(body: ProviderIn, request: Request, user: CurrentUser, db: Db):
    """Another OpenAI-compatible server (a second Ollama PC, a self-hosted gateway)."""
    row = Provider(kind="openai_compatible", label=body.label, base_url=body.base_url, models=body.models)
    db.add(row)
    from app.modules.sourcing.common import flush

    flush(db, "ai_provider")
    events.record(db, "ai_provider", row.id, "create", {"kind": row.kind, "label": row.label}, request_source(request),
                  actor=user.username)
    db.commit()
    return provider_out(db, row)


@router.patch("/providers/{provider_id}")
def patch_provider(provider_id: uuid.UUID, body: ProviderPatch, request: Request, user: CurrentUser, db: Db):
    p = service.get_provider(db, provider_id)
    changes = body.model_dump(exclude_unset=True)
    if "base_url" in changes and p.kind not in ("ollama", "openai_compatible"):
        raise AppError("base_url_not_allowed", "Only local or self-hosted providers have an address", status=422)
    for key, value in changes.items():
        if key != "enabled":
            setattr(p, key, value)
    if changes.get("enabled") is True:
        if not p.models and p.kind != "claude_subscription":
            raise AppError("models_required", "Add at least one model before enabling", status=422)
        missing = service.missing_prices(db, p)
        if missing:
            raise AppError("prices_required", "Enter the prices of every model before enabling an API provider",
                           {"models": missing}, status=422)
    if "enabled" in changes:
        p.enabled = changes["enabled"]
    if p.kind in adapters.API_KINDS and p.enabled and "models" in changes and service.missing_prices(db, p):
        raise AppError("prices_required", "Enter the prices of every model of an enabled API provider",
                       {"models": service.missing_prices(db, p)}, status=422)
    db.flush()
    events.record(db, "ai_provider", p.id, "update", jsonable(changes), request_source(request), actor=user.username)
    db.commit()
    return provider_out(db, p)


@router.put("/providers/{provider_id}/key")
def set_key(provider_id: uuid.UUID, body: KeyIn, request: Request, user: CurrentUser, db: Db):
    """The API key goes to Windows Credential Manager (never the database or a file); ``value: null`` removes it."""
    from app.core import secrets

    p = service.get_provider(db, provider_id)
    p.secret_name = p.secret_name or f"ai.{p.kind}.{str(p.id)[-8:]}"
    if sys.platform != "win32":
        raise AppError("credential_store_unavailable", "Keys are stored in Windows Credential Manager; on this machine "
                       f"set the environment variable {secrets.env_name_for(p.secret_name)}",
                       {"env": secrets.env_name_for(p.secret_name)}, status=409)
    secrets.set_named_secret(p.secret_name, body.value)
    db.flush()
    events.record(db, "ai_provider", p.id, "key", {"set": bool(body.value)}, request_source(request), actor=user.username)
    db.commit()
    return provider_out(db, p)


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: uuid.UUID, _: CurrentUser, db: Db):
    result = service.test_connection(db, provider_id)
    db.commit()
    return result


# ---- prices, routes, usage -------------------------------------------------------------------------------------------

@router.get("/prices")
def list_prices(_: CurrentUser, db: Db):
    return jsonable([{"id": r.id, "provider_id": r.provider_id, "model": r.model, "input_per_mtok": r.input_per_mtok,
                      "output_per_mtok": r.output_per_mtok} for r in db.scalars(select(Price).order_by(Price.model))])


@router.put("/prices")
def set_price(body: PriceIn, request: Request, user: CurrentUser, db: Db):
    service.get_provider(db, body.provider_id)
    row = service.price_of(db, body.provider_id, body.model)
    if row is None:
        row = Price(provider_id=body.provider_id, model=body.model)
        db.add(row)
    row.input_per_mtok, row.output_per_mtok = body.input_per_mtok, body.output_per_mtok
    db.flush()
    events.record(db, "ai_price", row.id, "set", jsonable(body.model_dump()), request_source(request), actor=user.username)
    db.commit()
    return jsonable({"id": row.id, "provider_id": row.provider_id, "model": row.model,
                     "input_per_mtok": row.input_per_mtok, "output_per_mtok": row.output_per_mtok})


@router.get("/routes")
def list_routes(_: CurrentUser, db: Db):
    return jsonable([{"id": r.id, "task": r.task, "primary_provider_id": r.primary_provider_id,
                      "primary_model": r.primary_model, "fallback_provider_id": r.fallback_provider_id,
                      "fallback_model": r.fallback_model, "privacy": r.privacy}
                     for r in db.scalars(select(Route).order_by(Route.task))])


@router.patch("/routes/{task}")
def patch_route(task: str, body: RoutePatch, request: Request, user: CurrentUser, db: Db):
    from app.modules.sourcing.common import flush

    row = db.scalar(select(Route).where(Route.task == task))
    if row is None:
        from app.core.errors import NotFound

        raise NotFound("not_found", "Route not found")
    changes = body.model_dump(exclude_unset=True)
    for key in ("primary_provider_id", "fallback_provider_id"):
        if changes.get(key):
            service.get_provider(db, changes[key])
    for key, value in changes.items():
        setattr(row, key, value)
    flush(db, "ai_route")
    events.record(db, "ai_route", row.id, "update", jsonable(changes), request_source(request), actor=user.username)
    db.commit()
    return list_routes(user, db)


@router.get("/usage")
def get_usage(_: CurrentUser, db: Db):
    return {**service.usage(db), "configured": service.configured(db)}


@router.get("/calls")
def list_calls(_: CurrentUser, db: Db, task: str | None = None, provider_id: uuid.UUID | None = None,
               status: str | None = None, case_id: uuid.UUID | None = None, page: int = 1,
               page_size: Annotated[int, Query(le=200)] = 50):
    """«چه چیزی کجا رفت»: what was sent where (descriptions only, never the content)."""
    stmt = select(Call)
    for col, value in ((Call.task, task), (Call.provider_id, provider_id), (Call.status, status), (Call.case_id, case_id)):
        if value is not None:
            stmt = stmt.where(col == value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Call.created_at.desc()).offset((max(page, 1) - 1) * page_size).limit(page_size))
    labels = {p.id: p.label for p in db.scalars(select(Provider))}
    return {"total": total, "items": jsonable([
        {"id": c.id, "at": c.created_at, "task": c.task, "entity_type": c.entity_type, "entity_id": c.entity_id,
         "case_id": c.case_id, "provider": labels.get(c.provider_id), "provider_kind": c.provider_kind, "model": c.model,
         "prompt_version": c.prompt_version, "input": c.input, "redactions": c.redactions, "privacy": c.privacy,
         "tokens_in": c.tokens_in, "tokens_out": c.tokens_out, "cost_usd": c.cost_usd, "subscription": c.subscription,
         "duration_ms": c.duration_ms, "status": c.status, "error": c.error, "attempt": c.attempt,
         "fallback_of_id": c.fallback_of_id} for c in rows])}


# ---- a case's privacy ------------------------------------------------------------------------------------------------

@router.get("/cases/{case_id}/privacy")
def get_case_privacy(case_id: uuid.UUID, _: CurrentUser, db: Db):
    return {"case_id": str(case_id), "local_only": service.case_local_only(db, case_id)}


@router.put("/cases/{case_id}/privacy")
def put_case_privacy(case_id: uuid.UUID, body: PrivacyIn, request: Request, user: CurrentUser, db: Db):
    out = service.set_case_local_only(db, case_id, body.local_only, request_source(request), user.username)
    db.commit()
    return out


# ---- drafts (the review screen) --------------------------------------------------------------------------------------

@router.get("/drafts")
def list_drafts(_: CurrentUser, db: Db, target_type: str | None = None, target_id: str | None = None,
                case_id: uuid.UUID | None = None, status: str | None = None):
    from app.modules.ai.models import Draft

    stmt = select(Draft)
    for col, value in ((Draft.target_type, target_type), (Draft.target_id, target_id), (Draft.case_id, case_id),
                       (Draft.status, status)):
        if value is not None:
            stmt = stmt.where(col == value)
    return [drafts.out(db, d) for d in db.scalars(stmt.order_by(Draft.created_at.desc()).limit(50))]


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: uuid.UUID, _: CurrentUser, db: Db):
    return drafts.out(db, drafts.get(db, draft_id))


@router.patch("/drafts/{draft_id}/fields/{field_id}")
def decide_field(draft_id: uuid.UUID, field_id: uuid.UUID, body: DecisionIn, _: CurrentUser, db: Db):
    drafts.decide(db, draft_id, field_id, body.decision, body.value)
    db.commit()
    return drafts.out(db, drafts.get(db, draft_id))


@router.post("/drafts/{draft_id}/accept-confident")
def accept_confident(draft_id: uuid.UUID, _: CurrentUser, db: Db):
    count = drafts.accept_confident(db, draft_id)
    db.commit()
    return {"accepted": count, **drafts.out(db, drafts.get(db, draft_id))}


@router.post("/drafts/{draft_id}/commit")
def commit_draft(draft_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    result = drafts.commit(db, draft_id, request_source(request), user.username)
    db.commit()
    return {"result": jsonable(result), **drafts.out(db, drafts.get(db, draft_id))}


@router.post("/drafts/{draft_id}/reject")
def reject_draft(draft_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    drafts.reject(db, draft_id, request_source(request), user.username)
    db.commit()
    return drafts.out(db, drafts.get(db, draft_id))


# ---- the tasks (v0.9.0 section 3): each starts a job and returns the pending draft ------------------------------------

class ExtractIn(InputModel):
    target_type: Literal["case", "inquiry", "offer", "listing"]
    target_id: uuid.UUID
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    text: Annotated[str, Field(max_length=200000)] | None = None
    party_id: uuid.UUID | None = None


class PartyParseIn(InputModel):
    text: Annotated[str, Field(max_length=20000)] | None = None
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)
    roles: list[Literal["buyer", "supplier", "forwarder", "customs_broker", "agent", "other"]] = []
    confirm_duplicate: bool = False


class DraftMessageIn(InputModel):
    target_type: Literal["rfq_recipient", "purchase_order"]
    target_id: uuid.UUID
    language: Literal["en", "fa"] | None = None


def _ensure_tasks() -> None:
    from app.modules.ai import builtin, tasks

    if "extract_items" not in tasks.TASKS:
        builtin.register()


@router.post("/extract", status_code=202)
def extract(body: ExtractIn, request: Request, user: CurrentUser, db: Db):
    """«استخراج با هوش مصنوعی»: items from files or pasted text into a draft the owner reviews."""
    from app.modules.ai import builtin

    _ensure_tasks()
    draft = builtin.start_extraction(db, target_type=body.target_type, target_id=body.target_id,
                                     document_ids=body.document_ids, text_=body.text, party_id=body.party_id,
                                     source=request_source(request), actor=user.username)
    db.commit()
    return drafts.out(db, draft)


@router.post("/parse-party", status_code=202)
def parse_party(body: PartyParseIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.ai import tasks

    _ensure_tasks()
    if not (body.text and body.text.strip()) and not body.document_ids:
        raise AppError("nothing_to_read", "Paste the signature or give a card image", status=422)
    draft = tasks.start(db, "parse_party", target_type="party",
                        payload={"text": body.text or "", "document_ids": [str(d) for d in body.document_ids],
                                 "roles": body.roles, "confirm_duplicate": body.confirm_duplicate},
                        source=request_source(request), actor=user.username)
    db.commit()
    return drafts.out(db, draft)


@router.post("/draft-message", status_code=202)
def draft_message(body: DraftMessageIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.ai import builtin

    _ensure_tasks()
    draft = builtin.start_drafting(db, target_type=body.target_type, target_id=body.target_id, language=body.language,
                                   source=request_source(request), actor=user.username)
    db.commit()
    return drafts.out(db, draft)


ROUTERS = [router]
