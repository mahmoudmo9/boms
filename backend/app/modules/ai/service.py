"""Running an AI task (v0.9.0 sections 1.2-1.3): routing, fallback, privacy, the monthly cap, redaction, structured
output with one retry, and the privacy log.

``run(db, task, text=…, images=…, schema=…, case_id=…)`` picks the route of the task (primary, then fallback), skips any
provider the privacy level or the cap does not allow, redacts for ``cloud_redacted``, validates the answer against the
task's schema (retrying once with the errors), restores the redacted values and logs every attempt in ``ai.call``
— the input is described (file names, pages, characters, redactions), never stored."""
import ipaddress
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.modules.ai import adapters, prompts, redact, schema as schema_mod
from app.modules.ai.adapters import API_KINDS, Attachment, ProviderError, Request
from app.modules.ai.models import Call, CaseSetting, Price, Provider, Route

MTOK = Decimal(1_000_000)
CHARS_PER_TOKEN = Decimal("3.5")
IMAGE_TOKENS = 1600          # a conservative estimate for one page image
WARN_LEVELS = (50, 80)


# ---- secrets ---------------------------------------------------------------------------------------------------------

def api_key(provider: Provider) -> str | None:
    from app.core import secrets

    return secrets.get_named_secret(provider.secret_name) if provider.secret_name else None


# ---- privacy ---------------------------------------------------------------------------------------------------------

def is_local(provider: Provider) -> bool:
    """Ollama, or an OpenAI-compatible server on this PC or the local network."""
    if provider.kind == "ollama":
        return True
    if provider.kind != "openai_compatible" or not provider.base_url:
        return False
    host = urlparse(provider.base_url).hostname or ""
    if host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def case_local_only(db: Session, case_id) -> bool:
    if not case_id:
        return False
    return bool(db.scalar(select(CaseSetting.local_only).where(CaseSetting.case_id == case_id)))


def set_case_local_only(db: Session, case_id: uuid.UUID, local_only: bool, source: str, actor: str | None) -> dict:
    from app.modules.events import service as events
    from app.modules.sourcing.inquiries import get_case

    get_case(db, case_id)
    row = db.scalar(select(CaseSetting).where(CaseSetting.case_id == case_id))
    if row is None:
        row = CaseSetting(case_id=case_id, local_only=local_only)
        db.add(row)
    else:
        row.local_only = local_only
    db.flush()
    events.record(db, "case", case_id, "ai_privacy", {"local_only": local_only}, source, actor=actor)
    return {"case_id": str(case_id), "local_only": local_only}


# ---- prices and the cap ----------------------------------------------------------------------------------------------

def price_of(db: Session, provider_id, model: str) -> Price | None:
    return db.scalar(select(Price).where(Price.provider_id == provider_id, Price.model == model))


def cost(price: Price | None, tokens_in: int | None, tokens_out: int | None) -> Decimal | None:
    if price is None:
        return None
    total = (Decimal(tokens_in or 0) * price.input_per_mtok + Decimal(tokens_out or 0) * price.output_per_mtok) / MTOK
    return total.quantize(Decimal("0.000001"), ROUND_HALF_UP)


def month_start(now: datetime | None = None) -> datetime:
    from app.core.time import utcnow

    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_spend(db: Session) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(Call.cost_usd), 0)).where(Call.created_at >= month_start(),
                                                                             Call.subscription.is_(False))) or Decimal(0)


def cap(db: Session) -> Decimal:
    from app.modules.system import settings

    return Decimal(str(settings.get(db, "ai.monthly_cap_usd")))


def usage(db: Session) -> dict:
    """Settings and the command center: the month's spending against the cap, with the warning level reached."""
    spent, limit = month_spend(db), cap(db)
    percent = float(spent / limit * 100) if limit > 0 else (100.0 if spent > 0 else 0.0)
    level = next((lv for lv in sorted(WARN_LEVELS, reverse=True) if percent >= lv), None)
    subscription_calls = db.scalar(select(func.count()).select_from(Call).where(
        Call.created_at >= month_start(), Call.subscription.is_(True), Call.status == "ok")) or 0
    return {"spent_usd": str(spent.quantize(Decimal("0.01"))), "cap_usd": str(limit), "percent": round(percent, 1),
            "warning": level, "reached": limit == 0 or spent >= limit, "api_fallback_enabled": limit > 0,
            "subscription_calls": subscription_calls}


def estimate(db: Session, provider: Provider, model: str, chars: int, images: int, max_tokens: int) -> Decimal | None:
    tokens_in = int(Decimal(chars) / CHARS_PER_TOKEN) + images * IMAGE_TOKENS
    return cost(price_of(db, provider.id, model), tokens_in, max_tokens)


# ---- routes ----------------------------------------------------------------------------------------------------------

@dataclass
class Candidate:
    provider: Provider
    model: str


def candidates(db: Session, task: str) -> tuple[list[Candidate], str]:
    route = db.scalar(select(Route).where(Route.task == task))
    if route is None:
        raise AppError("ai_route_missing", "No AI route for this task", {"task": task}, status=409)
    out = []
    for pid, model in ((route.primary_provider_id, route.primary_model), (route.fallback_provider_id, route.fallback_model)):
        provider = db.get(Provider, pid) if pid else None
        if provider is not None:
            out.append(Candidate(provider, model or (provider.models[0] if provider.models else "")))
    return out, route.privacy


def configured(db: Session) -> bool:
    """At least one enabled provider: every AI entry point says how to connect one when there is none."""
    return db.scalar(select(func.count()).select_from(Provider).where(Provider.enabled.is_(True))) > 0


# ---- running a task --------------------------------------------------------------------------------------------------

@dataclass
class Outcome:
    data: Any
    text: str
    call: Call
    attempts: list[Call] = field(default_factory=list)


def _log(db: Session, **values) -> Call:
    row = Call(**values)
    db.add(row)
    db.flush()
    return row


def run(db: Session, task: str, *, text: str, images: list[Attachment] | None = None, schema: dict | None = None,
        prompt_task: str | None = None, prompt_values: dict | None = None, case_id=None, entity_type: str | None = None,
        entity_id: str | None = None, input_desc: dict | None = None, party_ids=(), private_prices=(),
        max_tokens: int = 4096, job_id=None, examples: str = "") -> Outcome:
    images = images or []
    prompt = prompts.load(prompt_task or task)
    cands, privacy = candidates(db, task)
    if case_local_only(db, case_id):
        privacy = "local_only"
    describe = {"characters": len(text), "images": len(images), **(input_desc or {})}
    attempts: list[Call] = []
    last_error: ProviderError | None = None
    previous: Call | None = None
    cap_blocked = False
    usable = [c for c in cands if c.provider.enabled and c.model]
    if not usable:
        raise AppError("ai_not_configured", "No AI provider is set up for this task; connect one in Settings → «هوش مصنوعی»",
                       {"task": task}, status=409)
    for attempt, cand in enumerate(usable, start=1):
        provider = cand.provider
        base = dict(task=task, entity_type=entity_type, entity_id=str(entity_id) if entity_id else None, case_id=case_id,
                    provider_id=provider.id, provider_kind=provider.kind, model=cand.model, prompt_version=prompt.version,
                    input=describe, privacy=privacy, attempt=attempt, fallback_of_id=previous.id if previous else None,
                    job_id=job_id)
        if privacy == "local_only" and not is_local(provider):
            previous = _log(db, **base, status="skipped", error="local_only: cloud provider not allowed")
            attempts.append(previous)
            continue
        if provider.kind in API_KINDS:
            limit = cap(db)
            est = estimate(db, provider, cand.model, len(text) + len(prompt.system), len(images), max_tokens)
            if limit <= 0 or est is None or month_spend(db) + est > limit:
                cap_blocked = True
                previous = _log(db, **base, status="cap_reached",
                                error="monthly cap reached" if limit > 0 else "API fallback disabled (cap 0)")
                attempts.append(previous)
                continue
        redactor = redact.for_context(db, case_id, party_ids, private_prices) if privacy == "cloud_redacted" \
            and not is_local(provider) else redact.Redactor()
        user_text = prompt.render(input=text, examples=examples, **(prompt_values or {}))
        sent = redactor.redact(user_text)
        base["redactions"] = redactor.summary()
        req = Request(task, cand.model, prompt.system, sent, images, schema, max_tokens)
        adapter = adapters.for_provider(provider.kind, provider.base_url, api_key(provider))
        try:
            result, data = _generate_valid(adapter, req, schema)
        except ProviderError as exc:
            previous = _log(db, **base, status="error", error=f"{exc.kind}: {exc}"[:2000])
            attempts.append(previous)
            last_error = exc
            if exc.may_fall_back:
                continue
            break
        except schema_mod.InvalidOutput as exc:
            previous = _log(db, **base, status="invalid_output", error=str(exc)[:2000],
                            tokens_in=getattr(exc, "tokens_in", None), tokens_out=getattr(exc, "tokens_out", None))
            attempts.append(previous)
            last_error = ProviderError("invalid_output", str(exc))
            continue
        price = None if result.subscription else price_of(db, provider.id, cand.model)
        row = _log(db, **base, status="ok", tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                   cost_usd=None if result.subscription else (cost(price, result.tokens_in, result.tokens_out) or Decimal(0)),
                   subscription=result.subscription, duration_ms=result.duration_ms)
        attempts.append(row)
        return Outcome(redactor.restore(data) if data is not None else None, redactor.restore(result.text), row, attempts)
    if cap_blocked and last_error is None:
        raise Conflict("ai_cap_reached", "The monthly AI spending cap is reached; local tasks continue", usage(db))
    if privacy == "local_only" and last_error is None:
        raise AppError("ai_local_only", "This work may run only on a local model; none is set up for this task",
                       {"task": task}, status=409)
    kind = last_error.kind if last_error else "unavailable"
    raise AppError("ai_failed", "The AI task did not succeed", {"task": task, "reason": kind,
                                                                 "attempts": [str(a.id) for a in attempts]}, status=502)


def _generate_valid(adapter, req: Request, schema: dict | None):
    """Generate, parse and validate; on invalid output retry once with the errors appended."""
    result = adapter.generate(req)
    if schema is None:
        return result, None
    try:
        data = result.data if result.data is not None else schema_mod.parse_json(result.text)
        return result, schema_mod.validate(data, schema)
    except schema_mod.InvalidOutput as first:
        retry = Request(req.task, req.model, req.system,
                        req.text + "\n\nYour previous answer was not valid: " + "; ".join(first.errors[:10])
                        + "\nAnswer again with one JSON object that follows the schema exactly.",
                        req.images, req.schema, req.max_tokens)
        again = adapter.generate(retry)
        tokens_in = (result.tokens_in or 0) + (again.tokens_in or 0)
        tokens_out = (result.tokens_out or 0) + (again.tokens_out or 0)
        again.tokens_in, again.tokens_out = tokens_in, tokens_out
        again.duration_ms += result.duration_ms
        try:
            data = again.data if again.data is not None else schema_mod.parse_json(again.text)
            return again, schema_mod.validate(data, schema)
        except schema_mod.InvalidOutput as second:
            second.tokens_in, second.tokens_out = tokens_in, tokens_out
            raise second from None


# ---- providers -------------------------------------------------------------------------------------------------------

def test_connection(db: Session, provider_id: uuid.UUID) -> dict:
    """«Test connection»: a tiny prompt, shown with its latency; the provider's status is saved."""
    from app.core.time import utcnow

    provider = get_provider(db, provider_id)
    model = provider.models[0] if provider.models else ""
    prompt = prompts.load("ping")
    adapter = adapters.for_provider(provider.kind, provider.base_url, api_key(provider))
    status, detail, latency = "ok", None, None
    try:
        if not model and provider.kind != "claude_subscription":
            raise ProviderError("not_configured", "add at least one model")
        result = adapter.generate(Request("ping", model, prompt.system, prompt.render(), [], None, 16))
        latency = result.duration_ms
        detail = (result.text or "").strip()[:60]
        tokens = (result.tokens_in, result.tokens_out)
    except ProviderError as exc:
        status, detail, tokens = "error", f"{exc.kind}: {exc}"[:300], (None, None)
    provider.status, provider.status_detail, provider.last_checked_at, provider.last_latency_ms = status, detail, utcnow(), latency
    _log(db, task="ping", provider_id=provider.id, provider_kind=provider.kind, model=model, prompt_version=prompt.version,
         input={"characters": len(prompt.user)}, privacy="cloud", status="ok" if status == "ok" else "error",
         error=None if status == "ok" else detail, tokens_in=tokens[0], tokens_out=tokens[1], duration_ms=latency,
         subscription=provider.kind == "claude_subscription",
         cost_usd=None if provider.kind == "claude_subscription" else cost(price_of(db, provider.id, model), *tokens))
    db.flush()
    return {"status": status, "detail": detail, "latency_ms": latency}


def get_provider(db: Session, provider_id) -> Provider:
    from app.core.errors import NotFound

    row = db.get(Provider, provider_id)
    if row is None:
        raise NotFound("not_found", "AI provider not found")
    return row


def missing_prices(db: Session, provider: Provider) -> list[str]:
    if provider.kind not in API_KINDS:
        return []
    priced = set(db.scalars(select(Price.model).where(Price.provider_id == provider.id)))
    return [m for m in provider.models if m not in priced]


def purge_log(db: Session) -> int:
    """Retention of the privacy log (setting ``ai.log_retention_days``)."""
    from datetime import timedelta

    from sqlalchemy import text as sql

    from app.core.time import utcnow
    from app.modules.system import settings

    days = settings.get(db, "ai.log_retention_days")
    cutoff = utcnow() - timedelta(days=days)
    db.execute(sql("UPDATE ai.draft SET created_by_call_id = NULL WHERE created_by_call_id IN "
                   "(SELECT id FROM ai.call WHERE created_at < :c)"), {"c": cutoff})
    db.execute(sql("UPDATE ai.call SET fallback_of_id = NULL WHERE fallback_of_id IN "
                   "(SELECT id FROM ai.call WHERE created_at < :c)"), {"c": cutoff})
    return db.execute(sql("DELETE FROM ai.call WHERE created_at < :c"), {"c": cutoff}).rowcount
