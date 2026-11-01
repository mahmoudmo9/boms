"""Listings API: /api/listings (screening workspace) and /api/setad (agent connection, runs, cache, retention)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.web import request_source
from app.modules.listings import service
from app.modules.listings.schemas import BulkIn, CommandIn, ListingFilters, ListingQuery, ScreenIn
from app.modules.sourcing.common import jsonable
from app.modules.system.auth import CurrentUser

Db = Annotated[Session, Depends(get_db)]
router = APIRouter(prefix="/api/listings", tags=["listings"])
setad_router = APIRouter(prefix="/api/setad", tags=["setad"])


@router.post("/query")
def query(body: ListingQuery, _: CurrentUser, db: Db):
    result = service.query(db, body.model_dump())
    db.commit()   # files deleted by hand were marked missing while reading
    return jsonable(result)


@router.post("/facets/{field}")
def facets(field: str, body: ListingFilters, _: CurrentUser, db: Db, q: str | None = None):
    return jsonable(service.facets(db, body.model_dump(), field, q))


@router.get("/{listing_id}")
def detail(listing_id: uuid.UUID, _: CurrentUser, db: Db):
    result = service.detail(db, listing_id)
    db.commit()
    return jsonable(result)


@router.post("/{listing_id}/screen")
def screen(listing_id: uuid.UUID, body: ScreenIn, request: Request, user: CurrentUser, db: Db):
    service.screen(db, listing_id, body.action, body.model_dump(), request_source(request), user.username)
    db.commit()
    return jsonable(service.detail(db, listing_id))


@router.post("/bulk")
def bulk(body: BulkIn, request: Request, user: CurrentUser, db: Db):
    ids = service.bulk_ids(db, body.ids, body.filters.model_dump() if body.filters else None)
    source = request_source(request)
    if body.action == "export_csv":
        return Response(service.export_csv(db, ids), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=setad-listings.csv"})
    if body.action in ("fetch_detail", "download_files"):
        job = service.command(db, body.action, {"listing_ids": [str(i) for i in ids]}, source, user.username)
        db.commit()
        return {"queued": len(ids), "job_id": str(job.id)}
    result = service.bulk_screen(db, ids, body.action, {"reason": body.reason}, source, user.username)
    db.commit()
    return result


@router.get("/files/{file_id}/content")
def file_content(file_id: uuid.UUID, _: CurrentUser, db: Db):
    """Preview (PDF and images open in the browser) / download of a cached attachment."""
    path = service.local_file(db, file_id)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@router.post("/files/{file_id}/open", status_code=204)
def file_open(file_id: uuid.UUID, _: CurrentUser, db: Db, folder: bool = False):
    service.open_in_windows(db, file_id, folder)


@setad_router.get("/agent")
def agent(_: CurrentUser, db: Db):
    return jsonable(service.agent_status(db))


@setad_router.post("/agent/start")
def agent_start(_: CurrentUser, db: Db):
    return service.start_agent(db)


@setad_router.post("/commands", status_code=202)
def command(body: CommandIn, request: Request, user: CurrentUser, db: Db):
    payload = body.model_dump(exclude_none=True, mode="json")
    name = payload.pop("command")
    job = service.command(db, name, payload, request_source(request), user.username)
    db.commit()
    return {"job_id": str(job.id)}


@setad_router.post("/cancel", status_code=204)
def cancel(request: Request, user: CurrentUser, db: Db):
    service.cancel(db, request_source(request), user.username)
    db.commit()


@setad_router.get("/runs/{run_id}")
def run(run_id: uuid.UUID, _: CurrentUser, db: Db):
    return jsonable(service.run_report(db, run_id))


@setad_router.post("/cache/clear")
def clear_cache(request: Request, user: CurrentUser, db: Db):
    result = service.clear_cache(db, request_source(request), user.username)
    db.commit()
    return result


@setad_router.get("/retention")
def retention_preview(_: CurrentUser, db: Db):
    return service.purge_preview(db)


@setad_router.post("/retention/purge")
def retention_purge(request: Request, user: CurrentUser, db: Db):
    result = service.purge(db, request_source(request), user.username)
    db.commit()
    return result


ROUTERS = [router, setad_router]
