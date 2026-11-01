"""Command center section "Setad" (v0.5.0): what needs the owner's attention on Setad today."""

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.connectors.setad import pipeline as setad_pipeline
from app.core.time import utcnow
from app.modules.listings import convert
from app.modules.listings.service import DEADLINE_SQL, SOURCES, latest_run
from app.modules.system import settings

STALE_RUN_DAYS = 3


def summary(db: Session, today: date) -> dict:
    now = utcnow()
    due = db.execute(text(
        f"""
        SELECT l.id, l.source, l.external_no, l.title, l.organization, s.status, s.inquiry_id, ({DEADLINE_SQL}) AS deadline
        FROM ext.listing l JOIN ext.listing_screening s ON s.listing_id = l.id
        WHERE s.status IN ('starred', 'reviewing') AND ({DEADLINE_SQL}) IS NOT NULL
          AND ({DEADLINE_SQL}) < now() + interval '3 days'
        ORDER BY ({DEADLINE_SQL}) LIMIT 50
        """)).mappings().all()
    keywords = settings.get(db, "setad.warn_keywords") or []
    warned = []
    if keywords:
        for source in SOURCES:
            run = latest_run(db, source)
            if run is None:
                continue
            rows = db.execute(text(
                "SELECT l.id, l.source, l.external_no, l.title, l.organization, l.description FROM ext.listing l "
                "LEFT JOIN ext.listing_screening s ON s.listing_id = l.id "
                "WHERE l.source = :source AND l.first_run_id = :run AND coalesce(s.status, 'new') = 'new' "
                "ORDER BY l.first_seen DESC LIMIT 500"), {"source": source, "run": run.id}).mappings().all()
            for r in rows:
                found = setad_pipeline.find_keywords(f"{r['title']} {r['description']}", keywords)
                if found:
                    warned.append({**{k: r[k] for k in ("id", "source", "external_no", "title", "organization")},
                                   "keywords": found})
    runs = []
    for source in SOURCES:
        run = latest_run(db, source)
        at = (run.finished_at or run.started_at) if run else None
        runs.append({"source": source, "run_id": run.id if run else None, "kind": run.kind if run else None,
                     "status": run.status if run else None, "at": at, "errors": (run.errors or None) if run else None,
                     "stale": at is None or at < now - timedelta(days=STALE_RUN_DAYS)})
    return {
        "due": [{**dict(r), "passed": r["deadline"] < now} for r in due],
        "deadline_changed": convert.changed_deadlines(db),
        "warn_new": warned[:50],
        "runs": runs,
        "stale_days": STALE_RUN_DAYS,
    }
