"""Structured item descriptions (v0.9.0 section 7): noun-modifier templates.

A template (``core.product_template``) has a noun fa/en and ordered attributes (text, number with a UN/ECE unit and an
optional range, or a choice of values). ``validate`` checks attribute values against it; ``canonical`` builds the
description used by outputs::

    PUMP, CENTRIFUGAL, API 610, 120 m3/h, 85 m
    پمپ، گریز از مرکز، API 610، ۱۲۰ مترمکعب بر ساعت، ۸۵ متر

Products and line items keep their free names; the canonical description is generated on save unless the owner
overrides it (``canonical_override``)."""
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFound

FA_DIGITS = str.maketrans("0123456789.", "۰۱۲۳۴۵۶۷۸۹٫")
# UN/ECE Rec. 20 code -> (English symbol, Persian name)
UNIT_SYMBOLS = {"MQH": ("m3/h", "مترمکعب بر ساعت"), "MTR": ("m", "متر"), "MMT": ("mm", "میلی‌متر"),
                "INH": ('"', "اینچ"), "KWT": ("kW", "کیلووات"), "RPM": ("rpm", "دور در دقیقه"),
                "VLT": ("V", "ولت"), "BAR": ("bar", "بار"), "CEL": ("°C", "درجه سانتی‌گراد"),
                "KGM": ("kg", "کیلوگرم"), "LTR": ("L", "لیتر")}
NOUN_FIELDS = ("template_id", "attributes", "canonical_fa", "canonical_en", "canonical_override")


def get_template(db: Session, template_id):
    from app.modules.catalog.models import ProductTemplate

    row = db.get(ProductTemplate, template_id)
    if row is None:
        raise NotFound("not_found", "Product template not found")
    return row


def template_by_key(db: Session, key: str):
    from app.modules.catalog.models import ProductTemplate

    return db.scalar(select(ProductTemplate).where(ProductTemplate.key == key))


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).replace(",", "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٫", "0123456789.")).strip())
    except (InvalidOperation, ValueError):
        return None


def validate(template, attributes: dict | None) -> dict:
    """The attribute values cleaned against the template; 422 ``attribute_invalid`` with the problems otherwise."""
    attributes = dict(attributes or {})
    defs = {a["key"]: a for a in template.attributes}
    problems, out = [], {}
    for key, value in attributes.items():
        if key not in defs:
            problems.append({"attribute": key, "reason": "unknown"})
            continue
        if value is None or value == "":
            continue
        a = defs[key]
        if a.get("type") == "number":
            n = _number(value)
            if n is None:
                problems.append({"attribute": key, "reason": "not_a_number"})
                continue
            if "min" in a and n < Decimal(str(a["min"])) or "max" in a and n > Decimal(str(a["max"])):
                problems.append({"attribute": key, "reason": "out_of_range", "min": a.get("min"), "max": a.get("max")})
                continue
            out[key] = str(n.normalize()) if n == n.to_integral() else str(n)
            if "E" in out[key]:
                out[key] = format(n, "f")
        elif a.get("type") == "choice":
            allowed = {v["value"] for v in a.get("values", [])}
            if value not in allowed:
                problems.append({"attribute": key, "reason": "not_allowed", "allowed": sorted(allowed)})
                continue
            out[key] = value
        else:
            text = str(value).strip()
            if len(text) > 200:
                problems.append({"attribute": key, "reason": "too_long"})
                continue
            out[key] = text
    if problems:
        raise AppError("attribute_invalid", "Some attributes do not fit the template", {"problems": problems}, status=422)
    return out


def _value_text(a: dict, value: str, lang: str) -> str:
    if a.get("type") == "choice":
        found = next((v for v in a.get("values", []) if v["value"] == value), None)
        return (found["fa"] if lang == "fa" else found["en"]) if found else value
    if a.get("type") == "number":
        sym = UNIT_SYMBOLS.get(a.get("unit") or "")
        if lang == "fa":
            number = value.translate(FA_DIGITS)
            return f"{number} {sym[1]}" if sym else number
        if sym:
            return f"{value}{sym[0]}" if sym[0] == '"' else f"{value} {sym[0]}"
        return value
    return value


def canonical(template, attributes: dict, lang: str, short_only: bool = True) -> str:
    sep = "، " if lang == "fa" else ", "
    parts = [template.noun_fa if lang == "fa" else template.noun_en]
    for a in template.attributes:
        if short_only and not a.get("short", True):
            continue
        value = attributes.get(a["key"])
        if value not in (None, ""):
            parts.append(_value_text(a, str(value), lang))
    return sep.join(parts)


def apply(db: Session, row, data: dict) -> dict:
    """Sets the noun-modifier fields of a product or line item from ``data`` (removing them from it) and regenerates
    the canonical descriptions unless the owner overrides them. Returns the changes for the event."""
    given = {k: data.pop(k) for k in NOUN_FIELDS if k in data}
    if not given:
        return {}
    if "template_id" in given:
        row.template_id = given["template_id"]
        if given["template_id"] is None:
            row.attributes = {}
    template = get_template(db, row.template_id) if row.template_id else None
    if "attributes" in given:
        if template is None and given["attributes"]:
            raise AppError("template_required", "Choose a template before entering attributes", status=422)
        row.attributes = validate(template, given["attributes"]) if template else {}
    elif template is not None and "template_id" in given:
        row.attributes = validate(template, row.attributes or {})
    if "canonical_override" in given:
        row.canonical_override = bool(given["canonical_override"])
    if row.canonical_override:
        for lang in ("fa", "en"):
            if f"canonical_{lang}" in given:
                setattr(row, f"canonical_{lang}", (given[f"canonical_{lang}"] or "").strip() or None)
    elif template is not None:
        row.canonical_fa = canonical(template, row.attributes or {}, "fa")
        row.canonical_en = canonical(template, row.attributes or {}, "en")
    else:
        row.canonical_fa = row.canonical_en = None
    return {k: getattr(row, k) for k in NOUN_FIELDS}


def describe(row, lang: str) -> str | None:
    """The description outputs use: the canonical one in the document's language, when there is one."""
    value = getattr(row, f"canonical_{lang}", None)
    return value or None


def template_out(t) -> dict:
    return {"id": str(t.id), "key": t.key, "category_id": str(t.category_id) if t.category_id else None,
            "noun_fa": t.noun_fa, "noun_en": t.noun_en, "attributes": t.attributes, "status": t.status}


def check_template(data: dict) -> list[dict]:
    """A template's attribute definitions are well formed (keys unique, types known, units known codes)."""
    attrs = data.get("attributes") or []
    keys = set()
    for a in attrs:
        if not isinstance(a, dict) or not isinstance(a.get("key"), str) or not a["key"] or a["key"] in keys:
            raise AppError("template_invalid", "Every attribute needs a unique key", status=422)
        keys.add(a["key"])
        if a.get("type", "text") not in ("text", "number", "choice"):
            raise AppError("template_invalid", "Attribute type is text, number or choice", {"attribute": a["key"]}, status=422)
        if a.get("type") == "choice" and not a.get("values"):
            raise AppError("template_invalid", "A choice attribute lists its values", {"attribute": a["key"]}, status=422)
        if a.get("unit") and not str(a["unit"]).isalnum():
            raise AppError("template_invalid", "Units are UN/ECE codes", {"attribute": a["key"]}, status=422)
    return attrs
