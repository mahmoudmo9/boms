"""Convert a Setad listing to an inquiry (v0.5.0, Phase 7a, section 5).

The inquiry, its items and the buyer party are written by their own modules (sourcing, parties, documents, catalog);
this module writes only its own rows (screening, file -> document link) and the listing events.

- ``preview``: what the conversion will create (nothing is stored): buyer match / suggestions, items with product
  suggestions, files (downloaded / missing), dates.
- ``convert``: refused with 409 ``already_converted`` (with the inquiry id) the second time; a listing must be starred
  or reviewing; the buyer is an existing party (``party_id``), the exact normalized-name match, or a new party
  (``create_party``; the duplicate warning of Phase 3 returns 409 ``duplicate_party`` until confirmed).
- ``deadline_change`` / ``apply_deadline``: a later fetch that changed the deadline of a converted listing shows a
  banner on the inquiry; "Apply" moves the deadline and the follow-ups planned around it (never silently).
- ``reset_screening`` (hook): deleting the inquiry puts the listing back to ``reviewing``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.connectors.setad import jalali as setad_jalali
from app.connectors.setad import pipeline as setad_pipeline
from app.core.errors import AppError, Conflict
from app.core.text import normalize_fa
from app.core.time import utcnow
from app.modules.catalog import service as catalog
from app.modules.documents import service as documents
from app.modules.events import service as events
from app.modules.listings.models import Listing, ListingDetail, ListingFile, ListingScreening
from app.modules.listings.service import SOURCE_PURCHASE, _screening, _sync_file_state, get_listing, screening_of
from app.modules.parties import service as parties
from app.modules.sourcing import inquiries as sourcing

TEHRAN = ZoneInfo("Asia/Tehran")
CONVERTIBLE = ("starred", "reviewing")
CONTACT_LABELS = ("تماس", "تلفن", "نمابر", "فکس", "آدرس", "نشانی", "کد پستی", "پست الکترونیک", "ایمیل")
GOODS_CODE_KEY = "کد کالای ستاد"


def deadline_of(x: Listing) -> datetime | None:
    """The listing's deadline (same rule as the list's deadline column)."""
    if x.source == SOURCE_PURCHASE:
        return x.response_deadline
    if x.in_my_calls:
        return x.proposal_deadline or x.inquiry_deadline or x.documents_deadline
    return x.documents_deadline


def _day(value: datetime | None) -> date | None:
    return value.astimezone(TEHRAN).date() if value else None


def _detail(db: Session, x: Listing) -> ListingDetail | None:
    return db.get(ListingDetail, x.id)


def _info(x: Listing, d: ListingDetail | None) -> dict:
    return {"fields": (d.fields if d else []) or [], "items": (d.items if d else {}) or {},
            "description": x.description or x.title}


def buyer_contact(d: ListingDetail | None) -> str:
    """Contact lines of the detail page (phone, fax, address...) for the buyer party's notes."""
    lines = [f"{k}: {v}" for k, v in ((d.fields if d else []) or [])
             if v and any(label in (k or "") for label in CONTACT_LABELS)]
    return "\n".join(dict.fromkeys(lines))


def match_buyer(db: Session, name: str) -> tuple[dict | None, list[dict]]:
    """(exact party by normalized name, similar parties) for the listing's organization."""
    norm = normalize_fa(name or "") or ""
    if not norm:
        return None, []
    row = db.execute(text("SELECT id, name_fa, name_en FROM core.party WHERE status <> 'archived' AND "
                          "(core.normalize_fa(coalesce(name_fa, '')) = :n OR core.normalize_fa(coalesce(name_en, '')) = :n) "
                          "ORDER BY created_at LIMIT 1"), {"n": norm}).first()
    exact = {"id": row.id, "name_fa": row.name_fa, "name_en": row.name_en} if row else None
    similar = [s for s in parties.find_duplicates(db, name, None) if not exact or s["id"] != exact["id"]]
    return exact, similar


def _qty(value: float | None) -> Decimal:
    try:
        q = Decimal(str(value)) if value else Decimal(1)
    except InvalidOperation:
        q = Decimal(1)
    return q.quantize(Decimal("0.0001")) if q > 0 else Decimal(1)


def items_for(db: Session, x: Listing, d: ListingDetail | None) -> list[dict]:
    """Inquiry items from the detail items table, or one item from the description (SetadSuite ``items_of``)."""
    out = []
    for i, it in enumerate(setad_pipeline.items_of(SimpleNamespace(description=x.description or x.title),
                                                   _info(x, d)), start=1):
        name = (it.name or x.title or "-").strip()[:1000]
        suggestions = catalog.find_duplicates(db, [name])[:5]
        out.append({
            "position": i, "name": name, "quantity": _qty(it.qty), "unit_text": (it.unit or None),
            "required_by": setad_jalali.to_date(it.need_date) if it.need_date else None,
            "goods_code": it.code or None,
            "product_suggestions": [{"id": s["id"], "name": s.get("name_fa") or s.get("name_en") or s.get("name"),
                                     "score": s.get("score")} for s in suggestions],
        })
    return out


def _files(db: Session, x: Listing) -> list[ListingFile]:
    files = list(db.scalars(select(ListingFile).where(ListingFile.listing_id == x.id)
                            .order_by(ListingFile.group_title, ListingFile.display_name)))
    for f in files:
        _sync_file_state(f)
    db.flush()
    return files


def _check_convertible(db: Session, x: Listing) -> ListingScreening:
    s = screening_of(db, x.id)
    if s is not None and (s.status == "converted" or s.inquiry_id is not None):
        raise Conflict("already_converted", "The listing was already converted to an inquiry",
                       {"inquiry_id": str(s.inquiry_id) if s.inquiry_id else None,
                        "link": f"/sourcing/inquiries/{s.inquiry_id}" if s.inquiry_id else None})
    if s is None or s.status not in CONVERTIBLE:
        raise Conflict("not_screened", "Star the listing or mark it as reviewing before converting",
                       {"status": s.status if s else "new"})
    return s


def preview(db: Session, listing_id: uuid.UUID) -> dict[str, Any]:
    x = get_listing(db, listing_id)
    s = screening_of(db, x.id)
    d = _detail(db, x)
    exact, similar = match_buyer(db, x.organization)
    files = _files(db, x)
    deadline = deadline_of(x)
    return {
        "listing_id": x.id, "source": x.source, "number": x.external_no, "title": x.title, "url": x.detail_url,
        "kind": "rfq" if x.source == SOURCE_PURCHASE else "tender",
        "status": s.status if s else "new", "inquiry_id": s.inquiry_id if s else None,
        "received_at": x.published_at, "response_due_at": deadline, "deadline_exact": bool(x.deadline_exact),
        "required_price_validity": _day(x.price_valid_until),
        "delivery_province": x.province or None, "delivery_city": x.city or None,
        "buyer_note": (d.buyer_note if d else "") or "", "buyer_contact": buyer_contact(d),
        "detail_fetched": d is not None,
        "buyer": {"name": x.organization, "match": exact, "suggestions": similar},
        "items": items_for(db, x, d),
        "files": {"total": len(files), "downloaded": sum(f.state == "downloaded" for f in files),
                  "missing": [{"id": f.id, "name": f.display_name, "state": f.state} for f in files
                              if f.state != "downloaded"]},
    }


def _resolve_buyer(db: Session, x: Listing, data: dict, source: str, actor: str | None) -> uuid.UUID:
    if data.get("party_id"):
        party = parties.get_party(db, data["party_id"])
        party_id = party.id
    else:
        exact, similar = match_buyer(db, x.organization)
        if exact and not data.get("create_party"):
            party_id = exact["id"]
        elif data.get("create_party"):
            party, duplicates = parties.create_party(db, {
                "name_fa": (data.get("party_name") or x.organization or "").strip() or None, "kind": "company",
                "country_iso2": "IR", "roles": ["buyer"], "confirm_duplicate": bool(data.get("confirm_duplicate"))},
                source, actor)
            if party is None:
                raise Conflict("duplicate_party", "A similar party exists; pick it or confirm a new one",
                               {"duplicates": [{**d, "id": str(d["id"])} for d in duplicates]})
            party_id = party.id
        else:
            raise AppError("buyer_required", "Pick the buyer party or create a new one",
                           {"suggestions": [{**s, "id": str(s["id"])} for s in similar]}, status=422)
    if not any(r.role == "buyer" for r in parties.roles_of(db, party_id)):
        parties.add_role(db, party_id, "buyer", None, source, actor)
    return party_id


def _note_contact(db: Session, party_id: uuid.UUID, contact: str, number: str, source: str, actor: str | None) -> None:
    if not contact:
        return
    party = parties.get_party(db, party_id)
    if contact in (party.notes or ""):
        return
    block = f"ستاد ({number}):\n{contact}"
    parties.update_party(db, party_id, {"notes": f"{party.notes}\n\n{block}" if party.notes else block}, source, actor)


def _copy_files(db: Session, x: Listing, files: list[ListingFile], source: str, actor: str | None) -> tuple[list, list]:
    """Downloaded files -> the document store (hashed; an identical file already stored is reused)."""
    from app.modules.listings.service import local_file

    ids, skipped = [], []
    for f in files:
        if f.state != "downloaded":
            continue
        try:
            path = local_file(db, f.id)
            with path.open("rb") as stream:
                doc = documents.upload(db, stream, path.name, title=f.display_name or path.stem,
                                       notes=f"Setad {x.external_no}", language="fa", source=source, actor=actor)
            f.document_id = doc.id
        except Conflict as exc:
            if exc.code != "duplicate_document":
                raise
            f.document_id = uuid.UUID(exc.details["id"])
        except AppError as exc:  # blocked type, too large, file gone: listed, the conversion goes on
            skipped.append({"name": f.display_name, "code": exc.code})
            continue
        ids.append(f.document_id)
    db.flush()
    return ids, skipped


def convert(db: Session, listing_id: uuid.UUID, data: dict, source: str, actor: str | None = None) -> dict[str, Any]:
    x = get_listing(db, listing_id)
    s = _check_convertible(db, x)
    d = _detail(db, x)
    files = _files(db, x)
    missing = [f for f in files if f.state != "downloaded"]
    if missing and not data.get("without_missing_files"):
        raise Conflict("files_not_downloaded", "Some attachments are not downloaded yet",
                       {"missing": [f.display_name for f in missing]})
    party_id = _resolve_buyer(db, x, data, source, actor)
    _note_contact(db, party_id, buyer_contact(d), x.external_no, source, actor)

    products = {int(k): v for k, v in (data.get("products") or {}).items()}  # position -> chosen product id
    items = []
    for it in items_for(db, x, d):
        row = {k: it[k] for k in ("position", "name", "quantity", "unit_text", "required_by")}
        if it["goods_code"]:
            row["specs"] = [{"key": GOODS_CODE_KEY, "value": it["goods_code"]}]
        if products.get(it["position"]):
            row["product_id"] = products[it["position"]]
        items.append(row)
    document_ids, skipped = _copy_files(db, x, files, source, actor)

    deadline = deadline_of(x)
    raw = "\n\n".join(t for t in (x.description, (d.buyer_note if d else "")) if t and t.strip()) or None
    inquiry = sourcing.create_inquiry(db, {
        "party_id": party_id, "source_channel": "setad", "kind": "rfq" if x.source == SOURCE_PURCHASE else "tender",
        "received_at": x.published_at or utcnow(), "response_due_on": _day(deadline), "subject": x.title[:500] or None,
        "raw_text": raw, "items": items, "document_ids": document_ids,
        "listing_id": x.id, "external_no": x.external_no or None, "external_url": x.detail_url,
        "response_due_at": deadline, "required_price_validity": _day(x.price_valid_until),
        "delivery_province": x.province or None, "delivery_city": x.city or None,
    }, source, actor)

    s = _screening(db, x)
    old = s.status
    s.status, s.inquiry_id, s.converted_at = "converted", inquiry.id, utcnow()
    db.flush()
    events.record(db, "listing", x.id, "convert", {"old_status": old, "inquiry_id": str(inquiry.id),
                                                   "party_id": str(party_id), "items": len(items),
                                                   "documents": len(document_ids), "skipped_files": skipped},
                  source, actor=actor)
    return {"inquiry_id": inquiry.id, "party_id": party_id, "items": len(items), "documents": len(document_ids),
            "skipped_files": skipped}


# ---- after conversion -----------------------------------------------------------------------------------------

def origin_of_inquiry(db: Session, inquiry_id: uuid.UUID) -> dict | None:
    """"From Setad «number»" on the inquiry, with the deadline banner when the listing's deadline moved."""
    inquiry = sourcing.get_inquiry(db, inquiry_id)
    if inquiry.listing_id is None:
        return None
    x = db.get(Listing, inquiry.listing_id)
    if x is None:
        return {"listing_id": inquiry.listing_id, "number": inquiry.external_no, "url": inquiry.external_url,
                "deadline_change": None}
    return {"listing_id": x.id, "number": x.external_no, "url": x.detail_url, "source": x.source,
            "deadline_change": deadline_change(db, inquiry)}


def deadline_change(db: Session, inquiry) -> dict | None:
    x = db.get(Listing, inquiry.listing_id) if inquiry.listing_id else None
    new = deadline_of(x) if x else None
    if new is None or inquiry.response_due_at == new:
        return None
    return {"old": inquiry.response_due_at, "new": new}


def apply_deadline(db: Session, inquiry_id: uuid.UUID, source: str, actor: str | None = None) -> dict:
    inquiry = sourcing.get_inquiry(db, inquiry_id)
    change = deadline_change(db, inquiry)
    if change is None:
        raise Conflict("no_deadline_change", "The deadline on Setad has not changed")
    out = sourcing.apply_response_deadline(db, inquiry.id, change["new"], source, actor,
                                           origin={"listing_id": str(inquiry.listing_id), "from": "setad"})
    events.record(db, "listing", inquiry.listing_id, "deadline_applied",
                  {"inquiry_id": str(inquiry.id), "old": change["old"].isoformat() if change["old"] else None,
                   "new": change["new"].isoformat()}, source, actor=actor)
    return out


def changed_deadlines(db: Session) -> list[dict]:
    """Converted listings whose deadline changed on Setad and was not applied (command center)."""
    rows = db.execute(select(Listing, ListingScreening.inquiry_id)
                      .join(ListingScreening, ListingScreening.listing_id == Listing.id)
                      .where(ListingScreening.status == "converted", ListingScreening.inquiry_id.is_not(None))).all()
    out = []
    for x, inquiry_id in rows:
        inquiry = sourcing.get_inquiry(db, inquiry_id)
        change = deadline_change(db, inquiry)
        if change:
            out.append({"listing_id": x.id, "inquiry_id": inquiry_id, "number": x.external_no, "title": x.title,
                        "old": change["old"], "new": change["new"]})
    return out


def reset_screening(db: Session, inquiry_id: uuid.UUID, source: str, actor: str | None) -> dict:
    """Hook: the inquiry is being deleted -> its listing goes back to ``reviewing`` (the listing stays)."""
    rows = list(db.scalars(select(ListingScreening).where(ListingScreening.inquiry_id == inquiry_id)))
    for s in rows:
        s.status, s.inquiry_id, s.converted_at = "reviewing", None, None
        db.flush()
        events.record(db, "listing", s.listing_id, "screen_reset", {"reason": "inquiry deleted",
                                                                    "inquiry_id": str(inquiry_id),
                                                                    "new_status": "reviewing"}, source, actor=actor)
    return {"listings_reset": [str(s.listing_id) for s in rows]} if rows else {}
