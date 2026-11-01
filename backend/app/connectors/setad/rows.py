"""Site rows -> plain listing dicts (what the BOMS `listings` module stores), and the change-tracking rule.

`tender_row` is SetadSuite v0.9.23 setad_tender/db.py Database.tender_row + extra_fields (field names unchanged);
`need_row` maps the purchase-call `Need` of inquiries/parser.py. New in BOMS: dates are also parsed to aware
datetimes (Asia/Tehran), and TRACKED_FIELDS lists the only fields whose change is recorded. SetadSuite recorded a
change whenever the hash of the whole raw row changed, so volatile list metadata (`recCount`, counters) produced a
change row on almost every sync (62,440 rows in the owner's database); BOMS updates `raw` silently instead.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

from . import jalali, pipeline
from .eproc_parser import Need, western_digits

TEHRAN = ZoneInfo("Asia/Tehran")

SOURCE_PURCHASE = "setad_purchase"
SOURCE_TENDER = "setad_tender"

# Fields whose change is recorded (ext.listing_change). Everything else only refreshes `raw`.
TRACKED_FIELDS = (
    "external_no", "title", "organization", "province", "city", "category",
    "published_at", "documents_deadline", "proposal_deadline", "inquiry_deadline", "opening_at",
    "edition_date", "edition_no",
    "document_price", "guarantee_amount", "estimate",
    "site_state",
    "response_deadline", "price_valid_until",
)


def scalar(value):
    # SetadSuite setad_tender/db.py scalar(), unchanged
    if value is None: return ''
    if isinstance(value, dict): return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list): return json.dumps(value, ensure_ascii=False)
    return str(value)


def setad_datetime(text, default_time=(23, 59)) -> datetime | None:
    """Jalali '1405/08/08 12:00:00' (any digits) -> aware datetime in Asia/Tehran; a date without a time gets
    `default_time` (end of day for deadlines, like SetadSuite's jalali.to_datetime)."""
    dt = jalali.to_datetime(str(text or ""), default_time)
    return dt.replace(tzinfo=TEHRAN) if dt else None


def _amount(value):
    text = western_digits("" if value is None else str(value)).replace(",", "").replace("٬", "").strip()
    if text in ("", "null", "None"):
        return None
    try:
        return str(round(float(text), 4))
    except ValueError:
        return None


def extra_fields(raw):
    # SetadSuite setad_tender/db.py Database.extra_fields, unchanged
    ed=raw.get('lastTenderEdition') if isinstance(raw.get('lastTenderEdition'),dict) else {}
    no=scalar(ed.get('supplierNumber') or raw.get('lastTenderEdition.supplierNumber'))
    return {'inquiry_deadline':scalar(raw.get('inquiryDeadlineDate')),
            'last_edition_date':scalar(raw.get('supplierLastEditionDate')),
            'edition_no':no.strip()}


def tender_row(raw: dict) -> dict:
    """One row of the «فراخوان‌ها» grid (raw JSON of the site) -> listing fields."""
    org = raw.get('organization') or {}
    if not isinstance(org, dict): org = {}
    item_id = scalar(raw.get('id')).strip()
    if not item_id:
        raise ValueError('Tender has no internal id')
    extra = extra_fields(raw)
    return {
        "source": SOURCE_TENDER,
        "external_id": item_id,
        "external_no": scalar(raw.get('number')),
        "title": scalar(raw.get('title')),
        "type_name": scalar(raw.get('typeName')),
        "province": scalar(raw.get('operationProvinceName')),
        "city": scalar(raw.get('operationCityName')),
        "organization": scalar(org.get('name') or raw.get('organization.name')),
        "category": scalar(raw.get('domainCatName') or raw.get('subjectClassification') or ''),
        "description": scalar(raw.get('domainsDescription')),
        "published_at": setad_datetime(raw.get('publicNotificationDate'), (0, 0)),
        "documents_deadline": setad_datetime(raw.get('documentsDeadlineDate')),
        "proposal_deadline": setad_datetime(raw.get('proposalDeadlineDate')),
        "inquiry_deadline": setad_datetime(extra['inquiry_deadline']),
        "opening_at": setad_datetime(raw.get('openingDate'), (0, 0)),
        "edition_date": setad_datetime(extra['last_edition_date'], (0, 0)),
        "edition_no": extra['edition_no'],
        "document_price": _amount(raw.get('tenderDocumentsPrice')),
        "guarantee_amount": _amount(raw.get('guaranteeAmount') or raw.get('tenderGuaranteeAmount')),
        "estimate": _amount(raw.get('estimatePrice') or raw.get('estimatedAmount')),
        "raw": raw,
    }


def need_row(need: Need) -> dict:
    """One purchase call (need) of the advanced search / board -> listing fields."""
    province, _, city = need.province.partition("، ")
    return {
        "source": SOURCE_PURCHASE,
        "external_id": need.request_id,
        "external_no": western_digits(need.need_no),
        "title": need.description,
        "organization": need.organization,
        "province": province,
        "city": city,
        "category": need.category,
        "goods_group": need.goods_group,
        "service_group": need.service_group,
        "need_type": need.need_type,
        "published_at": setad_datetime(need.published_date, (0, 0)),
        "detail_url": need.detail_url,
        # the list shows only the time left («۳ روز و ۲ ساعت»): an estimate, refreshed silently until the detail
        # page gives the exact deadline (SetadSuite: needs.deadline_at / deadline_exact)
        "response_hours": pipeline.deadline_hours_from_text(need.response_deadline),
        "raw": asdict(need),
    }


def content_hash(row: dict) -> str:
    """Hash of the tracked fields only (fast "nothing changed" check)."""
    stable = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items() if k in TRACKED_FIELDS}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def tracked_changes(old: dict, new: dict) -> list[tuple[str, object, object]]:
    """(field, old, new) for every tracked field that really changed. Fields missing from `new` (a quick fetch or a
    list that does not carry them) are not changes."""
    out = []
    for field in TRACKED_FIELDS:
        if field not in new:
            continue
        a, b = old.get(field), new.get(field)
        if (a in ("", None)) and (b in ("", None)):
            continue
        if a != b:
            out.append((field, a, b))
    return out
