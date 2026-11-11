"""Reference data import (v0.9.0): ``python -m app.cli reference-import <dataset> [--file path]``.

Idempotent: rows are matched by their natural key, inserted or updated, rows of the same source missing from a full
file are deactivated, and malformed rows are rejected with a reason. Every run writes ``ref.dataset_import`` with the
report (inserted, updated, deactivated, rejected with reasons). Without ``--file`` the files shipped in
``reference/data`` are used; the official UN/LOCODE and GLEIF ELF files are loaded with ``--file`` when the owner has
them. Nothing is downloaded.
"""
import csv
import gzip
import hashlib
import io
import re
import unicodedata
import zipfile
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.events import service as events
from app.modules.parties import clock
from app.modules.reference.models import Airport, ContainerType, DatasetImport, Incoterm, LegalForm, Location, TransportMode
from app.modules.sourcing.common import jsonable

DATA = Path(__file__).resolve().parent / "data"
SHIPPED = {"locations": "locations_curated.csv", "airports": "airports.csv.gz", "legal_forms": "legal_forms_curated.csv",
           "containers": "container_types.csv", "transport_modes": "transport_modes.csv", "incoterms": "incoterms.csv",
           "units": "units_unece.csv"}
DATASETS = (*SHIPPED, "unlocode", "elf")
CURATED = "boms-curated"


class Report:
    def __init__(self) -> None:
        self.inserted = self.updated = self.deactivated = self.unchanged = 0
        self.rejected: list[dict] = []
        self.notes: dict = {}

    def reject(self, row: int, reason: str) -> None:
        if len(self.rejected) < 200:
            self.rejected.append({"row": row, "reason": reason})
        else:
            self.rejected_more = getattr(self, "rejected_more", 0) + 1

    def as_dict(self) -> dict:
        out = {"inserted": self.inserted, "updated": self.updated, "deactivated": self.deactivated,
               "unchanged": self.unchanged, "rejected": len(self.rejected) + getattr(self, "rejected_more", 0),
               "rejections": self.rejected, **({"notes": self.notes} if self.notes else {})}
        return out


def ascii_name(name: str) -> str:
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip()


def _read_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _upsert(db: Session, model, key: dict, values: dict, report: Report):
    row = db.scalar(select(model).filter_by(**key))
    if row is None:
        row = model(**key, **values)
        db.add(row)
        report.inserted += 1
        return row
    changed = False
    for k, v in values.items():
        if getattr(row, k) != v:
            setattr(row, k, v)
            changed = True
    if changed:
        report.updated += 1
    else:
        report.unchanged += 1
    return row


def _deactivate(db: Session, model, source: str, keep_ids: set, report: Report) -> None:
    for row in db.scalars(select(model).where(model.source == source, model.active.is_(True))):
        if row.id not in keep_ids:
            row.active = False
            report.deactivated += 1


FUNCTION_FLAGS = (("1", "is_port"), ("2", "is_rail"), ("3", "is_road"), ("4", "is_airport"), ("5", "is_postal"),
                  ("6", "is_multimodal"), ("7", "is_fixed"), ("B", "is_border"))
SHORT_FLAGS = {"p": "is_port", "r": "is_rail", "d": "is_road", "a": "is_airport"}


def _flags_from_function(function: str) -> dict:
    return {flag: (len(function) >= i + 1 and function[i] == ch) or (ch == "B" and "B" in function)
            for i, (ch, flag) in enumerate(FUNCTION_FLAGS)}


def _coordinates(text: str) -> tuple[Decimal | None, Decimal | None]:
    """UN/LOCODE «3114N 12129E» -> (31.233333, 121.483333)."""
    m = re.fullmatch(r"\s*(\d{2})(\d{2})([NS])\s+(\d{3})(\d{2})([EW])\s*", text or "")
    if not m:
        return None, None
    lat = (Decimal(m[1]) + Decimal(m[2]) / 60) * (1 if m[3] == "N" else -1)
    lon = (Decimal(m[4]) + Decimal(m[5]) / 60) * (1 if m[6] == "E" else -1)
    return lat.quantize(Decimal("0.000001")), lon.quantize(Decimal("0.000001"))


# ---- datasets -------------------------------------------------------------------------------------------------------------

def _locations_curated(db: Session, text: str, report: Report, release: str) -> None:
    keep: set = set()
    for n, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        code = (r.get("unlocode") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}[A-Z2-9]{3}", code):
            report.reject(n, f"bad UN/LOCODE {code!r}")
            continue
        existing = db.scalar(select(Location).where(Location.unlocode == code))
        if existing is not None and existing.source != CURATED:   # the official row wins; keep only the Persian name
            if existing.name_fa != r["name_fa"]:
                existing.name_fa = r["name_fa"]
                report.updated += 1
            else:
                report.unchanged += 1
            continue
        flags = {flag: ch in (r.get("functions") or "") for ch, flag in SHORT_FLAGS.items()}
        row = _upsert(db, Location, {"unlocode": code}, {
            "country_iso2": code[:2], "code": code[2:], "name": r["name"].strip(), "name_ascii": ascii_name(r["name"]),
            "name_fa": r["name_fa"].strip() or None, "iata": (r.get("iata") or "").strip() or None, "active": True,
            "source": CURATED, "release": release, **flags}, report)
        db.flush()
        keep.add(row.id)
    _deactivate(db, Location, CURATED, keep, report)      # a curated code corrected in a later release (IRCHB -> IRZBR)


def _unlocode(db: Session, text: str, report: Report, release: str) -> None:
    """The official UNECE CSV (columns: Change, Country, Location, Name, NameWoDiacritics, Subdivision, Status,
    Function, Date, IATA, Coordinates, Remarks; no header). Country header rows (no location) are skipped; ``X`` (to
    be removed) rows deactivate."""
    seen: set = set()
    matched, mismatches = 0, []
    curated = _curated_rows()        # from the shipped file, not the table: the same answer on every import
    for n, cols in enumerate(csv.reader(io.StringIO(text)), start=1):
        if len(cols) < 11 or not cols[2].strip() or cols[1].strip() == "Country":      # country rows, a header row
            continue
        change, country, loc = cols[0].strip(), cols[1].strip().upper(), cols[2].strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[A-Z2-9]{3}", loc):
            report.reject(n, f"bad code {country}{loc}")
            continue
        code = country + loc
        existing = db.scalar(select(Location).where(Location.unlocode == code))
        lat, lon = _coordinates(cols[10])
        values = {"country_iso2": country, "code": loc, "name": cols[3].strip(), "name_ascii": cols[4].strip() or ascii_name(cols[3]),
                  "subdivision": cols[5].strip() or None, "functions": cols[7].strip() or None,
                  "iata": cols[9].strip().upper() or None, "latitude": lat, "longitude": lon,
                  "active": change != "X", "verified": True, "source": "unece", "release": release,
                  **_flags_from_function(cols[7].strip())}
        if existing is not None and existing.name_fa:
            values["name_fa"] = existing.name_fa       # the curated Persian name stays
        mine = curated.get(code)
        if mine is not None:
            matched += 1
            mismatches += _curated_mismatches(code, mine, values)
            for flag in SHORT_FLAGS.values():          # a use the curated row records (CNSHA as a port) is kept
                values[flag] = values[flag] or mine[flag]
            values["iata"] = values["iata"] or mine["iata"]
            values["name_fa"] = values.get("name_fa") or mine["name_fa"]
        row = _upsert(db, Location, {"unlocode": code}, values, report)
        seen.add(code)
        db.flush()
        if row.iata:
            for airport in db.scalars(select(Airport).where(Airport.iata == row.iata, Airport.location_id.is_(None))):
                airport.location_id = row.id
    unmatched = [r.unlocode for r in db.scalars(select(Location).where(Location.source == CURATED, Location.active.is_(True)))
                 if r.unlocode not in seen]
    # the official release comes as several files: the counts add up, the unmatched list is what is left at the end
    report.notes["curated_matched"] = report.notes.get("curated_matched", 0) + matched
    if mismatches:
        report.notes["curated_mismatches"] = (report.notes.get("curated_mismatches", []) + mismatches)[:500]
    report.notes.pop("curated_not_in_file", None)
    if unmatched:
        report.notes["curated_not_in_file"] = unmatched[:200]     # reported, not a rejection: they stay unverified


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", ascii_name(name or "").lower()).strip()


def _curated_rows() -> dict[str, dict]:
    """The shipped curated locations by code: name, Persian name, IATA and the function flags."""
    out = {}
    for r in csv.DictReader(io.StringIO(_decode(_read_bytes(DATA / SHIPPED["locations"])))):
        code = (r.get("unlocode") or "").strip().upper()
        out[code] = {"name": r["name"].strip(), "name_fa": r["name_fa"].strip() or None,
                     "iata": (r.get("iata") or "").strip() or None,
                     **{flag: ch in (r.get("functions") or "") for ch, flag in SHORT_FLAGS.items()}}
    return out


def _curated_mismatches(code: str, curated: dict, official: dict) -> list[dict]:
    """Where a curated row disagrees with the official row of the same code. A name is a mismatch only when neither
    contains the other («Hamburg» / «Hamburg Pt» agree; «Turkmenbashi» / «Termez» do not)."""
    out = []
    mine, theirs = _name_key(curated["name"]), _name_key(official["name_ascii"] or official["name"])
    if mine and theirs and mine not in theirs and theirs not in mine:
        out.append({"unlocode": code, "field": "name", "curated": curated["name"], "official": official["name"]})
    extra = [short for short, flag in SHORT_FLAGS.items() if curated[flag] and not official[flag]]
    if extra:
        out.append({"unlocode": code, "field": "functions", "curated": "".join(extra), "official": official["functions"] or ""})
    if curated["iata"] and official["iata"] and curated["iata"] != official["iata"]:
        out.append({"unlocode": code, "field": "iata", "curated": curated["iata"], "official": official["iata"]})
    return out


def _airports(db: Session, text: str, report: Report, release: str) -> None:
    existing = {a.iata: a for a in db.scalars(select(Airport))}
    by_iata = {loc.iata: loc.id for loc in db.scalars(select(Location).where(Location.iata.is_not(None)))}
    seen: set = set()
    for n, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        iata = (r.get("iata_code") or "").strip().upper()
        if not iata or r.get("type") not in ("large_airport", "medium_airport", "small_airport") or iata in seen:
            continue
        if not re.fullmatch(r"[A-Z0-9]{3}", iata):
            report.reject(n, f"bad IATA {iata!r}")
            continue
        seen.add(iata)
        values = {"icao": (r.get("icao_code") or r.get("gps_code") or "").strip() or None, "name": r["name"].strip(),
                  "city": (r.get("municipality") or "").strip() or None, "country_iso2": (r.get("iso_country") or "").strip() or None,
                  "kind": r["type"], "location_id": by_iata.get(iata), "active": True, "source": "ourairports", "release": release}
        row = existing.get(iata)
        if row is None:
            db.add(Airport(iata=iata, **values))
            report.inserted += 1
            continue
        if row.location_id and not values["location_id"]:
            values["location_id"] = row.location_id
        changed = [k for k, v in values.items() if getattr(row, k) != v]
        for k in changed:
            setattr(row, k, values[k])
        if changed:
            report.updated += 1
        else:
            report.unchanged += 1
    for iata, row in existing.items():
        if iata not in seen and row.source == "ourairports" and row.active:
            row.active = False
            report.deactivated += 1


def _legal_forms_curated(db: Session, text: str, report: Report, release: str) -> None:
    for n, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        code = (r.get("code") or "").strip()
        if not code or not re.fullmatch(r"[A-Z]{2}", (r.get("country_iso2") or "").strip()):
            report.reject(n, "code and country are required")
            continue
        _upsert(db, LegalForm, {"code": code}, {
            "country_iso2": r["country_iso2"].strip(), "local_name": r["local_name"].strip(),
            "transliterated": (r.get("transliterated") or "").strip() or None, "name_fa": (r.get("name_fa") or "").strip() or None,
            "abbreviations": [a.strip() for a in (r.get("abbreviations") or "").split("|") if a.strip()],
            "curated": True, "active": True, "source": CURATED, "release": release}, report)


def _elf(db: Session, text: str, report: Report, release: str) -> None:
    """The GLEIF ISO 20275 CSV (header row; columns found by name)."""
    reader = csv.DictReader(io.StringIO(text))
    cols = {name.lower(): name for name in (reader.fieldnames or [])}

    def col(*words: str) -> str | None:
        for low, name in cols.items():
            if all(w in low for w in words):
                return name
        return None

    c_code, c_country = col("elf code"), col("country code")
    c_local, c_trans = col("local name"), col("transliterated name")
    c_abbr, c_status = col("abbreviations local"), col("status")
    if not (c_code and c_country and c_local):
        report.reject(1, "not an ELF code list (missing columns)")
        return
    keep = set()
    for n, r in enumerate(reader, start=2):
        elf = (r.get(c_code) or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{4}", elf):
            report.reject(n, f"bad ELF code {elf!r}")
            continue
        code = f"ELF-{elf}"
        if code in keep:
            continue           # one row per code (the list repeats a code per language)
        row = _upsert(db, LegalForm, {"code": code}, {
            "elf_code": elf, "country_iso2": (r.get(c_country) or "").strip()[:2].upper() or "XX",
            "local_name": (r.get(c_local) or "").strip() or elf, "transliterated": (r.get(c_trans) or "").strip() or None if c_trans else None,
            "abbreviations": [a.strip() for a in re.split(r"[;,]", r.get(c_abbr) or "") if a.strip()] if c_abbr else [],
            "curated": False, "active": (r.get(c_status) or "ACTV").strip().upper() != "INAC" if c_status else True,
            "source": "gleif", "release": release}, report)
        keep.add(code)
        db.flush()
        keep.add(row.id)
    _deactivate(db, LegalForm, "gleif", {k for k in keep if not isinstance(k, str)}, report)


def _simple(model, key: str, convert):
    def run(db: Session, text: str, report: Report, release: str) -> None:
        keep = set()
        for n, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
            try:
                values = convert(r)
            except (KeyError, ValueError, ArithmeticError) as exc:
                report.reject(n, str(exc) or "bad row")
                continue
            row = _upsert(db, model, {key: values.pop(key)}, {**values, "active": True, "source": "standard", "release": release}, report)
            db.flush()
            keep.add(row.id)
        _deactivate(db, model, "standard", keep, report)
    return run


def _bool(v: str) -> bool:
    return v.strip().lower() in ("true", "1", "yes")


_containers = _simple(ContainerType, "code", lambda r: {"code": r["code"].strip(), "description_en": r["description_en"].strip(),
                                                        "description_fa": r["description_fa"].strip(),
                                                        "length_ft": Decimal(r["length_ft"]), "teu": Decimal(r["teu"])})
_modes = _simple(TransportMode, "code", lambda r: {"code": r["code"].strip(), "name_en": r["name_en"].strip(),
                                                   "name_fa": r["name_fa"].strip()})
_incoterms = _simple(Incoterm, "code", lambda r: {"code": r["code"].strip().upper(), "name_en": r["name_en"].strip(),
                                                  "name_fa": r["name_fa"].strip(), "any_mode": _bool(r["any_mode"]),
                                                  "position": int(r["position"]), "version": "2020"})


def _units(db: Session, text: str, report: Report, release: str) -> None:
    """UN/ECE Rec. 20 codes on the existing units; missing trade units are added (owned by the system module, so
    through its model; existing names stay)."""
    from app.modules.system.models import Unit

    for n, r in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        code, unece = r["code"].strip(), r["unece_code"].strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,3}", unece):
            report.reject(n, f"bad UN/ECE code {unece!r}")
            continue
        unit = db.get(Unit, code)
        if unit is None:
            if not r.get("name_en"):
                report.reject(n, f"unknown unit {code!r} without names")
                continue
            db.add(Unit(code=code, name_fa=r["name_fa"].strip(), name_en=r["name_en"].strip(), kind=r["kind"].strip(),
                        base_factor=Decimal(r["base_factor"]), active=True, unece_code=unece))
            report.inserted += 1
        elif unit.unece_code != unece:
            unit.unece_code = unece
            report.updated += 1
        else:
            report.unchanged += 1


RUNNERS = {"locations": _locations_curated, "unlocode": _unlocode, "airports": _airports, "legal_forms": _legal_forms_curated,
           "elf": _elf, "containers": _containers, "transport_modes": _modes, "incoterms": _incoterms, "units": _units}
RELEASES = {"locations": "boms-2026.11", "airports": "ourairports-2026-11-09", "legal_forms": "boms-2026.11",
            "containers": "ISO 6346:2022", "transport_modes": "UNECE Rec 19", "incoterms": "Incoterms 2020",
            "units": "UNECE Rec 20 rev 17"}


def _texts(dataset: str, path: Path | None) -> tuple[list[str], str, str | None]:
    """(texts, source, sha256): a shipped file, a given CSV / .gz, a folder of CSV parts or a zip of them."""
    if path is None:
        if dataset not in SHIPPED:
            raise FileNotFoundError(f"{dataset}: no file is shipped; pass --file with the official CSV")
        path = DATA / SHIPPED[dataset]
        source = "shipped"
    else:
        source = "file"
    parts: list[bytes] = []
    if path.is_dir():
        parts = [p.read_bytes() for p in sorted(path.glob("*.csv"))]
    elif path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            parts = [z.read(n) for n in sorted(z.namelist()) if n.lower().endswith(".csv")]
    else:
        parts = [_read_bytes(path)]
    if not parts:
        raise FileNotFoundError(f"{path}: no CSV found")
    digest = hashlib.sha256(b"".join(parts)).hexdigest()
    return [_decode(p) for p in parts], source, digest


def run(db: Session, dataset: str, path: str | Path | None = None, release: str | None = None,
        source_ev: str = "script", actor: str | None = None) -> dict:
    if dataset not in RUNNERS:
        raise ValueError(f"unknown dataset {dataset!r}; one of {', '.join(DATASETS)}")
    texts, source, digest = _texts(dataset, Path(path) if path else None)
    release = release or RELEASES.get(dataset) or (Path(path).stem if path else None)
    report = Report()
    for text in texts:
        RUNNERS[dataset](db, text, report, release)
    db.flush()
    restored = restore_archived(db)
    out = {"dataset": dataset, "release": release, "source": source, **report.as_dict(), "restored_links": restored}
    db.add(DatasetImport(dataset=dataset, release=release, source=source, file_sha256=digest, report=jsonable(out),
                         imported_at=clock.now()))
    db.flush()
    events.record(db, "reference", None, "import", jsonable({k: v for k, v in out.items() if k != "rejections"}),
                  source_ev, actor=actor)
    return out


def run_shipped(db: Session, source_ev: str = "script") -> dict:
    """Every shipped dataset (installer, update and ``seed``): locations before airports so airports link."""
    return {name: {k: v for k, v in run(db, name, source_ev=source_ev).items() if k != "rejections"}
            for name in ("units", "transport_modes", "incoterms", "containers", "legal_forms", "locations", "airports")}


def restore_archived(db: Session) -> int:
    """References archived by a 0017 downgrade come back once their reference rows exist again."""
    from sqlalchemy import text

    exists = db.execute(text("SELECT to_regclass('sys.downgrade_archive')")).scalar()
    if not exists:
        return 0
    rows = db.execute(text("SELECT id, table_name, row_id, data FROM sys.downgrade_archive "
                           "WHERE migration = '0017' AND restored_at IS NULL")).all()
    done = 0
    targets = {"location": (Location, "unlocode"), "legal_form": (LegalForm, "code")}
    for archive_id, table, row_id, data in rows:
        if table == "ops.shipment_container":
            if data.get("container_type") and db.scalar(select(ContainerType.id).where(ContainerType.code == data["container_type"])) is None:
                continue
            db.execute(text("INSERT INTO ops.shipment_container (shipment_id, number, container_type, seal_no) "
                            "VALUES (:s, :n, :t, :seal) ON CONFLICT DO NOTHING"),
                       {"s": row_id, "n": data["number"], "t": data.get("container_type"), "seal": data.get("seal_no")})
        else:
            column = data["column"]
            model, key = targets["legal_form" if column == "legal_form_id" else "location"]
            ref_id = db.scalar(select(model.id).where(getattr(model, key) == data["key"]))
            if ref_id is None:
                continue
            db.execute(text(f"UPDATE {table} SET {column} = :r WHERE id = :i AND {column} IS NULL"), {"r": ref_id, "i": row_id})
        db.execute(text("UPDATE sys.downgrade_archive SET restored_at = now() WHERE id = :i"), {"i": archive_id})
        done += 1
    return done
