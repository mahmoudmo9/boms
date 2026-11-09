"""``codes.next(kind, context)``: the next code of a kind in the creating transaction, gap-free and never duplicated
(``INSERT … ON CONFLICT DO UPDATE … RETURNING`` holds the sequence row until commit; a rolled-back creation gives its
number back). The sequence runs per rendered prefix (the scope), so a pattern change simply starts its own sequence and
never touches existing codes.

Modules register their coded tables (``register``); a ``before_flush`` listener gives every new registered row its code,
so creation paths need no change. Codes are searchable and ``resolve`` turns a typed code into the record's page."""
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.modules.codes import patterns


@dataclass
class Kind:
    kind: str
    model: type
    column: str
    context: Callable            # (session, obj) -> dict of token values (without yyyy)
    link: Callable               # (session, row) -> URL
    label_key: str


REGISTRY: dict[str, Kind] = {}


def register(kind: str, model, *, column: str = "code", context: Callable | None = None, link: Callable,
             label_key: str | None = None) -> None:
    REGISTRY[kind] = Kind(kind, model, column, context or (lambda _db, _obj: {}), link, label_key or f"codes.kinds.{kind}")


def pattern(db: Session, kind: str) -> str:
    from app.modules.system import settings

    return settings.get(db, f"codes.pattern.{kind}") or patterns.DEFAULTS[kind]


def user_calendar(db: Session) -> str:
    if "codes_calendar" not in db.info:
        db.info["codes_calendar"] = db.execute(text("SELECT calendar FROM sys.app_user ORDER BY created_at LIMIT 1")).scalar() or "jalali"
    return db.info["codes_calendar"]


def year_of(on: date, calendar: str) -> int:
    from app.modules.quotes.numbering import numbering_year

    return numbering_year(on, calendar)


def next(db: Session, kind: str, context: dict | None = None, *, table: str | None = None, column: str | None = None) -> str:
    """The next code; ``context`` may give ``yyyy`` (else the user's calendar year of today), ``country``, ``role``,
    ``hs4``. With ``table`` / ``column`` an existing equal code (after a pattern change) is skipped."""
    from app.modules.parties import clock

    ctx = dict(context or {})
    ctx.setdefault("yyyy", year_of(clock.today(), user_calendar(db)))
    pat = pattern(db, kind)
    scope = patterns.render(pat, ctx)
    for _ in range(1000):
        seq = db.execute(text(
            "INSERT INTO core.code_sequence (kind, scope, last_number) VALUES (:k, :s, 1) "
            "ON CONFLICT (kind, scope) DO UPDATE SET last_number = core.code_sequence.last_number + 1 RETURNING last_number"),
            {"k": kind, "s": scope}).scalar_one()
        code = patterns.render(pat, ctx, seq)
        if table is None or not db.execute(text(f"SELECT 1 FROM {table} WHERE {column} = :c"), {"c": code}).first():
            return code
    raise RuntimeError(f"no free code for {kind}")


def _table_of(model) -> str:
    t = model.__table__
    return f'{t.schema}."{t.name}"' if t.schema else f'"{t.name}"'


def before_flush(session: Session, _context, _instances) -> None:
    if not REGISTRY:
        from app.core.modules import load_hooks

        load_hooks()
    by_model = {k.model: k for k in REGISTRY.values()}
    for obj in list(session.new):
        k = by_model.get(type(obj))
        if k is None or getattr(obj, k.column, None):
            continue
        with session.no_autoflush:
            ctx = k.context(session, obj)
            table = _table_of(k.model)
            setattr(obj, k.column, next(session, k.kind, ctx, table=table, column=k.column))


def install() -> None:
    if not event.contains(Session, "before_flush", before_flush):
        event.listen(Session, "before_flush", before_flush)


def ensure_loaded() -> None:
    from app.core.modules import load_hooks

    load_hooks()
    install()


CODE_RE = re.compile(r"^[A-Za-z]{2,4}(-[A-Za-z0-9]+)+$")


def resolve(db: Session, code: str) -> dict | None:
    """A typed code -> the record (kind, id, link). Every registered kind and the existing numbered documents."""
    ensure_loaded()
    code = (code or "").strip()
    if not CODE_RE.match(code):
        return None
    for k in REGISTRY.values():
        row = db.scalar(select(k.model).where(getattr(k.model, k.column) == code))
        if row is not None:
            return {"kind": k.kind, "id": str(row.id), "code": code, "link": k.link(db, row)}
    return None


def search(db: Session, needle: str, raw: str, limit: int) -> list:
    """The search provider «کد»: exact codes first, then code prefixes, over every registered kind."""
    from app.modules.search.registry import SearchHit

    ensure_loaded()
    q = (raw or "").strip()
    if len(q) < 2 or not re.match(r"^[A-Za-z]", q):
        return []
    hits = []
    for k in REGISTRY.values():
        col = getattr(k.model, k.column)
        for row in db.scalars(select(k.model).where(col.ilike(q.replace("%", "") + "%")).order_by(col).limit(limit)):
            value = getattr(row, k.column)
            hits.append(SearchHit(id=str(row.id), code=value, title=value, subtitle=_subtitle(row), link=k.link(db, row),
                                  score=2.0 if value.casefold() == q.casefold() else 1.0, extra={"kind": k.kind}))
    hits.sort(key=lambda h: (-h.score, h.title))
    return hits[:limit]


def _subtitle(row) -> str | None:
    for attr in ("title", "name_fa", "name_en", "subject", "description", "number", "purpose", "kind"):
        value = getattr(row, attr, None)
        if isinstance(value, str) and value:
            return value
    return None
