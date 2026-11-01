"""PostgreSQL store for the Setad agent: the `Database` interface of SetadSuite's tender worker plus the purchase-call
ingestion. Every method runs in its own short transaction (like SetadSuite's SQLite autocommit), so the UI sees a
long fetch page by page and a cancelled fetch keeps what it already read.

Change tracking (connectors.setad.rows.tracked_changes): a ``listing_change`` row is written only when a tracked
field really changes; volatile list metadata (``recCount``, counters) refreshes ``raw`` silently.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.connectors.setad import pipeline as setad_pipeline
from app.connectors.setad import rows as setad_rows
from app.connectors.setad.parsers import is_favorited
from app.core.time import utcnow
from app.modules.events import service as events
from app.modules.listings.models import AgentStatus, HarvestRun, Listing, ListingChange, ListingDetail, ListingFile

AMOUNT_FIELDS = ("document_price", "guarantee_amount", "estimate")
DATE_FIELDS = ("published_at", "documents_deadline", "proposal_deadline", "inquiry_deadline", "opening_at",
               "edition_date", "response_deadline", "price_valid_until")
WRITABLE = ("external_no", "title", "organization", "province", "city", "category", "goods_group", "service_group",
            "type_name", "need_type", "description", *DATE_FIELDS, "edition_no", *AMOUNT_FIELDS, "detail_url")
# SetadSuite's Persian run statuses -> harvest_run.status
RUN_STATUS = {"کامل": "done", "نیازمند بازبینی": "needs_review", "متوقف‌شده": "cancelled", "خطا": "error"}


def _amount(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.0001"))
    except Exception:
        return None


def _text(value):
    """Change-row text; datetimes in UTC so old (from the database) and new (from the site) read alike."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else str(value)


def _normalize(row: dict) -> dict:
    out = dict(row)
    for f in AMOUNT_FIELDS:
        if f in out:
            out[f] = _amount(out[f])
    return out


def _current(listing: Listing) -> dict:
    return {f: getattr(listing, f) for f in setad_rows.TRACKED_FIELDS if hasattr(listing, f)}


class ListingStore:
    def __init__(self, session_factory: Callable[[], Session], data_dir: Path | None = None):
        self.session = session_factory
        self.data_dir = Path(data_dir) if data_dir else None
        self.run_id: uuid.UUID | None = None
        self.run_kind: str | None = None
        self.counts = {"new": 0, "changed": 0}
        self.on_progress: Callable[[dict], None] | None = None   # agent status writer

    # ------------------------------------------------------------------ runs
    def start_run(self, source: str, kind: str, reported: int | None = None, pages: int | None = None) -> uuid.UUID:
        with self.session() as db:
            run = HarvestRun(source=source, kind=kind, started_at=utcnow(), status="running",
                             reported_count=reported, pages_total=pages)
            db.add(run)
            db.flush()
            events.record(db, "harvest_run", run.id, "start", {"source": source, "kind": kind}, "worker", actor="setad-agent")
            db.commit()
            self.run_id, self.run_kind = run.id, kind
            self.counts = {"new": 0, "changed": 0}
            return run.id

    def progress(self, pages_done: int | None = None, pages_total: int | None = None, rows_seen: int | None = None,
                 duplicates: int | None = None) -> None:
        if self.run_id is None:
            return
        values = {k: v for k, v in (("pages_done", pages_done), ("pages_total", pages_total), ("rows_seen", rows_seen),
                                    ("duplicates", duplicates)) if v is not None}
        values.update(new_count=self.counts["new"], changed_count=self.counts["changed"])
        with self.session() as db:
            db.execute(update(HarvestRun).where(HarvestRun.id == self.run_id).values(**values))
            db.commit()
        if self.on_progress:
            self.on_progress(values)

    def finish_run(self, status: str, errors: str = "") -> None:
        if self.run_id is None:
            return
        with self.session() as db:
            run = db.get(HarvestRun, self.run_id)
            run.status, run.finished_at, run.errors = status, utcnow(), errors or ""
            run.new_count, run.changed_count = self.counts["new"], self.counts["changed"]
            events.record(db, "harvest_run", run.id, "finish",
                          {"status": status, "new": run.new_count, "changed": run.changed_count,
                           "rows_seen": run.rows_seen, "errors": (errors or "")[:500]}, "worker", actor="setad-agent")
            db.commit()
        self.run_id = None

    # SetadSuite tender worker names
    def start_sync(self, reported, pages):
        return self.start_run(setad_rows.SOURCE_TENDER, "full", reported, pages)

    def sync_progress(self, run_id, page, unique, duplicates):
        self.progress(pages_done=page, rows_seen=unique, duplicates=duplicates)

    def finish_sync(self, run_id, status, errors):
        self.finish_run(RUN_STATUS.get(status, "needs_review" if status else "error"), errors)

    def last_sync(self):
        with self.session() as db:
            run = db.scalar(select(HarvestRun).where(HarvestRun.source == setad_rows.SOURCE_TENDER)
                            .order_by(HarvestRun.started_at.desc()).limit(1))
            if run is None:
                return None
            fa = {v: k for k, v in RUN_STATUS.items()}
            return {"id": run.id, "status": fa.get(run.status, run.status), "errors": run.errors}

    def save_sync_issues(self, run_id, kind, items):
        with self.session() as db:
            run = db.get(HarvestRun, run_id)
            if run is not None:
                run.issues = {**(run.issues or {}), kind: [list(map(str, x)) for x in items]}
                db.commit()

    # ------------------------------------------------------------------ upserts
    def _upsert(self, db: Session, rows: list[dict]) -> tuple[int, int, int]:
        """Insert or refresh listing rows of one page; change rows only for tracked fields."""
        if not rows:
            return 0, 0, 0
        source = rows[0]["source"]
        ids = [r["external_id"] for r in rows]
        existing = {x.external_id: x for x in db.scalars(select(Listing).where(Listing.source == source,
                                                                               Listing.external_id.in_(ids)))}
        now = utcnow()
        full = self.run_kind == "full" and self.run_id is not None
        added = updated = unchanged = 0
        for raw_row in rows:
            row = _normalize(raw_row)
            hours = row.pop("response_hours", None)
            listing = existing.get(row["external_id"])
            if listing is None:
                listing = Listing(source=source, external_id=row["external_id"], first_seen=now, last_seen=now,
                                  first_run_id=self.run_id, last_full_run_id=self.run_id if full else None,
                                  raw=row["raw"], content_hash=setad_rows.content_hash(row),
                                  **{k: row[k] for k in WRITABLE if k in row and row[k] is not None})
                if hours is not None:
                    listing.response_deadline = now + timedelta(hours=hours)
                db.add(listing)
                existing[row["external_id"]] = listing
                added += 1
                continue
            diffs = setad_rows.tracked_changes(_current(listing), row)
            for field, old, new in diffs:
                db.add(ListingChange(listing_id=listing.id, run_id=self.run_id, field=field,
                                     old_value=_text(old), new_value=_text(new), at=now))
            for k in WRITABLE:
                if k in row:
                    setattr(listing, k, row[k])
            if hours is not None and not listing.deadline_exact:
                listing.response_deadline = now + timedelta(hours=hours)   # estimate: refreshed silently
            listing.raw = row["raw"]
            listing.content_hash = setad_rows.content_hash(row)
            listing.last_seen = now
            if full:
                listing.last_full_run_id = self.run_id
            if diffs:
                updated += 1
            else:
                unchanged += 1
        db.flush()
        self.counts["new"] += added
        self.counts["changed"] += updated
        return added, updated, unchanged

    def add_tenders(self, raws) -> tuple[int, int, int]:
        rows = []
        for raw in raws:
            try:
                rows.append(setad_rows.tender_row(raw))
            except (ValueError, AttributeError, TypeError):
                continue
        with self.session() as db:
            result = self._upsert(db, rows)
            db.commit()
            return result

    def upsert_needs(self, needs) -> tuple[int, int, int]:
        """Purchase calls of one fetched page (inquiries/db.py Store.upsert_needs)."""
        rows = [setad_rows.need_row(n) for n in needs]
        with self.session() as db:
            result = self._upsert(db, rows)
            db.commit()
            return result

    # ------------------------------------------------------------------ reads used by the worker
    def _by_external(self, db: Session, external_id, source=setad_rows.SOURCE_TENDER) -> Listing | None:
        return db.scalar(select(Listing).where(Listing.source == source, Listing.external_id == str(external_id)))

    def list_tenders(self):
        with self.session() as db:
            return [{"id": x.external_id, "number": x.external_no} for x in
                    db.scalars(select(Listing).where(Listing.source == setad_rows.SOURCE_TENDER))]

    def tender(self, tender_id):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is None:
                return None
            return {"id": x.external_id, "number": x.external_no, "in_my_calls": int(x.in_my_calls),
                    "raw_json": json.dumps(x.raw or {}, ensure_ascii=False), "title": x.title}

    def raw_map(self, ids):
        with self.session() as db:
            return {x.external_id: x.raw for x in db.scalars(select(Listing).where(
                Listing.source == setad_rows.SOURCE_TENDER, Listing.external_id.in_([str(i) for i in ids])))}

    # ------------------------------------------------------------------ «فراخوان‌های من»
    def set_my_calls_from_rows(self, rows):
        pairs = {str(r["id"]): is_favorited(r) for r in rows
                 if isinstance(r, dict) and r.get("id") is not None and "favoriteCount" in r}
        if not pairs:
            return 0
        with self.session() as db:
            for x in db.scalars(select(Listing).where(Listing.source == setad_rows.SOURCE_TENDER,
                                                      Listing.external_id.in_(list(pairs)))):
                x.in_my_calls = pairs[x.external_id]
            db.commit()
        return sum(pairs.values())

    def set_my_calls(self, tender_id, yes=True):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is not None:
                x.in_my_calls = bool(yes)
                if not yes:
                    x.site_state = x.site_state_name = ""
                db.commit()

    def set_my_calls_bulk(self, ids, clear_others=False):
        ids = [str(i) for i in ids]
        with self.session() as db:
            if clear_others:
                db.execute(update(Listing).where(Listing.source == setad_rows.SOURCE_TENDER).values(in_my_calls=False))
            db.execute(update(Listing).where(Listing.source == setad_rows.SOURCE_TENDER,
                                             Listing.external_id.in_(ids)).values(in_my_calls=True))
            db.commit()
        return len(ids)

    def save_site_states(self, states):
        """«فراخوان‌های من»: in_my_calls + the site's own status (a tracked field: changes are recorded)."""
        changes = []
        now = utcnow()
        with self.session() as db:
            rows = {x.external_id: x for x in db.scalars(select(Listing).where(
                Listing.source == setad_rows.SOURCE_TENDER,
                (Listing.in_my_calls.is_(True)) | (Listing.site_state != "") | Listing.external_id.in_(list(states))))}
            prev = {k: (x.site_state, x.site_state_name) for k, x in rows.items() if x.in_my_calls}
            for k, x in rows.items():
                if k not in states and (x.in_my_calls or x.site_state):
                    if x.site_state:
                        db.add(ListingChange(listing_id=x.id, run_id=self.run_id, field="site_state",
                                             old_value=x.site_state, new_value="", at=now))
                    x.in_my_calls, x.site_state, x.site_state_name = False, "", ""
            for k, v in states.items():
                x = rows.get(k)
                if x is None:
                    continue
                new = (v.get("state", ""), v.get("state_name", ""))
                if x.site_state != new[0]:
                    db.add(ListingChange(listing_id=x.id, run_id=self.run_id, field="site_state",
                                         old_value=x.site_state, new_value=new[0], at=now))
                x.in_my_calls, x.site_state, x.site_state_name = True, new[0], new[1]
                for col, key in (("opening_at", "opening"), ("inquiry_deadline", "eval_deadline"),
                                 ("proposal_deadline", "proposal"), ("edition_date", "edition_date")):
                    if v.get(key):
                        value = setad_rows.setad_datetime(v[key], (0, 0) if col in ("opening_at", "edition_date") else (23, 59))
                        if value is not None and getattr(x, col) != value:
                            db.add(ListingChange(listing_id=x.id, run_id=self.run_id, field=col,
                                                 old_value=_text(getattr(x, col)), new_value=_text(value), at=now))
                            setattr(x, col, value)
                if v.get("edition_no") and x.edition_no != str(v["edition_no"]):
                    x.edition_no = str(v["edition_no"])
                old = prev.get(k)
                if old is not None and old != new:
                    changes.append((k, old[1] or old[0], new[1] or new[0]))
            db.commit()
        return changes

    # ------------------------------------------------------------------ meta (learned site request templates)
    def _meta_path(self) -> Path | None:
        return self.data_dir / "learned.json" if self.data_dir else None

    def meta(self, key, default=None):
        path = self._meta_path()
        if path is None or not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8")).get(key, default)
        except (OSError, ValueError):
            return default

    def set_meta(self, key, value):
        path = self._meta_path()
        if path is None:
            return
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        data[key] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def log_action(self, tender_id, action, result, message=""):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is not None:
                events.record(db, "listing", x.id, "site_action",
                              {"action": action, "result": result, "message": (message or "")[:500]}, "worker", actor="setad-agent")
                db.commit()

    # ------------------------------------------------------------------ details
    def save_detail(self, tender_id, text, pairs=None):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is not None:
                self._write_detail(db, x, fields=pairs or [], text=text or "")
                db.commit()

    def _write_detail(self, db: Session, listing: Listing, **values) -> ListingDetail:
        detail = db.get(ListingDetail, listing.id)
        if detail is None:
            detail = ListingDetail(listing_id=listing.id, fetched_at=utcnow())
            db.add(detail)
        for k, v in values.items():
            setattr(detail, k, v)
        detail.fetched_at = utcnow()
        return detail

    def save_need_detail(self, request_id: str, payload: dict) -> None:
        """A purchase call's detail page (engine "detail" event): fields, buyer note, items, attachment names; the
        exact response deadline and the required price validity become listing fields (tracked)."""
        info = payload.get("info") or {}
        with self.session() as db:
            x = self._by_external(db, request_id, setad_rows.SOURCE_PURCHASE)
            if x is None:
                return
            now = utcnow()
            self._write_detail(db, x, fields=[list(p) for p in info.get("fields") or []],
                               buyer_note=info.get("buyer_note") or "", items=info.get("items") or {},
                               text=(payload.get("content") or "")[:9000],
                               info={**info, "attachments": payload.get("attachments"),
                                     "attach_error": payload.get("attach_error") or ""})
            exact = setad_pipeline.exact_deadline(info)
            if exact:
                value = datetime.fromtimestamp(exact).replace(tzinfo=setad_rows.TEHRAN)
                value = setad_rows.setad_datetime(setad_pipeline.detail_field(info, "مهلت ارسال پاسخ")) or value
                if x.deadline_exact and x.response_deadline != value:
                    db.add(ListingChange(listing_id=x.id, run_id=None, field="response_deadline",
                                         old_value=_text(x.response_deadline), new_value=_text(value), at=now))
                x.response_deadline, x.deadline_exact = value, True
            validity = setad_rows.setad_datetime(setad_pipeline.detail_field(info, "حداقل تاریخ اعتبار"))
            if validity is not None:
                if x.price_valid_until is not None and x.price_valid_until != validity:
                    db.add(ListingChange(listing_id=x.id, run_id=None, field="price_valid_until",
                                         old_value=_text(x.price_valid_until), new_value=_text(validity), at=now))
                x.price_valid_until = validity
            city = setad_pipeline.detail_field(info, "شهر محل تحویل")
            if city and not x.city:
                x.city = city
            names = payload.get("attachments")
            if names:
                known = {f.display_name for f in db.scalars(select(ListingFile).where(ListingFile.listing_id == x.id))}
                for i, name in enumerate(names, start=1):
                    if name not in known:
                        db.add(ListingFile(listing_id=x.id, group_key="appendix", group_title="پیوست‌ها",
                                           appendix_id=f"name:{i}", display_name=name, state="pending",
                                           reported_count=len(names)))
            db.commit()

    # ------------------------------------------------------------------ document groups and files (tenders)
    def save_groups(self, tender_id, groups, method=""):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is None:
                return
            detail = self._write_detail(db, x)
            info = dict(detail.info or {})
            known = {str(g["document_type"]): g for g in info.get("groups") or []}
            for g in groups:
                if g.get("document_type"):
                    known[str(g["document_type"])] = {k: g.get(k) for k in ("document_type", "title", "count", "size",
                                                                            "document_id", "opener")} | {"method": method}
            detail.info = {**info, "groups": list(known.values())}
            db.commit()

    def clear_groups(self, tender_id):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            detail = db.get(ListingDetail, x.id) if x else None
            if detail is None:
                return
            keep = {f.group_key for f in db.scalars(select(ListingFile).where(ListingFile.listing_id == x.id))}
            info = dict(detail.info or {})
            info["groups"] = [g for g in info.get("groups") or [] if str(g.get("document_type")) in keep]
            detail.info = info
            db.commit()

    def groups(self, tender_id):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            detail = db.get(ListingDetail, x.id) if x else None
            return list((detail.info or {}).get("groups") or []) if detail else []

    def save_files(self, tender_id, document_type, items):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is None:
                return
            titles = {str(g.get("document_type")): g for g in (self._groups_of(db, x))}
            group = titles.get(str(document_type), {})
            existing = {f.appendix_id: f for f in db.scalars(select(ListingFile).where(
                ListingFile.listing_id == x.id, ListingFile.group_key == str(document_type)))}
            for f in items:
                if not f.get("appendix_id"):
                    continue
                row = existing.get(str(f["appendix_id"]))
                if row is None:
                    row = ListingFile(listing_id=x.id, group_key=str(document_type), appendix_id=str(f["appendix_id"]),
                                      state="pending")
                    db.add(row)
                row.group_title = group.get("title") or str(document_type)
                row.display_name = f.get("display_name") or row.display_name or str(f["appendix_id"])
                row.extension = f.get("extension") or ""
                row.size = f.get("size") or ""
                row.reported_count = group.get("count")
                row.meta = {k: f.get(k) for k in ("comment", "created")}
            db.commit()

    def _groups_of(self, db: Session, listing: Listing) -> list[dict]:
        detail = db.get(ListingDetail, listing.id)
        return list((detail.info or {}).get("groups") or []) if detail else []

    def files(self, tender_id):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is None:
                return []
            groups = {str(g.get("document_type")): g for g in self._groups_of(db, x)}
            return [{"document_type": f.group_key, "appendix_id": f.appendix_id, "display_name": f.display_name,
                     "extension": f.extension, "size": f.size, "local_path": f.local_path or "",
                     "state": f.state, "group_title": f.group_title or f.group_key,
                     "document_id": (groups.get(f.group_key) or {}).get("document_id") or x.external_id}
                    for f in db.scalars(select(ListingFile).where(ListingFile.listing_id == x.id)
                                        .order_by(ListingFile.group_title, ListingFile.display_name))]

    def set_file_result(self, tender_id, doc_type, file_id, path, state, error=""):
        with self.session() as db:
            x = self._by_external(db, tender_id)
            if x is None:
                return
            f = db.scalar(select(ListingFile).where(ListingFile.listing_id == x.id,
                                                   ListingFile.group_key == str(doc_type),
                                                   ListingFile.appendix_id == str(file_id)))
            if f is None:
                return
            ok = bool(path) and state != "ناموفق"
            f.local_path = str(path) if ok else f.local_path
            f.state = "downloaded" if ok else "error"
            f.error = "" if ok else (error or "")[:1000]
            if ok:
                f.sha256 = _sha256(Path(path))
            db.commit()

    # ------------------------------------------------------------------ purchase-call downloads (manifest on disk)
    def record_need_files(self, request_id: str, folder: Path) -> int:
        """After the engine downloaded a need's attachments into `folder`: one listing_file per manifest entry, and
        the site's attachment total from `.download_info.json` (SetadSuite 0.9.19 complete / partial)."""
        from app.connectors.setad.eproc_storage import load_manifest, recorded_attachment_total

        manifest = load_manifest(folder)
        total = recorded_attachment_total(folder)
        with self.session() as db:
            x = self._by_external(db, request_id, setad_rows.SOURCE_PURCHASE)
            if x is None:
                return 0
            rows = {f.appendix_id: f for f in db.scalars(select(ListingFile).where(ListingFile.listing_id == x.id))}
            by_name = {f.display_name: f for f in rows.values() if f.appendix_id.startswith("name:")}
            for file_id, entry in manifest.items():
                row = rows.get(file_id) or by_name.pop(entry.get("original_name", ""), None)
                if row is None:
                    row = ListingFile(listing_id=x.id, group_key="appendix", group_title="پیوست‌ها",
                                      appendix_id=file_id, display_name=entry.get("original_name") or file_id)
                    db.add(row)
                path = folder / entry.get("saved_as", "")
                row.appendix_id = file_id
                row.local_path = str(path)
                row.extension = path.suffix.lstrip(".")
                row.state = "downloaded" if path.is_file() else "missing"
                row.sha256 = _sha256(path) if path.is_file() else None
                row.reported_count = total
            db.commit()
            return len(manifest)


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ---- the agent's status row (written for the agent; the UI polls it) ----------------------------------------------

def write_agent_status(session_factory: Callable[[], Session], **values) -> None:
    with session_factory() as db:
        db.execute(update(AgentStatus).where(AgentStatus.id == 1).values(**values))
        db.commit()


def agent_cancel_requested(session_factory: Callable[[], Session]) -> bool:
    with session_factory() as db:
        row = db.get(AgentStatus, 1)
        return bool(row and row.cancel_requested)


def quick_since(session_factory: Callable[[], Session]) -> str | None:
    """Jalali yyyy/mm/dd = newest announcement date of the current purchase-call list minus 3 days
    (SetadSuite 0.9.6 «به‌روزرسانی سریع»; the list is what was seen since the last full fetch, 0.9.23)."""
    from sqlalchemy import func

    from app.connectors.setad import jalali
    from app.modules.listings.service import list_since

    with session_factory() as db:
        since = list_since(db, setad_rows.SOURCE_PURCHASE)
        q = select(func.max(Listing.published_at)).where(Listing.source == setad_rows.SOURCE_PURCHASE)
        if since is not None:
            q = q.where(Listing.last_seen >= since)
        newest = db.scalar(q)
    if newest is None:
        return None
    return jalali.from_date((newest.astimezone(setad_rows.TEHRAN) - timedelta(days=3)).date())


def listings_by_id(session_factory: Callable[[], Session], ids: list[str]) -> list[Listing]:
    with session_factory() as db:
        rows = [db.get(Listing, uuid.UUID(str(i))) for i in ids]
        for r in rows:
            if r is not None:
                db.expunge(r)
        return [r for r in rows if r is not None]

