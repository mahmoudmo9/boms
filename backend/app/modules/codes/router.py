"""Codes API (v0.9.0): patterns with a live example (Settings → «کدگذاری و نام‌گذاری») and code resolution.
Patterns themselves are saved through the settings API (``codes.pattern.<kind>``)."""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError, NotFound
from app.modules.codes import patterns, service
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api/codes", tags=["codes"])
SAMPLE = {"country": "CN", "role": "SUP", "hs4": "8413"}
RESERVED = ("contract", "letter")


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    pattern: str


def example(db: Session, kind: str, pattern: str) -> dict:
    """The code the next record would get under ``pattern`` (sample country / role / HS for the party and product
    kinds), without taking a number."""
    from app.modules.parties import clock

    ctx = {**SAMPLE, "yyyy": service.year_of(clock.today(), service.user_calendar(db))}
    scope = patterns.render(pattern, ctx)
    last = db.execute(text("SELECT last_number FROM core.code_sequence WHERE kind = :k AND scope = :s"),
                      {"k": kind, "s": scope}).scalar() or 0
    return {"kind": kind, "pattern": pattern, "default": patterns.DEFAULTS[kind], "scope": scope,
            "example": patterns.render(pattern, ctx, last + 1), "reserved": kind in RESERVED}


@router.get("/patterns")
def list_patterns(_: CurrentUser, db: Db):
    return [example(db, kind, service.pattern(db, kind)) for kind in patterns.DEFAULTS]


@router.post("/preview")
def preview(body: PreviewIn, _: CurrentUser, db: Db):
    if body.kind not in patterns.DEFAULTS:
        raise AppError("unknown_code_kind", "Unknown code kind", {"kind": body.kind}, status=422)
    try:
        pattern = patterns.check(body.pattern)
    except ValueError as exc:
        raise AppError("code_pattern_invalid", str(exc), status=422) from exc
    return example(db, body.kind, pattern)


@router.get("/resolve/{code}")
def resolve(code: str, _: CurrentUser, db: Db):
    hit = service.resolve(db, code)
    if hit is None:
        raise NotFound("code_not_found")
    return hit


ROUTERS = [router]
