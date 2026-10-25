"""Supplier capability tags: HS chapters/headings, ISIC sections/divisions and free tags per party.

Only this module writes ``core.party_capability``. Codes are stored as text (no FK to ``ref``), so a new HS or
ISIC edition can replace the reference rows; a code missing from the current edition is shown as "unknown".
"""

import re
import uuid

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.text import WORD_SIMILARITY, normalize_fa
from app.modules.events import service as events
from app.modules.parties import service as parties
from app.modules.sourcing.common import flush, jsonable
from app.modules.sourcing.models import HsCode, IsicCode, PartyCapability

REF = {"hs": HsCode, "isic": IsicCode}


def tag_norm(value: str) -> str:
    return (normalize_fa(value or "") or "").lower()


def _title(row) -> dict:
    return {"code": row.code, "level": row.level, "parent_code": row.parent_code, "title_en": row.title_en,
            "title_fa": row.title_fa, "title_fa_missing": not row.title_fa, "edition": row.edition}


def normalize_code(kind: str, code: str) -> str:
    code = (code or "").strip().upper().replace(".", "").replace(" ", "")
    if kind == "isic" and re.fullmatch(r"[A-U]\d{2}", code):
        code = code[1:]  # "C20" -> division "20"
    return code


def get_code(db: Session, kind: str, code: str):
    return db.get(REF[kind], normalize_code(kind, code))


def code_info(db: Session, kind: str, code: str) -> dict:
    row = get_code(db, kind, code)
    if row is None:
        return {"code": code, "unknown": True}
    info = _title(row)
    if row.parent_code:
        parent = db.get(REF[kind], row.parent_code)
        info["parent"] = _title(parent) if parent else None
    return info


def search_codes(db: Session, kind: str, q: str | None, parent: str | None = None, limit: int = 30) -> list[dict]:
    """Search by code prefix or title (Persian-normalized); without q: the top level or the children of parent."""
    model = REF[kind]
    query = select(model)
    needle = tag_norm(q or "")
    if needle:
        code = normalize_code(kind, needle)
        db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"),
                   {"v": str(WORD_SIMILARITY)})
        like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(or_(model.code.like(code + "%"), model.title_norm.like(like),
                                text(f"ref.{model.__tablename__}.title_norm %> :cap_q").bindparams(cap_q=needle)))
    elif parent:
        query = query.where(model.parent_code == normalize_code(kind, parent))
    else:
        query = query.where(model.parent_code.is_(None))
    rows = db.scalars(query.order_by(model.code).limit(limit)).all()
    parents = {p.code: p for p in db.scalars(select(model).where(model.code.in_({r.parent_code for r in rows if r.parent_code})))}
    return [{**_title(r), "parent": _title(parents[r.parent_code]) if r.parent_code in parents else None} for r in rows]


def capabilities_of(db: Session, party_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(select(PartyCapability).where(PartyCapability.party_id == party_id)
                      .order_by(PartyCapability.kind, PartyCapability.code, PartyCapability.tag_norm)).all()
    out = []
    for row in rows:
        item = {"id": str(row.id), "kind": row.kind, "code": row.code, "tag_text": row.tag_text, "notes": row.notes}
        if row.kind != "tag":
            item["info"] = code_info(db, row.kind, row.code)
        out.append(item)
    return out


def _existing(db: Session, party_id: uuid.UUID, kind: str, code: str | None, tag: str | None):
    query = select(PartyCapability).where(PartyCapability.party_id == party_id, PartyCapability.kind == kind)
    if kind == "tag":
        return db.scalar(query.where(PartyCapability.tag_norm == tag_norm(tag)))
    return db.scalar(query.where(PartyCapability.code == code))


def add(db: Session, party_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> PartyCapability:
    parties.get_party(db, party_id)
    kind = data["kind"]
    code, tag = None, None
    if kind == "tag":
        tag = " ".join((data.get("tag_text") or "").split())
        if not tag:
            raise AppError("tag_required", "The tag is empty", status=422)
    else:
        code = normalize_code(kind, data.get("code") or "")
        if get_code(db, kind, code) is None:
            raise AppError("unknown_code", f"Unknown {kind.upper()} code", {"kind": kind, "code": code}, status=422)
    if _existing(db, party_id, kind, code, tag) is not None:
        raise Conflict("duplicate_capability", "The party already has this capability",
                       {"kind": kind, "code": code, "tag": tag})
    row = PartyCapability(party_id=party_id, kind=kind, code=code, tag_text=tag, notes=data.get("notes"))
    db.add(row)
    flush(db, "duplicate_capability")
    events.record(db, "party", party_id, "capability_add", jsonable({"id": row.id, "kind": kind, "code": code,
                                                                     "tag": tag}), source, actor=actor)
    return row


def remove(db: Session, capability_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = db.get(PartyCapability, capability_id)
    if row is None:
        raise NotFound("not_found", "Capability not found")
    db.delete(row)
    flush(db, "in_use")
    events.record(db, "party", row.party_id, "capability_remove",
                  {"kind": row.kind, "code": row.code, "tag": row.tag_text}, source, actor=actor)


def replace(db: Session, party_id: uuid.UUID, wanted: list[dict], source: str, actor: str | None = None) -> list[dict]:
    """Multi-select save: add what is new, remove what is gone, keep the rest (with their notes)."""
    parties.get_party(db, party_id)
    keys = []
    for data in wanted:
        if data["kind"] == "tag":
            keys.append(("tag", tag_norm(data.get("tag_text") or ""), data))
        else:
            keys.append((data["kind"], normalize_code(data["kind"], data.get("code") or ""), data))
    current = db.scalars(select(PartyCapability).where(PartyCapability.party_id == party_id)).all()
    current_keys = {(r.kind, r.tag_norm if r.kind == "tag" else r.code): r for r in current}
    wanted_keys = {(k, c) for k, c, _ in keys}
    for key, row in current_keys.items():
        if key not in wanted_keys:
            remove(db, row.id, source, actor)
    seen = set()
    for kind, code, data in keys:
        if (kind, code) in current_keys or (kind, code) in seen:
            continue
        seen.add((kind, code))
        add(db, party_id, data, source, actor)
    return capabilities_of(db, party_id)


def matching_party_ids(db: Session, spec: str) -> set[uuid.UUID]:
    """Party filter "hs:3907", "hs:39", "isic:C20", "isic:C", "tag:pe100"."""
    kind, _, value = (spec or "").partition(":")
    kind = kind.strip().lower()
    if kind == "tag":
        norm = tag_norm(value)
        rows = db.scalars(select(PartyCapability.party_id).where(PartyCapability.kind == "tag",
                                                                 PartyCapability.tag_norm == norm))
        return set(rows)
    if kind not in REF:
        raise AppError("invalid_capability_filter", "Use hs:<code>, isic:<code> or tag:<text>", status=422)
    raw = (value or "").strip().upper()
    code = normalize_code(kind, raw)
    codes = {code}
    children_of = None
    if kind == "hs":
        if len(code) == 4:
            codes.add(code[:2])
        elif len(code) == 2:
            children_of = code
    else:
        row = get_code(db, kind, code)
        if row is not None and row.parent_code:
            codes.add(row.parent_code)
        elif row is not None:
            children_of = row.code
    condition = PartyCapability.code.in_(codes)
    if children_of:
        if kind == "hs":
            condition = or_(condition, PartyCapability.code.like(children_of + "%"))
        else:
            divisions = select(IsicCode.code).where(IsicCode.parent_code == children_of)
            condition = or_(condition, PartyCapability.code.in_(divisions))
    return set(db.scalars(select(PartyCapability.party_id).where(PartyCapability.kind == kind, condition)))


def suggest_suppliers(db: Session, hs_codes: list[str], exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """Parties whose HS tags match the items' HS codes: 4-digit heading first, then chapter. Suggestions only."""
    exclude = exclude or set()
    headings = {c[:4] for c in hs_codes if c and len(c) >= 4}
    chapters = {c[:2] for c in hs_codes if c and len(c) >= 2}
    if not chapters:
        return []
    rows = db.scalars(select(PartyCapability).where(PartyCapability.kind == "hs", or_(
        PartyCapability.code.in_(headings), PartyCapability.code.in_(chapters),
        *[PartyCapability.code.like(ch + "%") for ch in chapters]))).all()
    found: dict[uuid.UUID, dict] = {}
    for row in rows:
        if row.party_id in exclude:
            continue
        level = "heading" if row.code in headings else "chapter"
        entry = found.setdefault(row.party_id, {"party_id": row.party_id, "match": level, "codes": []})
        if level == "heading":
            entry["match"] = "heading"
        entry["codes"].append(row.code)
    party_rows = {p.id: p for p in (parties.get_party(db, pid) for pid in found)}
    roles = parties.roles_for(db, list(found))
    out = []
    for pid, entry in found.items():
        party = party_rows[pid]
        if party.status != "active" or party.do_not_contact:
            continue
        stage = next((r.stage for r in roles[pid] if r.role == "supplier"), None)
        out.append({**entry, "name_fa": party.name_fa, "name_en": party.name_en, "country_iso2": party.country_iso2,
                    "supplier_stage": stage, "codes": sorted(set(entry["codes"]))})
    return jsonable(sorted(out, key=lambda e: (e["match"] != "heading", (e["name_en"] or e["name_fa"] or ""))))


def search_party_ids(db: Session, needle: str, limit: int = 50) -> list[uuid.UUID]:
    """Parties findable by capability: code prefix, HS/ISIC title, or free tag (for the party search result)."""
    norm = tag_norm(needle)
    if not norm:
        return []
    like = "%" + norm.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = db.execute(text(
        """
        SELECT DISTINCT c.party_id FROM core.party_capability c
        LEFT JOIN ref.hs_code h ON c.kind = 'hs' AND h.code = c.code
        LEFT JOIN ref.isic_code i ON c.kind = 'isic' AND i.code = c.code
        WHERE (c.kind = 'tag' AND c.tag_norm LIKE :like)
           OR (c.kind <> 'tag' AND (c.code LIKE :prefix OR h.title_norm LIKE :like OR i.title_norm LIKE :like))
        LIMIT :limit
        """
    ), {"like": like, "prefix": normalize_code("hs", norm) + "%", "limit": limit}).scalars().all()
    return list(rows)
