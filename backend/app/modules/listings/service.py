"""Listings (Setad purchase calls and tenders): screening queries, the owner's decisions, files, retention, and the
commands sent to the Setad agent through the ``setad`` job lane.

The list rule of SetadSuite 0.9.23: the list is everything seen since the start of the last FULL fetch of that
source (a quick fetch adds and refreshes rows but never hides older ones); starred, reviewing and converted listings
are always listed.
"""
from __future__ import annotations

import csv
import io
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.connectors.setad import parsers as setad_parsers
from app.connectors.setad import pipeline as setad_pipeline
from app.connectors.setad.rows import SOURCE_PURCHASE, SOURCE_TENDER
from app.core.config import get_config
from app.core.errors import AppError, Conflict, NotFound
from app.core.text import normalize_fa
from app.core.time import utcnow
from app.modules.events import service as events
from app.modules.listings.models import (AgentStatus, HarvestRun, Listing, ListingChange, ListingDetail, ListingFile,
                                         ListingScreening)
from app.modules.system import jobs, settings
from app.modules.system.models import Job

SOURCES = (SOURCE_PURCHASE, SOURCE_TENDER)
STATUSES = ("new", "starred", "reviewing", "converted", "dismissed")
PAGE_SIZES = (100, 200, 500, 1000)
# the date that matters for screening: the response deadline of a purchase call; for a tender the documents deadline,
# then (once in «فراخوان‌های من») the send deadline - as SetadSuite's lifecycle.classify
DEADLINE_SQL = ("CASE WHEN l.source = 'setad_purchase' THEN l.response_deadline "
                "WHEN l.in_my_calls THEN coalesce(l.proposal_deadline, l.inquiry_deadline, l.documents_deadline) "
                "ELSE l.documents_deadline END")
SORTS = {
    "published": "l.published_at", "deadline": DEADLINE_SQL, "number": "l.external_no", "title": "l.title",
    "organization": "l.organization", "province": "l.province", "category": "l.category",
    "price": "l.document_price", "status": "coalesce(s.status, 'new')", "first_seen": "l.first_seen",
}
COMMANDS = ("connect", "full_fetch", "quick_fetch", "fetch_detail", "download_files", "sync_my_calls", "add_my_call",
            "remove_my_call", "open_payment_page", "set_role", "disconnect", "record_start", "record_stop")
SITE_WRITES = ("add_my_call", "remove_my_call")
AGENT_ALIVE_SECONDS = 20


# ---- folders -----------------------------------------------------------------------------------------------

def connector_dir() -> Path:
    """<data folder>/connectors/setad: browser profile, lock file, learned site templates, diagnostics."""
    return get_config().data_dir / "connectors" / "setad"


def files_dir(db: Session) -> Path:
    """Downloaded attachments (a cache: NOT in the nightly backup; converted listings' files are copied into the
    document store). SetadSuite's layout: purchase <need_no>/..., tender <number>/<category>/..."""
    path = settings.get(db, "setad.files_dir")
    return Path(path) if path else get_config().data_dir / "setad-files"


# ---- reading -----------------------------------------------------------------------------------------------

def get_listing(db: Session, listing_id: uuid.UUID) -> Listing:
    row = db.get(Listing, listing_id)
    if row is None:
        raise NotFound("not_found", "Listing not found")
    return row


def screening_of(db: Session, listing_id: uuid.UUID) -> ListingScreening | None:
    return db.get(ListingScreening, listing_id)


def latest_run(db: Session, source: str, kind: str | None = None) -> HarvestRun | None:
    q = select(HarvestRun).where(HarvestRun.source == source)
    if kind:
        q = q.where(HarvestRun.kind == kind)
    return db.scalar(q.order_by(HarvestRun.started_at.desc()).limit(1))


def list_since(db: Session, source: str) -> datetime | None:
    """Start of the last full fetch of the source (None: no full fetch yet -> everything stored is listed)."""
    run = latest_run(db, source, "full")
    return run.started_at if run else None


def _where(db: Session, p: dict[str, Any], chips: bool) -> tuple[list[str], dict[str, Any]]:
    source = p.get("source") or SOURCE_PURCHASE
    if source not in SOURCES:
        raise AppError("invalid_source", "Unknown listing source", {"source": source}, status=422)
    where = ["l.source = :source"]
    args: dict[str, Any] = {"source": source}
    since = list_since(db, source)
    if since is not None and not p.get("include_old"):
        where.append("(l.last_seen >= :since OR s.status IN ('starred', 'reviewing', 'converted'))")
        args["since"] = since
    if p.get("q"):
        where.append("l.search_norm LIKE :q")
        args["q"] = "%" + (normalize_fa(p["q"]) or "").replace("%", r"\%").replace("_", r"\_") + "%"
    for key, column in (("organizations", "l.organization"), ("provinces", "l.province"), ("categories", "l.category")):
        values = [v for v in p.get(key) or [] if v]
        if values:
            where.append(f"{column} = ANY(:{key})")
            args[key] = values
    if p.get("goods_group"):
        where.append("(l.goods_group = :goods_group OR l.service_group = :goods_group)")
        args["goods_group"] = p["goods_group"]
    if not chips:
        return where, args
    status = p.get("status")
    if status:
        if status not in STATUSES:
            raise AppError("invalid_status", "Unknown screening status", {"status": status}, status=422)
        where.append("coalesce(s.status, 'new') = :status")
        args["status"] = status
    else:
        where.append("coalesce(s.status, 'new') <> 'dismissed'")
    if p.get("new_only"):
        run = latest_run(db, source)
        where.append("l.first_run_id = :new_run")
        args["new_run"] = run.id if run else uuid.UUID(int=0)
    deadline = p.get("deadline")
    if deadline == "open":
        where.append(f"({DEADLINE_SQL}) >= now()")
    elif deadline == "passed":
        where.append(f"({DEADLINE_SQL}) < now()")
    elif deadline == "within":
        where.append(f"({DEADLINE_SQL}) >= now() AND ({DEADLINE_SQL}) < now() + make_interval(days => :days)")
        args["days"] = int(p.get("within_days") or 3)
    if p.get("downloaded"):
        where.append("EXISTS (SELECT 1 FROM ext.listing_file f WHERE f.listing_id = l.id AND f.state = 'downloaded')")
    if p.get("price") == "free":
        where.append("l.document_price = 0")
    elif p.get("price") == "paid":
        where.append("l.document_price > 0")
    if p.get("my_calls"):
        where.append("l.in_my_calls")
    return where, args


def _counts(db: Session, p: dict[str, Any]) -> dict[str, int]:
    """Counts per chip over the whole result of the other filters (search, organisation, place, category)."""
    where, args = _where(db, p, chips=False)
    run = latest_run(db, p.get("source") or SOURCE_PURCHASE)
    args["new_run"] = run.id if run else uuid.UUID(int=0)
    row = db.execute(text(f"""
        SELECT count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed') AS all,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND l.first_run_id = :new_run) AS new,
               count(*) FILTER (WHERE s.status = 'starred') AS starred,
               count(*) FILTER (WHERE s.status = 'reviewing') AS reviewing,
               count(*) FILTER (WHERE s.status = 'converted') AS converted,
               count(*) FILTER (WHERE s.status = 'dismissed') AS dismissed,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND ({DEADLINE_SQL}) >= now()) AS open,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND ({DEADLINE_SQL}) >= now()
                                AND ({DEADLINE_SQL}) < now() + interval '3 days') AS soon,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND ({DEADLINE_SQL}) < now()) AS passed,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND EXISTS (
                   SELECT 1 FROM ext.listing_file f WHERE f.listing_id = l.id AND f.state = 'downloaded')) AS downloaded,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND l.in_my_calls) AS my_calls,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND l.document_price = 0) AS free,
               count(*) FILTER (WHERE coalesce(s.status, 'new') <> 'dismissed' AND l.document_price > 0) AS paid
        FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id
        WHERE {' AND '.join(where)}
    """), args).mappings().one()
    return dict(row)


def query(db: Session, p: dict[str, Any]) -> dict[str, Any]:
    """One page of the screening table, sorted on any column, with counts over the whole result."""
    where, args = _where(db, p, chips=True)
    size = int(p.get("page_size") or 200)
    if size not in PAGE_SIZES:
        raise AppError("invalid_page_size", "Page size must be 100, 200, 500 or 1000", {"allowed": list(PAGE_SIZES)},
                       status=422)
    page = max(1, int(p.get("page") or 1))
    sort = SORTS.get(p.get("sort") or "deadline")
    if sort is None:
        raise AppError("invalid_sort", "Unknown sort column", {"allowed": list(SORTS)}, status=422)
    direction = "DESC" if p.get("dir") == "desc" else "ASC"
    clause = " AND ".join(where)
    total = db.execute(text(f"SELECT count(*) FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id "
                            f"WHERE {clause}"), args).scalar_one()
    rows = db.execute(text(f"""
        SELECT l.id, l.source, l.external_no, l.title, l.organization, l.province, l.city, l.category, l.goods_group,
               l.service_group, l.published_at, ({DEADLINE_SQL}) AS deadline, l.deadline_exact, l.document_price,
               l.in_my_calls, l.site_state, l.site_state_name, l.first_run_id, l.description,
               coalesce(s.status, 'new') AS status, s.inquiry_id, s.dismiss_reason
        FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id
        WHERE {clause}
        ORDER BY {sort} {direction} NULLS LAST, l.id
        LIMIT :limit OFFSET :offset
    """), {**args, "limit": size, "offset": (page - 1) * size}).mappings().all()
    files = _file_counts(db, [r["id"] for r in rows])
    run = latest_run(db, args["source"])
    keywords = settings.get(db, "setad.warn_keywords") or []
    items = []
    for r in rows:
        item = {k: r[k] for k in r.keys() if k not in ("first_run_id", "description")}
        item["is_new"] = run is not None and r["first_run_id"] == run.id
        item["documents"] = files.get(r["id"], {"downloaded": 0, "total": 0})
        item["warn"] = setad_pipeline.find_keywords(f"{r['title']} {r['description']}", keywords) if keywords else []
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": size, "counts": _counts(db, p),
            "since": list_since(db, args["source"])}


def _file_counts(db: Session, ids: list) -> dict:
    """Documents status of the page rows: downloaded / total (the site's count when known), files deleted by hand
    count as missing (disk and database stay in sync)."""
    if not ids:
        return {}
    out: dict = {}
    for f in db.scalars(select(ListingFile).where(ListingFile.listing_id.in_(ids))):
        _sync_file_state(f)
        entry = out.setdefault(f.listing_id, {"downloaded": 0, "files": 0, "reported": 0})
        entry["files"] += 1
        entry["downloaded"] += f.state == "downloaded"
        entry["reported"] = max(entry["reported"], f.reported_count or 0)
    return {k: {"downloaded": v["downloaded"], "total": max(v["files"], v["reported"])} for k, v in out.items()}


def _sync_file_state(f: ListingFile) -> None:
    if f.state == "downloaded" and f.local_path and not Path(f.local_path).is_file():
        f.state = "missing"
    elif f.state == "missing" and f.local_path and Path(f.local_path).is_file():
        f.state = "downloaded"


def facets(db: Session, p: dict[str, Any], field: str, q: str | None = None, limit: int = 300) -> list[dict]:
    """Values of organisation / province / category with counts (multi-select with search, SetadSuite 0.9.21)."""
    column = {"organization": "l.organization", "province": "l.province", "category": "l.category"}.get(field)
    if column is None:
        raise AppError("invalid_facet", "Unknown facet", {"field": field}, status=422)
    where, args = _where(db, {**p, "organizations": [], "provinces": [], "categories": []}, chips=False)
    where.append("coalesce(s.status, 'new') <> 'dismissed'")
    where.append(f"{column} <> ''")
    if q:
        where.append(f"core.normalize_fa({column}) LIKE :fq")
        args["fq"] = "%" + (normalize_fa(q) or "") + "%"
    rows = db.execute(text(f"SELECT {column} AS value, count(*) AS n FROM ext.listing l "
                           f"LEFT JOIN ext.listing_screening s ON s.listing_id = l.id WHERE {' AND '.join(where)} "
                           f"GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT :lim"), {**args, "lim": limit}).mappings().all()
    return [dict(r) for r in rows]


def detail(db: Session, listing_id: uuid.UUID) -> dict[str, Any]:
    """Side panel: fields grouped as SetadSuite does, technical fields apart, items, files, change history."""
    x = get_listing(db, listing_id)
    d = db.get(ListingDetail, x.id)
    s = screening_of(db, x.id)
    files = list(db.scalars(select(ListingFile).where(ListingFile.listing_id == x.id)
                            .order_by(ListingFile.group_title, ListingFile.display_name)))
    for f in files:
        _sync_file_state(f)
    db.flush()
    pairs = (d.fields if d else []) or []
    import json
    fa_fields, technical = setad_parsers.technical_fields(json.dumps(x.raw or {}, ensure_ascii=False), {})
    if x.source == SOURCE_TENDER:
        grouped = setad_parsers.group_pairs([list(p) for p in pairs] or [list(f) for f in fa_fields])
    else:
        grouped = setad_parsers.group_pairs([list(p) for p in pairs])
    changes = db.scalars(select(ListingChange).where(ListingChange.listing_id == x.id)
                         .order_by(ListingChange.at.desc()).limit(200))
    keywords = settings.get(db, "setad.warn_keywords") or []
    scan = " ".join([x.title, x.description, d.buyer_note if d else ""] +
                    [" ".join(r) for r in ((d.items or {}).get("rows") or [] if d else [])])
    return {
        "listing": {c: getattr(x, c) for c in (
            "id", "source", "external_id", "external_no", "title", "organization", "province", "city", "category",
            "goods_group", "service_group", "type_name", "need_type", "description", "published_at",
            "documents_deadline", "proposal_deadline", "inquiry_deadline", "opening_at", "edition_date", "edition_no",
            "response_deadline", "deadline_exact", "price_valid_until", "document_price", "guarantee_amount",
            "estimate", "guarantee_currency", "guarantee_description", "estimate_currency", "site_state", "site_state_name", "in_my_calls", "detail_url", "first_seen", "last_seen")},
        "groups": [{"title": title, "pairs": [list(p) for p in items]} for title, items in grouped],
        "technical": [list(t) for t in technical],
        "detail": None if d is None else {"buyer_note": d.buyer_note, "items": d.items, "fetched_at": d.fetched_at,
                                          "text": d.text, "attachments": (d.info or {}).get("attachments")},
        "files": [_file_out(f) for f in files],
        "changes": [{"field": c.field, "old": c.old_value, "new": c.new_value, "at": c.at} for c in changes],
        "screening": None if s is None else {
            "status": s.status, "dismiss_reason": s.dismiss_reason, "note": s.note, "checklist": s.checklist,
            "inquiry_id": s.inquiry_id, "starred_at": s.starred_at, "converted_at": s.converted_at},
        "warn": setad_pipeline.find_keywords(scan, keywords) if keywords else [],
        # v0.6.0: the owner's and the agent's actions on this listing (History tab)
        "events": [{"action": r.action, "at": r.at, "source": r.source, "actor": r.actor,
                    "data": {k: v for k, v in (r.data or {}).items() if k in EVENT_KEYS}}
                   for r in db.execute(text("SELECT action, occurred_at AS at, source, actor, data FROM core.event WHERE "
                                            "entity_type = 'listing' AND entity_id = :i ORDER BY id DESC LIMIT 100"),
                                       {"i": str(x.id)}).all()],
        "checklist_questions": settings.get(db, "setad.checklist"),
    }


EVENT_KEYS = ("old_status", "new_status", "reason", "result", "counts", "inquiry_id", "number", "action")


def _file_out(f: ListingFile) -> dict:
    return {"id": f.id, "group": f.group_title or f.group_key, "group_key": f.group_key, "appendix_id": f.appendix_id,
            "name": f.display_name, "extension": f.extension, "size": f.size, "state": f.state,
            "sha256": f.sha256, "document_id": f.document_id, "error": f.error or None}


# ---- screening (owner decisions; audited; a refresh never touches this table) -----------------------------

def _screening(db: Session, listing: Listing) -> ListingScreening:
    s = db.get(ListingScreening, listing.id)
    if s is None:
        s = ListingScreening(listing_id=listing.id, status="new", checklist=[])
        db.add(s)
        db.flush()
    return s


def screen(db: Session, listing_id: uuid.UUID, action: str, data: dict, source: str, actor: str | None = None) -> ListingScreening:
    """star / unstar / reviewing / dismiss (reason required) / restore / note / checklist."""
    x = get_listing(db, listing_id)
    s = _screening(db, x)
    old = s.status
    if action in ("star", "unstar", "reviewing", "dismiss", "restore") and s.status == "converted":
        raise Conflict("already_converted", "The listing was converted to an inquiry", {"inquiry_id": str(s.inquiry_id)})
    if action == "star":
        s.status, s.starred_at = "starred", s.starred_at or utcnow()
    elif action == "unstar":
        if s.status == "starred":
            s.status = "new"
    elif action == "reviewing":
        s.status = "reviewing"
    elif action == "dismiss":
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise AppError("reason_required", "Dismissing needs a reason", status=422)
        s.status, s.dismiss_reason = "dismissed", reason
    elif action == "restore":
        s.status, s.dismiss_reason = ("starred" if s.starred_at else "new"), None
    elif action == "note":
        s.note = (data.get("note") or "").strip() or None
    elif action == "checklist":
        s.checklist = [bool(v) for v in data.get("checklist") or []]
    else:
        raise AppError("invalid_action", "Unknown screening action", {"action": action}, status=422)
    db.flush()
    events.record(db, "listing", x.id, f"screen_{action}", {"old_status": old, "new_status": s.status,
                                                            **({"reason": s.dismiss_reason} if action == "dismiss" else {})},
                  source, actor=actor)
    return s


def bulk_ids(db: Session, ids: list[uuid.UUID] | None, filters: dict | None) -> list[uuid.UUID]:
    """Ticked rows, or every row of the current result ("select all results")."""
    if ids:
        return list(ids)
    if filters is None:
        raise AppError("ids_required", "Choose rows or the whole result", status=422)
    where, args = _where(db, filters, chips=True)
    return list(db.execute(text(f"SELECT l.id FROM ext.listing l LEFT JOIN ext.listing_screening s "
                                f"ON s.listing_id = l.id WHERE {' AND '.join(where)}"), args).scalars())


def bulk_screen(db: Session, ids: list[uuid.UUID], action: str, data: dict, source: str, actor: str | None = None) -> dict:
    done, skipped = 0, 0
    for listing_id in ids:
        try:
            screen(db, listing_id, action, data, source, actor)
            done += 1
        except Conflict:
            skipped += 1
    return {"done": done, "skipped": skipped}


CSV_FIELDS = (("external_no", "شماره"), ("title", "عنوان"), ("organization", "دستگاه"), ("province", "استان"),
              ("city", "شهر"), ("category", "طبقه‌بندی"), ("published_at", "تاریخ انتشار"), ("deadline", "مهلت"),
              ("document_price", "مبلغ خرید اسناد"), ("status", "وضعیت بررسی"))


def export_csv(db: Session, ids: list[uuid.UUID]) -> bytes:
    """UTF-8 with BOM, Persian headers; untrusted texts are protected against spreadsheet formulas
    (SetadSuite inquiries/storage.py export_csv)."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([label for _, label in CSV_FIELDS])
    if ids:
        rows = db.execute(text(f"""
            SELECT l.external_no, l.title, l.organization, l.province, l.city, l.category, l.published_at,
                   ({DEADLINE_SQL}) AS deadline, l.document_price, coalesce(s.status, 'new') AS status
            FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id
            WHERE l.id = ANY(:ids) ORDER BY l.published_at DESC NULLS LAST"""), {"ids": list(ids)}).mappings()
        for r in rows:
            values = ["" if r[k] is None else (r[k].isoformat() if isinstance(r[k], datetime) else str(r[k]))
                      for k, _ in CSV_FIELDS]
            writer.writerow(["'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v for v in values])
    return ("﻿" + out.getvalue()).encode("utf-8")


# ---- files: cache, clear, purge ------------------------------------------------------------------------------

def file_of(db: Session, file_id: uuid.UUID) -> ListingFile:
    f = db.get(ListingFile, file_id)
    if f is None:
        raise NotFound("not_found", "File not found")
    _sync_file_state(f)
    return f


def local_file(db: Session, file_id: uuid.UUID) -> Path:
    f = file_of(db, file_id)
    if f.state != "downloaded" or not f.local_path:
        raise AppError("file_missing", "The file is not downloaded (or was deleted on disk)", status=404)
    path = Path(f.local_path)
    root = files_dir(db).resolve()
    if root not in path.resolve().parents:
        raise AppError("file_missing", "The file is outside the Setad files folder", status=404)
    return path


def open_in_windows(db: Session, file_id: uuid.UUID, folder: bool = False) -> None:
    """"Open in Windows": the default app (or Explorer for the folder) on the owner's PC; BOMS runs on that PC."""
    path = local_file(db, file_id)
    target = path.parent if folder else path
    if os.name == "nt":  # pragma: no cover - Windows only
        os.startfile(str(target))  # noqa: S606
        return
    raise AppError("not_supported", "Opening files with the default app works only on Windows", status=400)


def clear_cache(db: Session, source: str, actor: str | None = None) -> dict:
    """Delete only files the connector downloaded (listed in listing_file) plus its manifests; other files in the
    folder stay; empty folders are removed (SetadSuite 0.9.17 «حذف دانلودها»)."""
    removed, folders = 0, set()
    for f in db.scalars(select(ListingFile).where(ListingFile.local_path.is_not(None))):
        path = Path(f.local_path)
        if path.is_file():
            path.unlink()
            removed += 1
        folders.add(path.parent)
        f.local_path, f.state, f.sha256 = None, "pending", None
    for folder in folders:
        for extra in (".download_manifest.json", ".download_info.json"):
            (folder / extra).unlink(missing_ok=True)
    root = files_dir(db)
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        current = folder
        while current != root and root in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    db.flush()
    events.record(db, "listing", "cache", "clear_cache", {"files": removed}, source, actor=actor)
    return {"files": removed}


def _purgeable(db: Session):
    days = settings.get(db, "setad.retention_days")
    return text(f"""
        SELECT l.id FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id
        WHERE coalesce(s.status, 'new') IN ('new', 'dismissed')
          AND ({DEADLINE_SQL}) IS NOT NULL AND ({DEADLINE_SQL}) < now() - make_interval(days => {int(days)})
    """)


def purge_preview(db: Session) -> dict:
    ids = list(db.execute(_purgeable(db)).scalars())
    return {"listings": len(ids), "retention_days": settings.get(db, "setad.retention_days")}


def purge(db: Session, source: str, actor: str | None = None) -> dict:
    """Retention: listings whose deadline passed more than setad.retention_days ago and that were never kept
    (status new or dismissed). Starred, reviewing and converted listings are never purged."""
    ids = list(db.execute(_purgeable(db)).scalars())
    if ids:
        db.execute(text("DELETE FROM ext.listing WHERE id = ANY(:ids)"), {"ids": ids})
    events.record(db, "listing", "retention", "purge", {"listings": len(ids)}, source, actor=actor)
    return {"listings": len(ids)}


# ---- the Setad agent ---------------------------------------------------------------------------------------------

def agent_status(db: Session) -> dict:
    row = db.get(AgentStatus, 1)
    alive = bool(row and row.heartbeat_at and (utcnow() - row.heartbeat_at).total_seconds() < AGENT_ALIVE_SECONDS)
    runs = {src: latest_run(db, src) for src in SOURCES}
    queued = db.execute(text("SELECT count(*) FROM sys.job WHERE lane = 'setad' AND status IN ('queued', 'running')")
                        ).scalar_one()
    return {
        "alive": alive,
        **({c: getattr(row, c) for c in ("pid", "connected", "role", "browser_channel", "command", "pages_done",
                                         "pages_total", "rows_seen", "captcha_waiting", "captcha_message", "message",
                                         "last_error", "cancel_requested", "recording", "heartbeat_at", "started_at",
                                         "job_id", "listing_id", "files_done", "files_total")}
           if row else {}),
        "jobs": setad_jobs(db),
        "connected": bool(row and row.connected and alive),
        "queued": queued,
        "runs": {src: None if r is None else {c: getattr(r, c) for c in (
            "id", "kind", "status", "started_at", "finished_at", "reported_count", "pages_total", "pages_done",
            "rows_seen", "new_count", "changed_count", "duplicates", "errors")} for src, r in runs.items()},
    }


def run_report(db: Session, run_id: uuid.UUID) -> dict:
    run = db.get(HarvestRun, run_id)
    if run is None:
        raise NotFound("not_found", "Fetch run not found")
    return {c: getattr(run, c) for c in ("id", "source", "kind", "status", "started_at", "finished_at",
                                         "reported_count", "pages_total", "pages_done", "rows_seen", "new_count",
                                         "changed_count", "duplicates", "errors", "issues")}


def command(db: Session, name: str, payload: dict, source: str, actor: str | None = None):
    """Queue a command for the agent (lane ``setad``). Site write actions need an explicit per-listing
    confirmation (422 confirmation_required) and are recorded as events."""
    if name not in COMMANDS:
        raise AppError("invalid_command", "Unknown Setad command", {"command": name}, status=422)
    payload = dict(payload or {})
    if name in SITE_WRITES or name == "open_payment_page":
        listing = get_listing(db, uuid.UUID(str(payload.get("listing_id"))))
        if listing.source != SOURCE_TENDER:
            raise AppError("not_a_tender", "Only tenders have «فراخوان‌های من»", status=422)
        if name in SITE_WRITES and payload.get("confirmed") is not True:
            raise AppError("confirmation_required", "Confirm this action on Setad for this listing", status=422)
        payload["external_id"] = listing.external_id
        if name in SITE_WRITES:
            events.record(db, "listing", listing.id, name, {"confirmed": True, "number": listing.external_no},
                          source, actor=actor)
    if name in ("full_fetch", "quick_fetch") and payload.get("source") not in SOURCES:
        raise AppError("invalid_source", "Choose purchase calls or tenders", status=422)
    if name in ("fetch_detail", "download_files"):
        ids = [uuid.UUID(str(i)) for i in payload.get("listing_ids") or []]
        if not ids:
            raise AppError("ids_required", "Choose listings", status=422)
        # v0.6.0: a listing that already has the same command queued or running is not queued again
        active = active_listing_jobs(db, name)
        fresh = [str(i) for i in dict.fromkeys(ids) if str(i) not in active]
        if not fresh:
            return db.get(Job, uuid.UUID(active[str(ids[0])]))
        payload["listing_ids"] = fresh
    if name in ("full_fetch", "quick_fetch"):
        same = db.execute(text("SELECT id FROM sys.job WHERE lane = 'setad' AND type = :t AND status IN "
                               "('queued', 'running') AND payload->>'source' = :s ORDER BY created_at LIMIT 1"),
                          {"t": f"setad.{name}", "s": payload.get("source")}).scalar()
        if same is not None:
            return db.get(Job, same)
    if name in ("connect", "set_role") and payload.get("role") not in (None, "EPROC", "ETEND"):
        raise AppError("invalid_role", "Role is EPROC (supplier) or ETEND (bidder)", status=422)
    row = db.get(AgentStatus, 1)
    if row is not None:
        row.cancel_requested = False
    return jobs.enqueue(db, f"setad.{name}", payload, max_attempts=1, source=source, actor=actor, lane="setad")


def active_listing_jobs(db: Session, name: str | None = None) -> dict[str, str]:
    """listing id -> id of a queued or running fetch_detail / download_files job that covers it."""
    rows = db.execute(text(
        "SELECT id, type, payload FROM sys.job WHERE lane = 'setad' AND status IN ('queued', 'running') "
        "AND type IN ('setad.fetch_detail', 'setad.download_files') ORDER BY created_at")).all()
    out: dict[str, str] = {}
    for job_id, job_type, payload in rows:
        if name and job_type != f"setad.{name}":
            continue
        for listing_id in (payload or {}).get("listing_ids") or []:
            out.setdefault(str(listing_id), str(job_id))
    return out


def setad_jobs(db: Session) -> list[dict]:
    """Queued and running Setad commands with their listings (the workspace shows «در صف دانلود» per row)."""
    rows = db.execute(text(
        "SELECT id, type, status, payload, created_at FROM sys.job WHERE lane = 'setad' AND status IN ('queued', "
        "'running') ORDER BY created_at")).all()
    return [{"id": r.id, "command": r.type.split(".", 1)[1], "status": r.status,
             "listing_ids": (r.payload or {}).get("listing_ids") or [], "created_at": r.created_at} for r in rows]


def job_result(db: Session, job_id: uuid.UUID) -> dict:
    """Status and result of one Setad command (the result is in the job's ``done`` event)."""
    job = db.get(Job, job_id)
    if job is None or job.lane != "setad":
        raise NotFound("not_found", "Command not found")
    result = db.execute(text("SELECT data->'result' FROM core.event WHERE entity_type = 'job' AND entity_id = :i "
                             "AND action = 'done' ORDER BY id DESC LIMIT 1"), {"i": str(job_id)}).scalar()
    return {"id": job.id, "command": job.type.split(".", 1)[1], "status": job.status, "result": result,
            "error": (job.last_error or "").strip().splitlines()[-1][:500] if job.last_error else None,
            "finished_at": job.finished_at}


def agent_log(job_id: str | None = None, lines: int = 200) -> list[str]:
    """The last ``lines`` lines of logs/setad-agent.log (of one command when ``job_id`` is given)."""
    from app.core.config import get_config

    path = get_config().data_dir / "logs" / "setad-agent.log"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        tail = fh.readlines()[-20000:]
    if job_id:
        tail = [line for line in tail if f" {job_id} " in line]
    return [line.rstrip("\n") for line in tail[-lines:]]


def cancel(db: Session, source: str, actor: str | None = None) -> None:
    """Stop the running fetch cleanly (the agent checks between pages and during a captcha wait); queued Setad
    commands are dropped."""
    row = db.get(AgentStatus, 1)
    if row is not None:
        row.cancel_requested = True
    db.execute(text("UPDATE sys.job SET status = 'failed', last_error = 'cancelled', finished_at = now() "
                    "WHERE lane = 'setad' AND status = 'queued'"))
    events.record(db, "setad_agent", "agent", "cancel", {}, source, actor=actor)


def start_agent(db: Session) -> dict:
    """Start the agent process in the owner's desktop session unless one is alive (single instance: the agent
    itself also refuses to start twice). Returns {started, pid}."""
    import subprocess
    import sys

    if agent_status(db)["alive"]:
        return {"started": False}
    backend_dir = Path(__file__).resolve().parents[3]
    kwargs: dict = {"cwd": str(backend_dir), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                    "stderr": subprocess.DEVNULL}
    if os.name == "nt":  # pragma: no cover - Windows: own process group, no console window
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, "-m", "app.connectors.setad.agent"], **kwargs)  # noqa: S603
    return {"started": True, "pid": proc.pid}

