"""Reference data API (v0.9.0): Settings → «داده‌های مرجع» (summary, import from a file) and the lists the forms
pick from (locations, containers, Incoterms, transport modes, legal forms). Nothing is fetched from the internet."""
import shutil
import uuid
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AppError
from app.core.web import request_source
from app.modules.reference import importer, service
from app.modules.reference.models import ContainerType, Incoterm, LegalForm, Location, TransportMode
from app.modules.sourcing.common import jsonable
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api/reference", tags=["reference"])
MAX_IMPORT_BYTES = 200 * 1024 * 1024


def location_out(db: Session, loc: Location) -> dict:
    return {"id": str(loc.id), "unlocode": loc.unlocode, "country_iso2": loc.country_iso2, "code": loc.code,
            "name": loc.name, "name_fa": loc.name_fa, "subdivision": loc.subdivision, "iata": loc.iata,
            "is_port": loc.is_port, "is_airport": loc.is_airport, "is_rail": loc.is_rail, "is_road": loc.is_road,
            "verified": loc.verified, "label_fa": service.location_label(loc, "fa"),
            "label_en": service.location_label(loc, "en")}


@router.get("/summary")
def summary(_: CurrentUser, db: Db):
    return {"datasets": service.summary(db), "importable": list(importer.DATASETS)}


# ---- v0.10.1: imports with a preview, as background jobs ----------------------------------------------------------------

@router.post("/imports", status_code=201)
async def start_import(request: Request, user: CurrentUser, db: Db, file: Annotated[UploadFile, File()],
                       dataset: Annotated[str | None, Form()] = None):
    """Upload an official file (UN/LOCODE release zip or parts, GLEIF ELF CSV). BOMS recognises the format and runs a
    preview; nothing changes until ``confirm``."""
    from app.modules.reference import imports

    data = await file.read()
    run = imports.start(db, file.filename or "upload.csv", data, dataset, user.username, request_source(request))
    db.commit()
    return imports.run_out(run)


@router.get("/imports")
def list_imports(_: CurrentUser, db: Db, limit: Annotated[int, Query(le=50)] = 10):
    from app.modules.reference import imports
    from app.modules.reference.models import ImportRun

    rows = db.scalars(select(ImportRun).order_by(ImportRun.created_at.desc()).limit(limit))
    return [imports.run_out(r) for r in rows]


@router.get("/imports/{run_id}")
def get_import(run_id: uuid.UUID, _: CurrentUser, db: Db):
    from app.modules.reference import imports

    return imports.run_out(imports.get(db, run_id))


class ConfirmIn(BaseModel):
    release: Annotated[str | None, Field(max_length=40)] = None


@router.post("/imports/{run_id}/confirm")
def confirm_import(run_id: uuid.UUID, body: ConfirmIn, request: Request, user: CurrentUser, db: Db):
    from app.modules.reference import imports

    run = imports.confirm(db, run_id, body.release, user.username, request_source(request))
    db.commit()
    return imports.run_out(run)


@router.post("/imports/{run_id}/cancel")
def cancel_import(run_id: uuid.UUID, request: Request, user: CurrentUser, db: Db):
    from app.modules.reference import imports

    run = imports.cancel(db, run_id, user.username, request_source(request))
    db.commit()
    return imports.run_out(run)


@router.post("/import")
def import_file(request: Request, user: CurrentUser, db: Db, file: Annotated[UploadFile, File()],
                dataset: Annotated[str, Form()], release: Annotated[str | None, Form(max_length=40)] = None):
    """Load a dataset from a file the owner downloaded (CSV, .gz or a zip of CSV parts)."""
    if dataset not in importer.DATASETS:
        raise AppError("unknown_dataset", "Unknown dataset", {"datasets": list(importer.DATASETS)}, status=422)
    if dataset not in (*importer.OFFICIAL, "airports"):
        # v0.10.1: the curated sets ship with BOMS; an official file uploaded as one was rejected row by row
        raise AppError("curated_dataset", "This dataset ships with BOMS; upload the official file (UN/LOCODE or ELF) instead",
                       {"official": list(importer.OFFICIAL)}, status=422)
    suffix = "".join(Path(file.filename or "data.csv").suffixes[-2:]) or ".csv"
    with tempfile.TemporaryDirectory(prefix="boms-ref-") as tmp:
        path = Path(tmp) / f"upload{suffix}"
        with path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        if path.stat().st_size > MAX_IMPORT_BYTES:
            raise AppError("file_too_large", "File is larger than the import limit", {"max_bytes": MAX_IMPORT_BYTES}, status=413)
        try:
            report = importer.run(db, dataset, path, release, source_ev=request_source(request), actor=user.username)
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            db.rollback()
            raise AppError("reference_file_invalid", str(exc), status=422) from exc
    db.commit()
    report["rejections"] = report.get("rejections", [])[:200]
    return jsonable(report)


@router.get("/locations")
def locations(_: CurrentUser, db: Db, q: str | None = None, country: str | None = None,
              mode: Literal["sea", "air", "rail", "road"] | None = None, limit: Annotated[int, Query(le=100)] = 20):
    stmt = select(Location).where(Location.active.is_(True))
    if country:
        stmt = stmt.where(Location.country_iso2 == country.upper())
    if mode:
        stmt = stmt.where({"sea": Location.is_port, "air": Location.is_airport, "rail": Location.is_rail,
                           "road": Location.is_road}[mode].is_(True))
    if q and q.strip():
        needle = q.strip()
        like = f"%{needle.lower()}%"
        stmt = stmt.where(or_(func.lower(Location.name_ascii).like(like), Location.name_fa.like(f"%{needle}%"),
                              Location.unlocode == needle.upper().replace(" ", ""), Location.code == needle.upper(),
                              Location.iata == needle.upper()))
        exact = or_(Location.unlocode == needle.upper().replace(" ", ""), Location.code == needle.upper(),
                    Location.iata == needle.upper())
        stmt = stmt.order_by(exact.desc(), Location.name_fa.is_(None), Location.verified.desc(), Location.name_ascii)
    else:
        stmt = stmt.order_by(Location.name_fa.is_(None), Location.country_iso2, Location.name_ascii)
    return [location_out(db, loc) for loc in db.scalars(stmt.limit(limit))]


def _rows(db: Session, model, order) -> list[dict]:
    out = []
    for row in db.scalars(select(model).where(model.active.is_(True)).order_by(order)):
        out.append({c.name: getattr(row, c.name) for c in model.__table__.columns
                    if c.name not in ("created_at", "updated_at", "source", "active")})
    return jsonable(out)


@router.get("/containers")
def containers(_: CurrentUser, db: Db):
    return _rows(db, ContainerType, ContainerType.code)


@router.get("/incoterms")
def incoterms(_: CurrentUser, db: Db):
    rows = _rows(db, Incoterm, Incoterm.position)
    for r in rows:
        r["citation_example"] = service.incoterm_citation(r["code"], "Bandar Abbas")
    return rows


@router.get("/transport-modes")
def transport_modes(_: CurrentUser, db: Db):
    return _rows(db, TransportMode, TransportMode.code)


@router.get("/legal-forms")
def legal_forms(_: CurrentUser, db: Db, country: str | None = None, q: str | None = None,
                limit: Annotated[int, Query(le=200)] = 50):
    stmt = select(LegalForm).where(LegalForm.active.is_(True))
    if country:
        stmt = stmt.where(LegalForm.country_iso2 == country.upper())
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(LegalForm.local_name).like(like), LegalForm.name_fa.like(f"%{q.strip()}%"),
                              func.lower(func.coalesce(LegalForm.transliterated, "")).like(like)))
    stmt = stmt.order_by(LegalForm.curated.desc(), LegalForm.country_iso2, LegalForm.local_name).limit(limit)
    return jsonable([{"id": str(r.id), "code": r.code, "elf_code": r.elf_code, "country_iso2": r.country_iso2,
                      "local_name": r.local_name, "name_fa": r.name_fa, "abbreviations": r.abbreviations,
                      "curated": r.curated} for r in db.scalars(stmt)])


ROUTERS = [router]
