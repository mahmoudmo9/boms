"""Live page updates (v0.10.0 section 6): one server-sent-events stream of job and record-change notices, and the
same feed as a plain request for the polling fallback.

``GET /api/live/stream``: ``text/event-stream``; one ``change`` event per batch (``id`` = the cursor, so the
browser's automatic reconnect resumes with ``Last-Event-ID``), a comment every 15 s to keep the connection open. The
stream ends after ``max_seconds`` (default 5 min) and the browser reconnects: no request lives forever.
``GET /api/live/changes?since=<cursor>``: the polling fallback (every 2 s), same notices.

Both are background requests: they never count as activity for the idle lock."""
import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.core.db import new_session
from app.modules.live import service
from app.modules.system.auth import CurrentUser, Db

router = APIRouter(prefix="/api/live", tags=["live"])
TICK = 1.0
KEEPALIVE = 15.0


def _read(since):
    db = new_session()
    try:
        return service.changes(db, since)
    finally:
        db.close()


@router.get("/changes")
def changes(_: CurrentUser, db: Db, since: Annotated[str | None, Query(max_length=64)] = None):
    return service.changes(db, service.parse_cursor(since))


@router.get("/stream")
async def stream(request: Request, _: CurrentUser, since: Annotated[str | None, Query(max_length=64)] = None,
                 max_seconds: Annotated[float, Query(ge=0.5, le=600)] = 300, tick: Annotated[float, Query(ge=0.05, le=5)] = TICK):
    cursor = service.parse_cursor(request.headers.get("last-event-id") or since)

    async def events():
        nonlocal cursor
        loop = asyncio.get_running_loop()
        end = loop.time() + max_seconds
        quiet_since = loop.time()
        yield "retry: 2000\n\n"
        while loop.time() < end:
            if await request.is_disconnected():
                return
            out = await run_in_threadpool(_read, cursor)
            cursor = service.parse_cursor(out["cursor"])
            if out["notices"]:
                yield f"id: {out['cursor']}\nevent: change\ndata: {json.dumps(out, ensure_ascii=False)}\n\n"
                quiet_since = loop.time()
            elif loop.time() - quiet_since >= KEEPALIVE:
                yield f": keepalive\nid: {out['cursor']}\n\n"
                quiet_since = loop.time()
            await asyncio.sleep(tick)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


ROUTERS = [router]
