"""Reference import of the official files (v0.10.1 section 0.2): UN/LOCODE and GLEIF ELF.

The owner uploads the file; BOMS recognises the format from its content, shows a preview (dry run: rows to insert,
update, deactivate and reject, with the reasons grouped by count and the first examples) and changes nothing until the
owner confirms. Both the preview and the import run as background jobs (``reference.import``) with progress in
``ref.import_run`` (rows read, stage), which the event stream carries to the page, and a «لغو» that is checked
between stages and every few thousand rows.

The work is set-based: rows are parsed and validated in Python, loaded into a temporary staging table with PostgreSQL
``COPY``, and merged into the target table with one ``INSERT … ON CONFLICT`` in the same transaction. A cancel, a
failure or a closed browser leaves the data exactly as it was (the transaction is rolled back).

UN/LOCODE: the official CSV release is a zip with ``CodeListPart1.csv`` … ``CodeListPart3.csv`` and
``SubdivisionCodes.csv`` (no header; columns Change, Country, Location, Name, NameWoDiacritics, Subdivision, Status,
Function, Date, IATA, Coordinates, Remarks). Rows missing from the file are deactivated only when all three parts were
imported; a single part is upsert-only, with a warning. The encoding is found by validation (UTF-8, then Windows-1252,
then ISO-8859-1) and reported.

ELF (ISO 20275): comma-delimited, every field quoted, may start with a BOM, 16 columns found by their normalised
header name. One code has a row per language: they are grouped into one legal form with its names per language.
``8888`` and ``9999`` have no country and are kept as special codes; ``INAC`` rows are imported inactive.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import time
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.reference import importer
from app.modules.reference.importer import CURATED, SHORT_FLAGS, ascii_name

BATCH = 5000
EXAMPLES = 20
SPECIAL_ELF = {"8888": "Entity legal form not yet allocated an ELF code (8888)",
               "9999": "Other entity legal form without an ELF code (9999)"}


class Cancelled(Exception):
    """The owner pressed «لغو»: the transaction is rolled back and nothing changes."""


# ---- reading the file ---------------------------------------------------------------------------------------------------

def decode(data: bytes) -> tuple[str, str]:
    """Text and the encoding it was read with: UTF-8 when the bytes are valid UTF-8, else Windows-1252, else
    ISO-8859-1 (which accepts any byte)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8"), "utf-8 (BOM)"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "windows-1252"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "iso-8859-1"


def file_parts(name: str, data: bytes) -> dict[str, bytes]:
    """{part name: bytes}: the CSV files of a zip, a ``.gz`` or a single CSV."""
    if name.lower().endswith(".zip") or data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return {Path(n).name: z.read(n) for n in sorted(z.namelist())
                    if n.lower().endswith((".csv", ".txt")) and not n.endswith("/")}
    if name.lower().endswith(".gz") or data[:2] == b"\x1f\x8b":
        return {Path(name).name.removesuffix(".gz"): gzip.decompress(data)}
    return {Path(name).name: data}


def release_from_name(name: str) -> str | None:
    """``loc251csv.zip`` → ``2025-1``; ``2026-02-19-elf-code-list-v1.6.csv`` → ``1.6``."""
    base = Path(name).name.lower()
    m = re.match(r"loc(\d{2})(\d)csv", base)
    if m:
        return f"20{m[1]}-{m[2]}"
    m = re.search(r"-v(\d+(?:\.\d+)+)\.csv", base)
    if m:
        return m[1]
    return None


def norm_header(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("﻿", "").strip().strip('"').lower())


ELF_COLUMNS = {
    "code": "elf code", "country_name": "country of formation", "country": "country code (iso 3166-1)",
    "local_name": "entity legal form name local name", "language": "language", "language_code": "language code (iso 639-1)",
    "transliterated": "entity legal form name transliterated name (per iso 01-140-10)",
    "abbr_local": "abbreviations local language", "abbr_trans": "abbreviations transliterated",
    "status": "elf status actv/inac"}
ELF_REQUIRED = {"code": "ELF Code", "country": "Country Code (ISO 3166-1)", "local_name": "Entity Legal Form name Local name"}


def detect(parts: dict[str, bytes]) -> str | None:
    """The dataset a file holds, from its content: ``elf`` (its header) or ``unlocode`` (the code-list columns)."""
    for name, data in parts.items():
        head, _ = decode(data[:4096])
        first = head.splitlines()[0] if head.splitlines() else ""
        if "elf code" in norm_header(first):
            return "elf"
        if re.search(r"(?i)codelistpart\d", name) or re.search(r"(?i)subdivisioncodes", name):
            return "unlocode"
        try:
            cols = next(csv.reader(io.StringIO(first)))
        except StopIteration:
            continue
        if len(cols) >= 11 and re.fullmatch(r"[A-Z]{2}", cols[1].strip() or "") is not None:
            return "unlocode"
    return None


# ---- parsed rows --------------------------------------------------------------------------------------------------------

@dataclass
class Parsed:
    dataset: str
    rows: list[dict] = field(default_factory=list)
    rejected: Counter = field(default_factory=Counter)
    examples: list[dict] = field(default_factory=list)
    encodings: dict[str, str] = field(default_factory=dict)
    parts: list[str] = field(default_factory=list)
    complete: bool = True
    warnings: list[str] = field(default_factory=list)
    notes: dict = field(default_factory=dict)
    read: int = 0

    def reject(self, row: int, part: str, reason: str) -> None:
        self.rejected[reason] += 1
        if len(self.examples) < EXAMPLES:
            self.examples.append({"part": part, "row": row, "reason": reason})


Progress = Callable[[str, int, int | None], None]


def _unlocode(parts: dict[str, bytes], progress: Progress) -> Parsed:
    out = Parsed("unlocode")
    code_parts = {n: d for n, d in parts.items() if not re.search(r"(?i)subdivisioncodes", n)}
    numbers = {int(m[1]) for n in code_parts if (m := re.search(r"(?i)codelistpart(\d)", n))}
    out.complete = {1, 2, 3} <= numbers
    if not out.complete:
        out.warnings.append("partial_release")
    seen: set[str] = set()
    for name, data in parts.items():
        text_, enc = decode(data)
        out.encodings[name] = enc
        out.parts.append(name)
        if re.search(r"(?i)subdivisioncodes", name):
            out.notes["subdivisions"] = sum(1 for _ in csv.reader(io.StringIO(text_)))
            continue
        for n, cols in enumerate(csv.reader(io.StringIO(text_)), start=1):
            out.read += 1
            if out.read % BATCH == 0:
                progress("reading", out.read, None)
            if len(cols) < 11:
                out.reject(n, name, "fewer than 11 columns")
                continue
            if not cols[2].strip() or cols[1].strip().lower() in ("country", "iso 3166 alpha-2 country code"):
                continue                                        # a country heading row or a header
            change, country, loc = cols[0].strip(), cols[1].strip().upper(), cols[2].strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", country) or not re.fullmatch(r"[A-Z2-9]{3}", loc):
                out.reject(n, name, "bad code")
                continue
            code = country + loc
            if code in seen:
                out.reject(n, name, "code repeated in the file")
                continue
            seen.add(code)
            fn = cols[7].strip()
            lat, lon = importer._coordinates(cols[10])
            out.rows.append({"unlocode": code, "country_iso2": country, "code": loc, "name": cols[3].strip(),
                             "name_ascii": cols[4].strip() or ascii_name(cols[3]), "subdivision": cols[5].strip() or None,
                             "functions": fn or None, **importer._flags_from_function(fn), "latitude": lat, "longitude": lon,
                             "iata": cols[9].strip().upper() or None, "active": change != "X"})
    return out


def _elf(parts: dict[str, bytes], progress: Progress) -> Parsed:
    out = Parsed("elf")
    groups: dict[str, dict] = {}
    for name, data in parts.items():
        text_, enc = decode(data)
        out.encodings[name] = enc
        out.parts.append(name)
        reader = csv.reader(io.StringIO(text_))
        header = next(reader, [])
        index = {norm_header(h): i for i, h in enumerate(header)}
        col = {key: index.get(label) for key, label in ELF_COLUMNS.items()}
        missing = [shown for key, shown in ELF_REQUIRED.items() if col[key] is None]
        for n, cols in enumerate(reader, start=2):
            out.read += 1
            if out.read % BATCH == 0:
                progress("reading", out.read, None)
            if missing:
                out.reject(n, name, f"column {missing[0]} not found")
                continue
            if not any(c.strip() for c in cols):
                continue
            get = lambda key: (cols[col[key]].strip() if col[key] is not None and col[key] < len(cols) else "")  # noqa: E731
            elf = get("code").upper()
            if not re.fullmatch(r"[A-Z0-9]{4}", elf):
                out.reject(n, name, "bad ELF code")
                continue
            country = get("country").upper()[:2]
            special = elf in SPECIAL_ELF
            if not special and not re.fullmatch(r"[A-Z]{2}", country):
                out.reject(n, name, "no country code")
                continue
            g = groups.setdefault(elf, {"code": f"ELF-{elf}", "elf_code": elf, "country_iso2": "XX" if special else country,
                                        "local_name": "", "transliterated": None, "abbreviations": [], "active": True,
                                        "names": [], "name_fa": None, "special": special})
            local = get("local_name")
            lang = get("language_code").lower() or None
            abbreviations = [a.strip() for a in re.split(r"[;,]", get("abbr_local")) if a.strip()]
            if local or special:
                g["names"].append({"lang": lang, "name": local or SPECIAL_ELF.get(elf, ""), "language": get("language") or None,
                                   "transliterated": get("transliterated") or None, "abbreviations": abbreviations})
            g["local_name"] = g["local_name"] or local or SPECIAL_ELF.get(elf, elf)
            g["transliterated"] = g["transliterated"] or get("transliterated") or None
            g["abbreviations"] += [a for a in abbreviations if a not in g["abbreviations"]]
            if lang == "fa" and local:
                g["name_fa"] = local
            if get("status").upper() == "INAC":
                g["active"] = False
    out.rows = list(groups.values())
    out.notes["codes"] = len(out.rows)
    out.notes["special"] = sorted(r["elf_code"] for r in out.rows if r["special"])
    out.notes["inactive"] = sum(1 for r in out.rows if not r["active"])
    return out


def parse(dataset: str, parts: dict[str, bytes], progress: Progress = lambda *a: None) -> Parsed:
    parsed = (_unlocode if dataset == "unlocode" else _elf)(parts, progress)
    total = parsed.read
    if total and sum(parsed.rejected.values()) > total / 2:
        parsed.warnings.append("mostly_rejected")
    return parsed


# ---- staging and merge -------------------------------------------------------------------------------------------------

LOC_COLS = ["unlocode", "country_iso2", "code", "name", "name_ascii", "subdivision", "functions", "is_port", "is_rail",
            "is_road", "is_airport", "is_postal", "is_multimodal", "is_fixed", "is_border", "latitude", "longitude", "iata",
            "active"]
LOC_TYPES = ["text"] * 7 + ["bool"] * 8 + ["numeric", "numeric", "text", "bool"]
ELF_COLS = ["code", "elf_code", "country_iso2", "local_name", "transliterated", "abbreviations", "active", "names", "name_fa"]
ELF_TYPES = ["text", "text", "text", "text", "text", "text[]", "bool", "text", "text"]


def _copy(db: Session, table: str, cols: list[str], types: list[str], rows: list[dict], progress: Progress,
          cancelled: Callable[[], bool]) -> None:
    raw = db.connection().connection.driver_connection
    with raw.cursor() as cur:
        with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
            cp.set_types(types)
            for i, r in enumerate(rows, start=1):
                cp.write_row([json.dumps(r[c], ensure_ascii=False) if c == "names" else r[c] for c in cols])
                if i % BATCH == 0:
                    progress("loading", i, len(rows))
                    if cancelled():
                        raise Cancelled()


def _stage_unlocode(db: Session, parsed: Parsed, progress: Progress, cancelled: Callable[[], bool]) -> None:
    db.execute(text("DROP TABLE IF EXISTS stg_loc, stg_cur"))
    db.execute(text("CREATE TEMP TABLE stg_loc (unlocode text PRIMARY KEY, country_iso2 text, code text, name text, "
                    "name_ascii text, subdivision text, functions text, is_port bool, is_rail bool, is_road bool, "
                    "is_airport bool, is_postal bool, is_multimodal bool, is_fixed bool, is_border bool, latitude numeric, "
                    "longitude numeric, iata text, active bool) ON COMMIT DROP"))
    _copy(db, "stg_loc", LOC_COLS, LOC_TYPES, parsed.rows, progress, cancelled)
    # the shipped curated rows: a use they record (CNSHA as a port), their IATA and Persian name are kept on every import
    db.execute(text("CREATE TEMP TABLE stg_cur (unlocode text PRIMARY KEY, name_fa text, iata text, is_port bool, "
                    "is_rail bool, is_road bool, is_airport bool) ON COMMIT DROP"))
    curated = importer._curated_rows()
    if curated:
        db.execute(text("INSERT INTO stg_cur VALUES (:u, :fa, :iata, :p, :r, :d, :a)"),
                   [{"u": code, "fa": c["name_fa"], "iata": c["iata"], "p": c["is_port"], "r": c["is_rail"],
                     "d": c["is_road"], "a": c["is_airport"]} for code, c in curated.items()])
    db.execute(text("ANALYZE stg_loc"))


MERGED_LOC = """
    SELECT s.unlocode, s.country_iso2, s.code, s.name, s.name_ascii, s.subdivision, s.functions,
           s.is_port OR coalesce(c.is_port, false) AS is_port, s.is_rail OR coalesce(c.is_rail, false) AS is_rail,
           s.is_road OR coalesce(c.is_road, false) AS is_road, s.is_airport OR coalesce(c.is_airport, false) AS is_airport,
           s.is_postal, s.is_multimodal, s.is_fixed, s.is_border, s.latitude, s.longitude,
           coalesce(s.iata, c.iata) AS iata, s.active, coalesce(l.name_fa, c.name_fa) AS name_fa,
           l.id AS existing_id
    FROM stg_loc s LEFT JOIN stg_cur c ON c.unlocode = s.unlocode LEFT JOIN ref.location l ON l.unlocode = s.unlocode"""
LOC_SET = ["country_iso2", "code", "name", "name_ascii", "subdivision", "functions", "is_port", "is_rail", "is_road",
           "is_airport", "is_postal", "is_multimodal", "is_fixed", "is_border", "latitude", "longitude", "iata", "active",
           "name_fa"]


def _loc_changed(alias_new: str, alias_old: str) -> str:
    cols = LOC_SET + ["source", "verified", "release"]
    return (f"({', '.join(f'{alias_old}.{c}' for c in cols)}) IS DISTINCT FROM "
            f"({', '.join(f'{alias_new}.{c}' for c in cols)})")


def _counts_unlocode(db: Session, parsed: Parsed, release: str | None) -> dict:
    p = {"rel": release}
    inserted = db.execute(text(f"SELECT count(*) FROM ({MERGED_LOC}) m WHERE m.existing_id IS NULL")).scalar()
    updated = db.execute(text(
        f"SELECT count(*) FROM ({MERGED_LOC}) m JOIN ref.location l ON l.id = m.existing_id "
        f"CROSS JOIN LATERAL (SELECT m.*, 'unece'::text AS source, true AS verified, CAST(:rel AS text) AS release) n "
        f"WHERE {_loc_changed('n', 'l')}"), p).scalar()
    deactivated = db.execute(text(
        "SELECT count(*) FROM ref.location l WHERE l.source = 'unece' AND l.active "
        "AND NOT EXISTS (SELECT 1 FROM stg_loc s WHERE s.unlocode = l.unlocode)")).scalar() if parsed.complete else 0
    return {"insert": inserted, "update": updated, "deactivate": deactivated,
            "unchanged": len(parsed.rows) - inserted - updated}


def _merge_unlocode(db: Session, parsed: Parsed, release: str | None) -> dict:
    cols = LOC_SET + ["unlocode", "source", "verified", "release"]
    res = db.execute(text(
        f"INSERT INTO ref.location AS l ({', '.join(cols)}) "
        f"SELECT {', '.join('m.' + c for c in LOC_SET)}, m.unlocode, 'unece', true, CAST(:rel AS text) FROM ({MERGED_LOC}) m "
        f"ON CONFLICT (unlocode) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in LOC_SET + ['source', 'verified', 'release'])}, "
        f"updated_at = now() WHERE {_loc_changed('EXCLUDED', 'l')} RETURNING (xmax = 0) AS inserted"), {"rel": release}).scalars().all()
    inserted = sum(1 for x in res if x)
    out = {"inserted": inserted, "updated": len(res) - inserted, "deactivated": 0}
    if parsed.complete:
        out["deactivated"] = db.execute(text(
            "UPDATE ref.location l SET active = false, updated_at = now() WHERE l.source = 'unece' AND l.active "
            "AND NOT EXISTS (SELECT 1 FROM stg_loc s WHERE s.unlocode = l.unlocode)")).rowcount
    out["unchanged"] = len(parsed.rows) - out["inserted"] - out["updated"]
    # airports of the same IATA code point at their location
    db.execute(text("UPDATE ref.airport a SET location_id = l.id FROM ref.location l "
                    "WHERE a.location_id IS NULL AND l.iata IS NOT NULL AND a.iata = l.iata AND l.active"))
    return out


def _curated_check(parsed: Parsed) -> dict:
    """After a UN/LOCODE import: the curated rows matched, the mismatches, and (complete release) those not in it."""
    curated = importer._curated_rows()
    by_code = {r["unlocode"]: r for r in parsed.rows}
    matched, mismatches = 0, []
    for code, mine in curated.items():
        row = by_code.get(code)
        if row is None:
            continue
        matched += 1
        mismatches += importer._curated_mismatches(code, mine, row)
    # reported, not rejected: they stay unverified (for a single part file, they may be in another part)
    return {"curated_matched": matched, "curated_mismatches": mismatches[:500],
            "curated_not_in_file": sorted(set(curated) - set(by_code))[:200]}


def _stage_elf(db: Session, parsed: Parsed, progress: Progress, cancelled: Callable[[], bool]) -> None:
    db.execute(text("DROP TABLE IF EXISTS stg_elf"))
    db.execute(text("CREATE TEMP TABLE stg_elf (code text PRIMARY KEY, elf_code text, country_iso2 text, local_name text, "
                    "transliterated text, abbreviations text[], active bool, names text, name_fa text) ON COMMIT DROP"))
    _copy(db, "stg_elf", ELF_COLS, ELF_TYPES, parsed.rows, progress, cancelled)


MERGED_ELF = """
    SELECT s.code, s.elf_code, s.country_iso2, s.local_name, s.transliterated, s.abbreviations, s.active,
           s.names::jsonb AS names, coalesce(l.name_fa, s.name_fa) AS name_fa, l.id AS existing_id
    FROM stg_elf s LEFT JOIN ref.legal_form l ON l.code = s.code"""
ELF_SET = ["elf_code", "country_iso2", "local_name", "transliterated", "abbreviations", "active", "names", "name_fa"]


def _elf_changed(alias_new: str, alias_old: str) -> str:
    cols = ELF_SET + ["source", "release"]
    return (f"({', '.join(f'{alias_old}.{c}' for c in cols)}) IS DISTINCT FROM "
            f"({', '.join(f'{alias_new}.{c}' for c in cols)})")


def _counts_elf(db: Session, parsed: Parsed, release: str | None) -> dict:
    inserted = db.execute(text(f"SELECT count(*) FROM ({MERGED_ELF}) m WHERE m.existing_id IS NULL")).scalar()
    updated = db.execute(text(
        f"SELECT count(*) FROM ({MERGED_ELF}) m JOIN ref.legal_form l ON l.id = m.existing_id "
        f"CROSS JOIN LATERAL (SELECT m.*, 'gleif'::text AS source, CAST(:rel AS text) AS release) n WHERE {_elf_changed('n', 'l')}"),
        {"rel": release}).scalar()
    deactivated = db.execute(text("SELECT count(*) FROM ref.legal_form l WHERE l.source = 'gleif' AND l.active "
                                  "AND NOT EXISTS (SELECT 1 FROM stg_elf s WHERE s.code = l.code)")).scalar()
    return {"insert": inserted, "update": updated, "deactivate": deactivated, "unchanged": len(parsed.rows) - inserted - updated}


def _merge_elf(db: Session, parsed: Parsed, release: str | None) -> dict:
    cols = ELF_SET + ["code", "source", "curated", "release"]
    res = db.execute(text(
        f"INSERT INTO ref.legal_form AS l ({', '.join(cols)}) "
        f"SELECT {', '.join('m.' + c for c in ELF_SET)}, m.code, 'gleif', false, CAST(:rel AS text) FROM ({MERGED_ELF}) m "
        f"ON CONFLICT (code) DO UPDATE SET {', '.join(f'{c} = EXCLUDED.{c}' for c in ELF_SET + ['source', 'release'])}, "
        f"updated_at = now() WHERE {_elf_changed('EXCLUDED', 'l')} RETURNING (xmax = 0) AS inserted"), {"rel": release}).scalars().all()
    inserted = sum(1 for x in res if x)
    deactivated = db.execute(text("UPDATE ref.legal_form l SET active = false, updated_at = now() WHERE l.source = 'gleif' "
                                  "AND l.active AND NOT EXISTS (SELECT 1 FROM stg_elf s WHERE s.code = l.code)")).rowcount
    return {"inserted": inserted, "updated": len(res) - inserted, "deactivated": deactivated,
            "unchanged": len(parsed.rows) - len(res)}


STAGE = {"unlocode": _stage_unlocode, "elf": _stage_elf}
COUNT = {"unlocode": _counts_unlocode, "elf": _counts_elf}
MERGE = {"unlocode": _merge_unlocode, "elf": _merge_elf}


def summary(parsed: Parsed) -> dict:
    rejected = sum(parsed.rejected.values())
    return {"rows_read": parsed.read, "records": len(parsed.rows), "rejected": rejected,
            "reasons": [{"reason": r, "count": n} for r, n in parsed.rejected.most_common()],
            "examples": parsed.examples, "encodings": parsed.encodings, "parts": parsed.parts, "complete": parsed.complete,
            "warnings": parsed.warnings, "notes": parsed.notes}


def preview(db: Session, dataset: str, parts: dict[str, bytes], release: str | None, progress: Progress = lambda *a: None,
            cancelled: Callable[[], bool] = lambda: False) -> dict:
    """The dry run: what an import would do. Always rolled back by the caller (temporary tables only)."""
    parsed = parse(dataset, parts, progress)
    if cancelled():
        raise Cancelled()
    progress("checking", parsed.read, parsed.read)
    STAGE[dataset](db, parsed, progress, cancelled)
    counts = COUNT[dataset](db, parsed, release)
    return {**summary(parsed), **counts, "dataset": dataset, "release": release}


def apply(db: Session, dataset: str, parts: dict[str, bytes], release: str | None, progress: Progress = lambda *a: None,
          cancelled: Callable[[], bool] = lambda: False) -> dict:
    """The import, in the caller's transaction: parse, stage with COPY, merge set-based. The caller commits."""
    started = time.monotonic()
    parsed = parse(dataset, parts, progress)
    if cancelled():
        raise Cancelled()
    STAGE[dataset](db, parsed, progress, cancelled)
    if cancelled():
        raise Cancelled()
    progress("merging", parsed.read, parsed.read)
    out = MERGE[dataset](db, parsed, release)
    if dataset == "unlocode":
        parsed.notes.update(_curated_check(parsed))
    if cancelled():
        raise Cancelled()
    return {**summary(parsed), **out, "dataset": dataset, "release": release, "seconds": round(time.monotonic() - started, 2)}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
