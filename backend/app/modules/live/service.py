"""The change feed behind live page updates (v0.10.0 section 6).

The worker, the Setad agent and the server are separate processes, so the feed reads what they wrote: job status
changes (``sys.job``), record changes (``core.event``), Setad file downloads (``ext.listing_file``), harvest runs and
the agent's progress (``ext.agent_status``). ``changes(db, since)`` returns the notices newer than the cursor and a new
cursor. Rows are read with an overlap (``OVERLAP``): a writer's ``now()`` is its transaction start, so a row can
commit a little after a later cursor was handed out. Notices are therefore at least once; each has a stable ``key``
and the browser ignores keys it has already seen. Notices name what changed, never its content.

Each source is read newest first up to ``LIMIT`` rows, so a burst (a bulk action, an import) never hides the latest
changes; when a source had more, ``overflow`` is true and the browser refreshes everything it shows instead of
relying on the notices."""
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

OVERLAP = timedelta(seconds=10)
FIRST_LOOK = timedelta(seconds=5)     # a new client starts from a few seconds back, not from the beginning of time
LIMIT = 300


def _iso(value: datetime) -> str:
    return value.isoformat()


def now(db: Session) -> datetime:
    return db.execute(text("SELECT clock_timestamp()")).scalar_one()


def changes(db: Session, since: datetime | None) -> dict[str, Any]:
    cursor = now(db)
    start = (since - OVERLAP) if since else cursor - FIRST_LOOK
    notices: list[dict] = []
    counts: list[int] = []

    def read(sql: str):
        rows = db.execute(text(sql), {"s": start, "n": LIMIT}).all()
        counts.append(len(rows))
        return rows

    for r in read("SELECT id, type, status, lane, updated_at FROM sys.job WHERE updated_at > :s "
                  "ORDER BY updated_at DESC LIMIT :n"):
        notices.append({"kind": "job", "key": f"job:{r.id}:{r.status}:{_iso(r.updated_at)}", "id": str(r.id), "type": r.type,
                        "status": r.status, "lane": r.lane, "at": _iso(r.updated_at)})
    for r in read("SELECT id, entity_type, entity_id, action, source, occurred_at FROM core.event WHERE occurred_at > :s "
                  "ORDER BY occurred_at DESC, id DESC LIMIT :n"):
        notices.append({"kind": "record", "key": f"event:{r.id}", "entity_type": r.entity_type, "entity_id": r.entity_id,
                        "action": r.action, "source": r.source, "at": _iso(r.occurred_at)})
    for r in read("SELECT listing_id, max(updated_at) AS at, count(*) FILTER (WHERE state = 'downloaded') AS done, "
                  "count(*) AS total FROM ext.listing_file WHERE updated_at > :s GROUP BY listing_id ORDER BY at DESC LIMIT :n"):
        notices.append({"kind": "record", "key": f"files:{r.listing_id}:{_iso(r.at)}", "entity_type": "listing",
                        "entity_id": str(r.listing_id), "action": "files", "at": _iso(r.at)})
    for r in read("SELECT id, status, updated_at FROM ext.harvest_run WHERE updated_at > :s ORDER BY updated_at DESC LIMIT :n"):
        notices.append({"kind": "record", "key": f"harvest:{r.id}:{r.status}:{_iso(r.updated_at)}", "entity_type": "harvest_run",
                        "entity_id": str(r.id), "action": r.status, "at": _iso(r.updated_at)})
    for r in db.execute(text(
            "SELECT command, listing_id, files_done, files_total, pages_done, pages_total, connected, updated_at "
            "FROM ext.agent_status WHERE updated_at > :s LIMIT 1"), {"s": start}):
        notices.append({"kind": "agent", "key": f"agent:{_iso(r.updated_at)}", "command": r.command,
                        "listing_id": str(r.listing_id) if r.listing_id else None, "files_done": r.files_done,
                        "files_total": r.files_total, "pages_done": r.pages_done, "pages_total": r.pages_total,
                        "connected": r.connected, "at": _iso(r.updated_at)})
    notices.sort(key=lambda n: n["at"])
    return {"cursor": _iso(cursor), "notices": notices, "overflow": any(c >= LIMIT for c in counts)}


def parse_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None
