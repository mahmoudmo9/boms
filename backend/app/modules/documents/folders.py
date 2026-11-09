"""Readable folder view (v0.9.0 section 6.1).

The content-addressed store (``files/ab/cd/<sha256>``) stays the only source of truth and the only thing backed up.
Next to it BOMS keeps a derived, read-only view per case::

    <data folder>/پرونده‌ها/CS-1405-0012 پمپ صنعتی - نفت و گاز پارس/۰۳ پیش‌فاکتور/PI-1405-0005_…pdf

Files are hard links to the store (no extra space, no admin rights); where hard links are impossible (another volume)
the view falls back to copies and Settings says so. ``sync`` makes the view match the database: missing files are
linked, stale files and folders removed. It runs as a job after document link changes, case code / title changes and
deletions, and in full via ``python -m app.cli folders-rebuild``. The view is never backed up or restored."""
import os
import re
import shutil
import stat
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.core.files import store_relpath

# folder key -> (position, Persian name, English name)
FOLDERS = {
    "inquiry": (1, "درخواست", "Inquiry"),
    "sourcing": (2, "استعلام و پیشنهاد تأمین‌کننده", "RFQs and supplier offers"),
    "quote": (3, "پیش‌فاکتور", "Proforma invoices"),
    "contract": (4, "قرارداد", "Contract"),
    "purchase": (5, "سفارش خرید", "Purchase orders"),
    "shipping": (6, "حمل و اسناد", "Shipping and documents"),
    "finance": (7, "مالی", "Finance"),
    "correspondence": (8, "مکاتبات", "Correspondence"),
    "tender": (9, "مناقصه", "Tender"),
}
# what a document is linked to -> folder key (the setting ``folders.mapping`` overrides entries)
DEFAULT_MAPPING = {
    "case": "inquiry", "inquiry": "inquiry", "line_item": "inquiry",
    "rfq": "sourcing", "offer": "sourcing",
    "quote": "quote", "cost_sheet": "quote",
    "sales_order": "contract", "sales_order_change": "contract",
    "purchase_order": "purchase", "purchase_order_change": "purchase", "process_step": "purchase",
    "shipment": "shipping", "shipment_document": "shipping", "shipment_event": "shipping", "receipt": "shipping",
    "delivery": "shipping", "inspection": "shipping", "claim": "shipping",
    "sales_invoice": "finance", "purchase_invoice": "finance", "payment_record": "finance",
    "payment_milestone": "finance", "actual_cost": "finance",
    "interaction": "correspondence",
    "tender": "tender", "tender_proposal": "tender", "envelope_item": "tender", "guarantee": "tender",
    "guarantee_event": "tender", "tender_addendum": "tender", "tender_cost": "tender",
}
ROOT_NAME = "پرونده‌ها"
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# (case_id, kind, document_id, output) for every document of every case. Links first, then the document columns.
_LINKED = {
    "case": "SELECT id AS case_id, id FROM ops.\"case\"",
    "inquiry": "SELECT id AS case_id, inquiry_id AS id FROM ops.\"case\" WHERE inquiry_id IS NOT NULL",
    "line_item": "SELECT case_id, id FROM ops.line_item WHERE case_id IS NOT NULL",
    "rfq": "SELECT case_id, id FROM ops.rfq",
    "offer": "SELECT case_id, id FROM ops.supplier_offer",
    "quote": "SELECT case_id, id FROM ops.quote",
    "cost_sheet": "SELECT case_id, id FROM ops.cost_sheet",
    "sales_order": "SELECT case_id, id FROM ops.sales_order",
    "purchase_order": "SELECT case_id, id FROM ops.purchase_order",
    "shipment": "SELECT case_id, id FROM ops.shipment",
    "claim": "SELECT case_id, id FROM ops.claim",
    "inspection": "SELECT case_id, id FROM ops.inspection",
    "sales_invoice": "SELECT case_id, id FROM ops.sales_invoice",
    "purchase_invoice": "SELECT case_id, id FROM ops.purchase_invoice",
    "actual_cost": "SELECT case_id, id FROM ops.actual_cost",
    "tender": "SELECT case_id, id FROM ops.tender",
    "guarantee": "SELECT case_id, id FROM ops.guarantee",
    "tender_proposal": "SELECT t.case_id, p.id FROM ops.tender_proposal p JOIN ops.tender t ON t.id = p.tender_id",
}
_COLUMNS = [  # (kind, SQL giving case_id, document_id)
    ("sales_order", "SELECT case_id, signed_document_id FROM ops.sales_order"),
    ("sales_order_change", "SELECT o.case_id, c.document_id FROM ops.sales_order_change c JOIN ops.sales_order o ON o.id = c.sales_order_id"),
    ("purchase_order", "SELECT case_id, confirmation_document_id FROM ops.purchase_order"),
    ("purchase_order_change", "SELECT o.case_id, c.document_id FROM ops.purchase_order_change c JOIN ops.purchase_order o ON o.id = c.purchase_order_id"),
    ("process_step", "SELECT p.case_id, s.document_id FROM ops.process_step s JOIN ops.process p ON p.id = s.process_id"),
    ("shipment_document", "SELECT s.case_id, d.document_id FROM ops.shipment_document d JOIN ops.shipment s ON s.id = d.shipment_id"),
    ("shipment_event", "SELECT s.case_id, e.document_id FROM ops.shipment_event e JOIN ops.shipment s ON s.id = e.shipment_id"),
    ("receipt", "SELECT coalesce(s.case_id, o.case_id), r.document_id FROM ops.receipt r "
                "LEFT JOIN ops.shipment s ON s.id = r.shipment_id LEFT JOIN ops.purchase_order o ON o.id = r.purchase_order_id"),
    ("delivery", "SELECT coalesce(s.case_id, o.case_id), d.receipt_document_id FROM ops.delivery d "
                 "LEFT JOIN ops.shipment s ON s.id = d.shipment_id LEFT JOIN ops.sales_order o ON o.id = d.sales_order_id"),
    ("inspection", "SELECT case_id, report_document_id FROM ops.inspection"),
    ("purchase_invoice", "SELECT case_id, document_id FROM ops.purchase_invoice"),
    ("actual_cost", "SELECT case_id, document_id FROM ops.actual_cost"),
    ("payment_milestone", "SELECT case_id, receipt_document_id FROM ops.payment_milestone"),
    ("payment_record", "SELECT DISTINCT coalesce(si.case_id, pi.case_id, ac.case_id), r.document_id FROM ops.payment_record r "
                       "JOIN ops.payment_allocation a ON a.payment_record_id = r.id "
                       "LEFT JOIN ops.sales_invoice si ON si.id = a.sales_invoice_id "
                       "LEFT JOIN ops.purchase_invoice pi ON pi.id = a.purchase_invoice_id "
                       "LEFT JOIN ops.actual_cost ac ON ac.id = a.actual_cost_id"),
    ("guarantee", "SELECT case_id, document_id FROM ops.guarantee"),
    ("guarantee_event", "SELECT g.case_id, e.document_id FROM ops.guarantee_event e JOIN ops.guarantee g ON g.id = e.guarantee_id"),
    ("envelope_item", "SELECT t.case_id, e.document_id FROM ops.envelope_item e JOIN ops.tender t ON t.id = e.tender_id"),
    ("tender_addendum", "SELECT t.case_id, a.document_id FROM ops.tender_addendum a JOIN ops.tender t ON t.id = a.tender_id"),
    ("tender_cost", "SELECT t.case_id, c.document_id FROM ops.tender_cost c JOIN ops.tender t ON t.id = c.tender_id"),
]


def _documents_sql(case_filter: str = "") -> str:
    parts = [f"SELECT x.case_id, '{kind}' AS kind, l.document_id, l.role = 'output' AS output "
             f"FROM core.document_link l JOIN ({sql}) x ON x.id::text = l.entity_id WHERE l.entity_type = '{kind}'"
             for kind, sql in _LINKED.items()]
    parts += [f"SELECT y.case_id, '{kind}', y.document_id, false FROM ({sql}) AS y(case_id, document_id) "
              f"WHERE y.document_id IS NOT NULL" for kind, sql in _COLUMNS]
    return ("SELECT u.case_id, u.kind, u.output, d.id, d.sha256, d.original_filename, d.uploaded_at "
            f"FROM ({' UNION ALL '.join(parts)}) u JOIN core.document d ON d.id = u.document_id "
            f"WHERE u.case_id IS NOT NULL {case_filter} ORDER BY u.case_id, d.uploaded_at, d.id")


# ---- names -----------------------------------------------------------------------------------------------------------

RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_COMPONENT = 120


def sanitize(name: str, max_len: int = MAX_COMPONENT) -> str:
    """A name Windows accepts: no ``<>:"/\\|?*`` or control characters, no reserved device name, no trailing dot or
    space, at most ``max_len`` characters (the extension kept)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 10 or not stem:
        stem, ext = name, ""
    if stem.split(".")[0].upper() in RESERVED:
        stem = "_" + stem
    if len(stem) + len(ext) + (1 if ext else 0) > max_len:
        stem = stem[: max(1, max_len - len(ext) - 1)].rstrip(". ")
    out = f"{stem}.{ext}" if ext else stem
    return out or "_"


def folder_name(key: str) -> str:
    pos, fa, _en = FOLDERS[key]
    return f"{pos:02d}".translate(FA_DIGITS) + " " + fa


def case_folder_name(code: str | None, title: str, party: str | None) -> str:
    label = " - ".join(x for x in (title.strip(), (party or "").strip()) if x)
    return sanitize(f"{code or 'CS'} {label}".strip())


def view_root(db: Session) -> Path:
    from app.modules.system import settings

    custom = settings.get(db, "folders.root")
    return Path(custom) if custom else get_config().data_dir / ROOT_NAME


def mapping(db: Session) -> dict:
    from app.modules.system import settings

    return {**DEFAULT_MAPPING, **(settings.get(db, "folders.mapping") or {})}


def long_path(path: Path) -> str:
    """Windows paths over 260 characters need the ``\\\\?\\`` prefix."""
    s = str(path)
    if sys.platform == "win32" and len(s) > 240 and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(s)
    return s


# ---- desired state ----------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    folders: dict[str, set] = field(default_factory=dict)            # case folder -> sub-folders
    files: dict[tuple[str, str, str], str] = field(default_factory=dict)  # (case folder, sub, file) -> sha256


def plan(db: Session, case_ids: list | None = None) -> Plan:
    out = Plan()
    params: dict = {}
    case_where = ""
    if case_ids is not None:
        case_where = "WHERE c.id = ANY(:ids)"
        params["ids"] = [uuid.UUID(str(i)) for i in case_ids]
    cases = db.execute(text(
        "SELECT c.id, c.code, c.title, coalesce(p.name_fa, p.name_en) AS party, "
        "EXISTS (SELECT 1 FROM ops.tender t WHERE t.case_id = c.id) AS has_tender "
        f"FROM ops.\"case\" c LEFT JOIN core.party p ON p.id = c.party_id {case_where}"), params).all()
    names = {}
    for c in cases:
        name = case_folder_name(c.code, c.title, c.party)
        names[c.id] = name
        out.folders[name] = {folder_name(k) for k in FOLDERS if k != "tender" or c.has_tender}
    if not names:
        return out
    kinds = mapping(db)
    rows = db.execute(text(_documents_sql("AND u.case_id = ANY(:ids)")), {"ids": list(names)}).all()
    for case_id, kind, output, _doc_id, sha, filename, uploaded_at in rows:
        key = kinds.get(kind, "correspondence")
        sub = folder_name(key if key in FOLDERS else "correspondence")
        out.folders[names[case_id]].add(sub)
        base = filename if output else f"{uploaded_at:%Y-%m-%d}_{filename}"
        file = sanitize(base)
        slot = (names[case_id], sub, file)
        if slot in out.files and out.files[slot] != sha:      # same name, different content
            stem, dot, ext = file.rpartition(".")
            file = sanitize(f"{stem or file}_{sha[:8]}{dot}{ext if stem else ''}")
            slot = (names[case_id], sub, file)
        out.files[slot] = sha
    return out


# ---- applying it ------------------------------------------------------------------------------------------------------

def _writable(path) -> None:
    try:
        os.chmod(long_path(Path(path)), stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


class _Remover:
    """Deletes view entries. On Windows the read-only attribute belongs to the file, shared by all its hard links:
    deleting a link may need it cleared, so the store is marked read-only again afterwards."""

    def __init__(self) -> None:
        self.cleared = False
        self.count = 0

    def file(self, path: Path) -> None:
        try:
            os.unlink(long_path(path))
        except PermissionError:
            _writable(path)
            self.cleared = True
            os.unlink(long_path(path))
        self.count += 1

    def tree(self, path: Path) -> None:
        for p in sorted(path.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if p.is_dir() and not p.is_symlink():
                os.rmdir(long_path(p))
            else:
                self.file(p)
        os.rmdir(long_path(path))
        self.count += 1

    def restore_read_only(self) -> None:
        if self.cleared:
            from app.core.files import make_read_only

            for p in get_config().files_dir.rglob("*"):
                if p.is_file():
                    make_read_only(p)


def _place(store: Path, target: Path, prefer_link: bool) -> str:
    """Hard link (or copy) ``store`` at ``target``; returns the mode used."""
    if prefer_link:
        try:
            os.link(long_path(store), long_path(target))
            return "hardlink"
        except OSError:
            pass
    shutil.copyfile(long_path(store), long_path(target))
    os.chmod(long_path(target), stat.S_IREAD)
    return "copy"


def sync(db: Session, case_ids: list | None = None) -> dict:
    """Make the view match the database (all cases, or the given ones). Never touches the store."""
    root = view_root(db)
    root.mkdir(parents=True, exist_ok=True)
    desired = plan(db, case_ids)
    report = {"root": str(root), "cases": len(desired.folders), "linked": 0, "copied": 0, "removed": 0,
              "unchanged": 0, "missing_in_store": 0}
    prefer_link = True
    rm = _Remover()
    # case folders: whole view, or only the given cases' (old names of a renamed case go too)
    if case_ids is None:
        for child in root.iterdir() if root.exists() else []:
            if child.is_dir() and child.name not in desired.folders:
                rm.tree(child)
    else:
        codes = {name.split(" ", 1)[0] for name in desired.folders}
        for child in root.iterdir():
            if child.is_dir() and child.name.split(" ", 1)[0] in codes and child.name not in desired.folders:
                rm.tree(child)
    for case_name, subs in desired.folders.items():
        case_dir = root / case_name
        case_dir.mkdir(exist_ok=True)
        wanted_files = {(s, f): sha for (c, s, f), sha in desired.files.items() if c == case_name}
        for child in case_dir.iterdir():
            if child.is_dir() and child.name not in subs:
                rm.tree(child)
        for sub in subs:
            sub_dir = case_dir / sub
            sub_dir.mkdir(exist_ok=True)
            for existing in sub_dir.iterdir():
                if (sub, existing.name) not in wanted_files:
                    rm.tree(existing) if existing.is_dir() else rm.file(existing)
        for (sub, name), sha in wanted_files.items():
            target = case_dir / sub / name
            store = get_config().files_dir / store_relpath(sha)
            if not store.exists():
                report["missing_in_store"] += 1
                continue
            if target.exists():
                same = os.path.samefile(target, store) or target.stat().st_size == store.stat().st_size
                if same:
                    report["unchanged"] += 1
                    continue
                rm.file(target)
            mode = _place(store, target, prefer_link)
            if mode == "copy":
                prefer_link = False      # another volume: every file of this run will be a copy
            report["linked" if mode == "hardlink" else "copied"] += 1
    rm.restore_read_only()
    report["removed"] = rm.count
    mode = "copy" if report["copied"] and not report["linked"] else "hardlink"
    _save_status(db, {**report, "mode": mode if (report["linked"] or report["copied"]) else _status(db).get("mode", "hardlink")})
    return report


def rebuild_all(db: Session) -> dict:
    """``python -m app.cli folders-rebuild``: the whole view from scratch."""
    root = view_root(db)
    if root.exists():
        rm = _Remover()
        rm.tree(root)
        rm.restore_read_only()
    return sync(db)


def _status(db: Session) -> dict:
    from app.modules.system import settings

    return settings.get_internal(db, "folders.status") or {}


def _save_status(db: Session, report: dict) -> None:
    from app.core.time import utcnow
    from app.modules.system import settings

    settings.set_internal(db, "folders.status", {**report, "at": utcnow().isoformat()})


def status(db: Session) -> dict:
    """Settings: where the view is, hard links or copies, the last sync."""
    from app.modules.system import settings

    return {"enabled": settings.get(db, "folders.enabled"), "root": str(view_root(db)), **_status(db)}


def case_folder(db: Session, case_id) -> Path:
    row = db.execute(text("SELECT c.code, c.title, coalesce(p.name_fa, p.name_en) FROM ops.\"case\" c "
                          "LEFT JOIN core.party p ON p.id = c.party_id WHERE c.id = :i"), {"i": case_id}).one_or_none()
    if row is None:
        from app.core.errors import NotFound

        raise NotFound("not_found", "Case not found")
    return view_root(db) / case_folder_name(*row)


def cases_of_document(db: Session, document_id) -> list:
    rows = db.execute(text(_documents_sql("AND d.id = :d")),
                      {"d": uuid.UUID(str(document_id))}).all()
    return list(dict.fromkeys(r[0] for r in rows))


# ---- the job ----------------------------------------------------------------------------------------------------------

JOB = "folders.sync"


def request_sync(db: Session) -> None:
    """Queue one sync (at most one waits at a time). Called after link, case and deletion changes."""
    from app.modules.system import jobs, settings

    if not settings.get(db, "folders.enabled"):
        return
    queued = db.execute(text("SELECT 1 FROM sys.job WHERE type = :t AND status = 'queued' LIMIT 1"), {"t": JOB}).first()
    if queued is None:
        jobs.enqueue(db, JOB, {}, max_attempts=3, source="system")


def open_in_explorer(path: Path) -> bool:
    """Open Explorer on the owner's PC (Windows only; the backend runs on that PC)."""
    if sys.platform != "win32" or not path.exists():
        return False
    os.startfile(str(path))  # noqa: S606 - a local folder of this app's own data
    return True


# ---- what triggers a sync ---------------------------------------------------------------------------------------------

def _relevant(obj, deleted: bool) -> bool:
    from sqlalchemy import inspect as sa_inspect

    from app.modules.documents.models import DocumentLink
    from app.modules.sourcing.models import Case

    if isinstance(obj, DocumentLink):
        return True
    if isinstance(obj, Case):
        if deleted:
            return True
        state = sa_inspect(obj)
        return state.pending or any(state.attrs[a].history.has_changes() for a in ("title", "code", "party_id"))
    mapper = sa_inspect(type(obj), raiseerr=False)
    if mapper is None:
        return False
    cols = [c.key for c in mapper.column_attrs if c.key.endswith("document_id")]
    if not cols:
        return False
    if deleted:
        return any(getattr(obj, c, None) for c in cols)
    state = sa_inspect(obj)
    return any(state.attrs[c].history.has_changes() for c in cols)


def _after_flush(session: Session, _ctx) -> None:
    if session.info.get("folders_dirty"):
        return
    if any(_relevant(o, False) for o in session.new) or any(_relevant(o, False) for o in session.dirty) \
            or any(_relevant(o, True) for o in session.deleted):
        session.info["folders_dirty"] = True


def _before_commit(session: Session) -> None:
    if session.info.pop("folders_dirty", False):
        try:
            request_sync(session)
        except Exception:   # the view is derived: never block the owner's change because of it
            import logging

            logging.getLogger("boms").exception("folder view: could not queue a sync")


def _after_rollback(session: Session, _transaction=None) -> None:
    session.info.pop("folders_dirty", None)


def install() -> None:
    from sqlalchemy import event

    for name, fn in (("after_flush", _after_flush), ("before_commit", _before_commit),
                     ("after_soft_rollback", _after_rollback)):
        if not event.contains(Session, name, fn):
            event.listen(Session, name, fn)
