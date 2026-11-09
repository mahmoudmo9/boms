"""Reference data services (v0.9.0): display rules (the code next to the name), the Incoterms® 2020 citation, route
labels, the ISO 6346 container check digit."""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound
from app.modules.reference.models import Airport, ContainerType, Incoterm, LegalForm, Location

# ISO 6346: letter values skip multiples of 11 (A=10, B=12 ... K=21, L=23 ... U=32, V=34 ...)
_LETTERS = {}
_v = 10
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _LETTERS[_c] = _v
    _v += 1


def container_check_digit(prefix10: str) -> int:
    """ISO 6346 check digit of the owner code + category + serial (10 characters)."""
    total = sum((_LETTERS[ch] if ch.isalpha() else int(ch)) * (2 ** i) for i, ch in enumerate(prefix10.upper()))
    return total % 11 % 10


def container_number_valid(number: str) -> bool:
    n = re.sub(r"[\s-]", "", (number or "").upper())
    return bool(re.fullmatch(r"[A-Z]{3}[UJZ][0-9]{7}", n)) and container_check_digit(n[:10]) == int(n[10])


def normalize_container(number: str) -> str:
    n = re.sub(r"[\s-]", "", (number or "").upper())
    if not container_number_valid(n):
        raise AppError("container_number_invalid", "Not a valid ISO 6346 container number (owner code, category, serial, check digit)",
                       {"number": number}, status=422)
    return n


def get_location(db: Session, location_id: uuid.UUID) -> Location:
    row = db.get(Location, location_id)
    if row is None:
        raise NotFound("not_found", "Location not found")
    return row


def location_label(loc: Location | None, lang: str, full: bool = False) -> str:
    """«شانگهای SHA» / "Shanghai SHA"; ``full`` gives the whole UN/LOCODE (CNSHA)."""
    if loc is None:
        return ""
    name = (loc.name_fa or loc.name) if lang == "fa" else loc.name
    return f"{name} {loc.unlocode if full else loc.code}"


def airport_code(db: Session, loc: Location | None) -> str | None:
    if loc is None:
        return None
    if loc.iata:
        return loc.iata
    return db.scalar(select(Airport.iata).where(Airport.location_id == loc.id).limit(1))


def route_label(db: Session, origin: Location | None, destination: Location | None, mode: str | None, lang: str) -> str:
    """Sea / road / rail: «شانگهای SHA ← بوشهر BUZ» (fa reads right to left) or "Shanghai SHA → Bushehr BUZ";
    air: by IATA code, «PVG ← BUZ» / "PVG → BUZ"."""
    arrow = "←" if lang == "fa" else "→"
    if mode == "air":
        a, b = airport_code(db, origin), airport_code(db, destination)
        return f"{a or location_label(origin, lang)} {arrow} {b or location_label(destination, lang)}"
    return f"{location_label(origin, lang)} {arrow} {location_label(destination, lang)}"


def incoterm_citation(code: str | None, place: str | None, lang: str = "en") -> str:
    """"CFR Bandar Abbas (Incoterms® 2020)"."""
    if not code:
        return ""
    return f"{code} {place or ''}".strip() + " (Incoterms® 2020)"


def incoterm_text(db: Session, code: str | None, place: str | None, location_id, lang: str = "en") -> str:
    """The Incoterm of an output in the citation format; the place falls back to the chosen UN/LOCODE location."""
    if not place and location_id:
        loc = db.get(Location, location_id)
        if loc is not None:
            place = (loc.name_fa or loc.name) if lang == "fa" else loc.name
    return incoterm_citation(code, place, lang) if code else (place or "")


def unit_label_en(name: str, unece_code: str | None) -> str:
    """English outputs show the UN/ECE Rec. 20 code next to the unit: "piece (H87)"."""
    return f"{name} ({unece_code})" if name and unece_code and unece_code.casefold() != name.casefold() else name


def legal_form_words(db: Session) -> list[str]:
    """Every legal-form name and abbreviation, longest first, for the duplicate check (names compared without them)."""
    words = set()
    for row in db.scalars(select(LegalForm).where(LegalForm.active.is_(True))):
        words.update(a for a in row.abbreviations if a)
        if row.name_fa:
            words.add(row.name_fa)
        words.add(row.local_name)
    return sorted((w for w in words if len(w) >= 2), key=len, reverse=True)


def strip_legal_form(name: str, words: list[str]) -> str:
    """"Shanghai Valve Co., Ltd." -> "Shanghai Valve"; «شرکت فولاد سهامی خاص» -> «فولاد»."""
    text = f" {name or ''} "
    for w in words:
        text = re.sub(rf"(?i)(?<![\w]){re.escape(w)}(?![\w])", " ", text)
    text = re.sub(r"(?i)(?<![\w])(شرکت|company|co)(?![\w])\.?", " ", text)
    return re.sub(r"[\s.,()\-]+", " ", text).strip()


def summary(db: Session) -> list[dict]:
    """Settings → «داده‌های مرجع»: per dataset the rows, active rows and the last import."""
    from sqlalchemy import func

    from app.modules.reference.models import DatasetImport, TransportMode
    from app.modules.sourcing.common import jsonable
    from app.modules.system.models import Unit

    out = []
    for name, model in (("locations", Location), ("airports", Airport), ("legal_forms", LegalForm),
                        ("containers", ContainerType), ("transport_modes", TransportMode), ("incoterms", Incoterm)):
        total, active = db.execute(select(func.count(), func.count().filter(model.active.is_(True))).select_from(model)).one()
        datasets = {"locations": ("locations", "unlocode"), "legal_forms": ("legal_forms", "elf")}.get(name, (name,))
        last = db.scalar(select(DatasetImport).where(DatasetImport.dataset.in_(datasets)).order_by(DatasetImport.imported_at.desc()).limit(1))
        out.append({"dataset": name, "rows": total, "active": active,
                    "last_import": None if last is None else {"dataset": last.dataset, "release": last.release, "at": last.imported_at,
                                                              "report": {k: v for k, v in last.report.items() if k != "rejections"}}})
    units = db.execute(select(func.count(), func.count(Unit.unece_code)).select_from(Unit)).one()
    out.append({"dataset": "units", "rows": units[0], "active": units[1], "last_import": None})
    out[0]["verified"] = db.scalar(select(func.count()).select_from(Location).where(Location.verified.is_(True)))
    return jsonable(out)
