"""The AI tasks of v0.9.0 (section 3) and their committers.

1. ``extract_items``: items from PDFs (text layer by PyMuPDF; scanned pages rendered as images for a vision model),
   images, Excel/CSV (the model also proposes the column mapping of the import dialog) and pasted text, into a case,
   an inquiry, a supplier offer or a Setad listing conversion. Items carry the noun-modifier template and attributes,
   the original wording, quantity, UN/ECE unit, HS suggestion with reason, standards and page. Numbers are rechecked by
   code (quantity × unit price against a stated total) and differences are flagged.
2. ``parse_party``: a party and its contact from a signature, a business card image or a letterhead.
3. ``draft_message``: the RFQ message and the PO cover message in the target language with a Persian back-translation.

Every result is a draft: nothing is written before «ثبت», and then through the owning module's services with source
``ai_draft``."""
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.modules.ai import drafts, service, tasks
from app.modules.ai.adapters import Attachment

MAX_PAGES = 30
MAX_IMAGES = 8
MIN_PAGE_TEXT = 40
SHEET_ROWS = 300
NUM = {"type": ["number", "string", "null"]}
STR = {"type": ["string", "null"]}

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["items", "terms", "column_mapping"],
    "properties": {
        "items": {"type": "array", "maxItems": 500, "items": {
            "type": "object", "required": ["original", "noun", "template", "attributes", "quantity", "unit"],
            "properties": {
                "original": {"type": "string"}, "noun": STR, "template": STR,
                "attributes": {"type": "object"}, "description_en": STR, "description_fa": STR,
                "quantity": NUM, "unit": STR, "unit_text": STR,
                "specs": {"type": ["array", "null"], "items": {"type": "object"}},
                "hs_code": STR, "hs_reason": STR, "standards": {"type": ["array", "null"], "items": {"type": "string"}},
                "page": {"type": ["integer", "null"]}, "confidence": {"enum": ["high", "medium", "low", None]},
                "line_item": {"type": ["integer", "null"]},
                "unit_price": NUM, "total": NUM, "currency": STR, "moq": NUM, "lead_time_days": {"type": ["integer", "null"]},
            }}},
        "terms": {"type": ["object", "null"], "properties": {
            "incoterm": STR, "incoterm_place": STR, "valid_until": STR, "payment_terms": STR, "delivery": STR,
            "currency": STR}},
        "column_mapping": {"type": ["array", "null"], "items": {"type": ["string", "null"]}},
    },
}
PARTY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["company", "person"],
    "properties": {
        "company": {"type": "object", "properties": {
            "name": STR, "name_fa": STR, "legal_form": STR, "country_iso2": STR, "address": STR, "website": STR,
            "national_id": STR, "economic_code": STR, "phones": {"type": ["array", "null"], "items": {"type": "string"}},
            "emails": {"type": ["array", "null"], "items": {"type": "string"}}}},
        "person": {"type": ["object", "null"], "properties": {
            "name": STR, "title": STR, "phones": {"type": ["array", "null"], "items": {"type": "string"}},
            "emails": {"type": ["array", "null"], "items": {"type": "string"}}}},
    },
}
DRAFT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["subject", "body", "back_translation_fa"],
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "back_translation_fa": {"type": "string"}},
}


# ---- inputs ----------------------------------------------------------------------------------------------------------

def prepare_inputs(db: Session, document_ids: list, pasted: str | None,
                   files: list[tuple[str, str]] = ()) -> tuple[str, list[Attachment], dict, list]:
    """(text, images, description for the privacy log, sources for the review screen). Never stores the content.
    ``files``: (name, local path) of files outside the document store (Setad attachments before conversion)."""
    import mimetypes
    from pathlib import Path

    from app.modules.documents import service as documents

    entries = []
    for doc_id in document_ids or []:
        doc = documents.get(db, doc_id)
        entries.append((str(doc.id), doc.original_filename or doc.title or "file", doc.mime_type or "",
                        documents.file_path(doc).read_bytes(), doc.text_content))
    for name, path in files or []:
        p = Path(path)
        if p.is_file():
            entries.append((None, name, mimetypes.guess_type(name)[0] or "", p.read_bytes(), None))
    parts, images, names, sources = [], [], [], []
    pages = 0
    for doc_id, name, mime, data, text_content in entries:
        names.append(name)
        lower = name.lower()
        src = {"document_id": doc_id, "name": name} if doc_id else {"name": name}
        if mime == "application/pdf" or lower.endswith(".pdf"):
            text_, imgs, n = _pdf(data, name)
            pages += n
            parts.append(text_)
            images += imgs
            sources.append({**src, "kind": "pdf", "pages": n})
        elif mime.startswith("image/") or lower.endswith((".png", ".jpg", ".jpeg")):
            images.append(Attachment(name, mime or "image/png", data))
            sources.append({**src, "kind": "image"})
        elif lower.endswith((".xlsx", ".xlsm", ".csv")):
            from app.modules.sourcing import importing

            rows = importing.parse_upload(name, data)[:SHEET_ROWS]
            table = "\n".join(f"row {i}: " + " | ".join(f"[{j}] {c}" for j, c in enumerate(r)) for i, r in enumerate(rows, 1))
            parts.append(f"--- sheet {name} ({len(rows)} rows; columns by index) ---\n{table}")
            sources.append({**src, "kind": "sheet", "rows": len(rows), "preview": rows[:SHEET_ROWS]})
        else:
            parts.append(f"--- {name} ---\n{text_content or data.decode('utf-8', 'ignore')[:200000]}")
            sources.append({**src, "kind": "text"})
    if pasted and pasted.strip():
        parts.append(f"--- pasted text ---\n{pasted.strip()}")
        sources.append({"kind": "pasted", "text": pasted.strip()[:20000]})
    images = images[:MAX_IMAGES]
    text_ = "\n\n".join(p for p in parts if p)
    if not text_.strip() and not images:
        raise AppError("nothing_to_read", "Give a file or paste the text to read", status=422)
    desc = {"files": names, "pages": pages, "images": len(images), "pasted_characters": len(pasted or "")}
    return text_, images, desc, sources


def _pdf(data: bytes, name: str) -> tuple[str, list[Attachment], int]:
    """The text layer page by page; pages without text (scans) are rendered as images for a vision model."""
    import pymupdf

    out, images = [], []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            if i > MAX_PAGES:
                break
            text_ = page.get_text().strip()
            if len(text_) >= MIN_PAGE_TEXT:
                out.append(f"--- {name}, page {i} ---\n{text_}")
            elif len(images) < MAX_IMAGES:
                png = page.get_pixmap(dpi=110).tobytes("png")
                images.append(Attachment(f"{name}-page-{i}.png", "image/png", png))
                out.append(f"--- {name}, page {i}: scanned, see image {name}-page-{i}.png ---")
        return "\n\n".join(out), images, min(doc.page_count, MAX_PAGES)


def _templates_text(db: Session) -> str:
    from app.modules.catalog.models import ProductTemplate

    lines = []
    for t in db.scalars(select(ProductTemplate).where(ProductTemplate.status == "active").order_by(ProductTemplate.key)):
        attrs = []
        for a in t.attributes:
            extra = ("=" + "|".join(v["value"] for v in a.get("values", []))) if a.get("type") == "choice" else \
                (f" ({a['unit']})" if a.get("unit") else "")
            attrs.append(a["key"] + extra)
        lines.append(f"- {t.key}: {t.noun_en} / {', '.join(attrs)}")
    return "\n".join(lines)


# ---- numbers and references, checked by code -------------------------------------------------------------------------

def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    s = str(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٫٬", "0123456789.,")).replace(",", "").strip()
    try:
        return Decimal(s) if s else None
    except InvalidOperation:
        return None


def _unit_code(db: Session, unece: str | None) -> tuple[str | None, str | None]:
    """(sys.unit code, unit text): the model's UN/ECE code mapped to a BOMS unit, else kept as text."""
    if not unece:
        return None, None
    code = db.execute(text("SELECT code FROM sys.unit WHERE upper(unece_code) = upper(:u) OR lower(code) = lower(:u) "
                           "ORDER BY (upper(unece_code) = upper(:u)) DESC LIMIT 1"), {"u": unece}).scalar()
    return (code, None) if code else (None, unece)


def _hs_known(db: Session, hs: str | None) -> bool:
    if not hs or not re.fullmatch(r"\d{4,10}", hs):
        return False
    return bool(db.execute(text("SELECT 1 FROM ref.hs_code WHERE code = :c"), {"c": hs[:4]}).first())


def checks_for(items: list[dict]) -> list[dict]:
    """quantity × unit price against a stated total: differences are flagged (BOMS computes, the model only reads)."""
    out = []
    for i, it in enumerate(items):
        q, p, total = _dec(it.get("quantity")), _dec(it.get("unit_price")), _dec(it.get("total"))
        if q is not None and p is not None and total is not None:
            computed = (q * p).quantize(Decimal("0.01"))
            if abs(computed - total) > Decimal("0.01"):
                out.append({"item": i, "kind": "total_differs", "stated": str(total), "computed": str(computed)})
    return out


# ---- 1. item extraction ---------------------------------------------------------------------------------------------

TARGETS = ("case", "inquiry", "offer", "listing")


def start_extraction(db: Session, *, target_type: str, target_id, document_ids=(), text_: str | None = None,
                     party_id=None, source: str, actor: str | None):
    from app.modules.sourcing.inquiries import get_case

    if target_type not in TARGETS:
        raise AppError("invalid_target", "Items are extracted into a case, an inquiry, an offer or a Setad listing",
                       status=422)
    case_id = None
    if target_type in ("case", "offer"):
        case_id = get_case(db, target_id).id
    if target_type == "offer" and not party_id:
        raise AppError("party_required", "Choose the supplier of the offer", status=422)
    if target_type == "inquiry":
        case_id = db.execute(text("SELECT id FROM ops.\"case\" WHERE inquiry_id = :i"), {"i": target_id}).scalar()
    files = []
    if target_type == "listing":   # the downloaded Setad attachments (not in the document store before conversion)
        files = [[r.display_name, r.local_path] for r in db.execute(text(
            "SELECT display_name, local_path FROM ext.listing_file WHERE listing_id = :l AND state = 'downloaded' "
            "AND local_path IS NOT NULL ORDER BY group_key, display_name"), {"l": target_id})]
        if not files and not document_ids and not text_:
            raise AppError("files_not_downloaded", "Download the attachments first, or paste the text", status=409)
    return tasks.start(db, "extract_items", target_type=target_type, target_id=target_id, case_id=case_id,
                       payload={"document_ids": [str(d) for d in document_ids], "text": text_ or "",
                                "party_id": str(party_id) if party_id else None, "files": files},
                       sources=[{"document_id": str(d)} for d in document_ids], source=source, actor=actor)


def _case_items(db: Session, case_id) -> list:
    from app.modules.sourcing import items as sourcing_items

    return sourcing_items.items_of(db, case_id=case_id) if case_id else []


def build_extraction(db: Session, draft, payload: dict, job_id) -> None:
    text_, images, desc, sources = prepare_inputs(db, payload.get("document_ids") or [], payload.get("text"),
                                                  [tuple(f) for f in payload.get("files") or []])
    context = ""
    known = _case_items(db, draft.case_id) if draft.target_type == "offer" else []
    if known:
        context = "Items of the case (give `line_item` = the number of the matching item):\n" + "\n".join(
            f"{i}. {it.name} — {it.quantity or ''} {it.unit_code or it.unit_text or ''}" for i, it in enumerate(known, 1))
    party_ids = [payload["party_id"]] if payload.get("party_id") else []
    outcome = service.run(db, "extraction", prompt_task="extraction", text=text_, images=images, schema=EXTRACT_SCHEMA,
                          prompt_values={"templates": _templates_text(db), "target": draft.target_type, "context": context},
                          examples=drafts.examples(db, "extract_items"), case_id=draft.case_id, entity_type=draft.target_type,
                          entity_id=draft.target_id, input_desc=desc, party_ids=party_ids, job_id=job_id, max_tokens=8192)
    data = outcome.data or {}
    items = data.get("items") or []
    fields = []
    checks = checks_for(items)
    flagged = {c["item"] for c in checks}
    from app.modules.catalog import nounmod

    for i, it in enumerate(items):
        base = f"items[{i}]"
        conf = it.get("confidence") or "medium"
        src = {"page": it.get("page"), "original": it.get("original")}
        template = nounmod.template_by_key(db, it["template"]) if it.get("template") else None
        attrs = {}
        if template is not None:
            try:
                attrs = nounmod.validate(template, it.get("attributes") or {})
            except AppError:
                attrs = {k: v for k, v in (it.get("attributes") or {}).items()
                         if k in {a["key"] for a in template.attributes}}
                conf = "low"
        canonical_en = nounmod.canonical(template, attrs, "en") if template else (it.get("description_en") or None)
        canonical_fa = nounmod.canonical(template, attrs, "fa") if template else (it.get("description_fa") or None)
        unit_code, unit_text = _unit_code(db, it.get("unit") or it.get("unit_text"))
        hs = re.sub(r"\D", "", it.get("hs_code") or "") or None
        specs = [{"key": str(s.get("key") or s.get("name") or ""), "value": str(s.get("value") or "")}
                 for s in (it.get("specs") or []) if isinstance(s, dict) and (s.get("key") or s.get("name"))]
        for std in it.get("standards") or []:
            specs.append({"key": "Standard", "value": str(std)})
        quantity = _dec(it.get("quantity"))
        rows = [("name", "نام / Name", it.get("original") or canonical_en or "", conf),
                ("quantity", "مقدار / Quantity", str(quantity) if quantity is not None else None, conf),
                ("unit_code", "واحد / Unit", unit_code, conf if unit_code else "low"),
                ("unit_text", "واحد (متن) / Unit text", unit_text, "low"),
                ("template", "قالب / Template", template.key if template else None, conf),
                ("attributes", "ویژگی‌ها / Attributes", attrs or None, conf),
                ("canonical_en", "شرح استاندارد (en)", canonical_en, conf),
                ("canonical_fa", "شرح استاندارد (fa)", canonical_fa, conf),
                ("hs_code", "کد HS", hs, "medium" if _hs_known(db, hs) else "low"),
                ("hs_reason", "دلیل HS / HS reason", it.get("hs_reason"), "low"),
                ("specs", "مشخصات / Specs", specs or None, conf)]
        if draft.target_type == "offer":
            price_conf = "low" if i in flagged else conf
            rows += [("line_item", "قلم پرونده / Case item",
                      str(known[it["line_item"] - 1].id) if it.get("line_item") and 0 < it["line_item"] <= len(known) else None,
                      conf if it.get("line_item") else "low"),
                     ("unit_price", "قیمت واحد / Unit price", str(_dec(it.get("unit_price"))) if _dec(it.get("unit_price")) is not None else None, price_conf),
                     ("moq", "حداقل سفارش / MOQ", str(_dec(it.get("moq"))) if _dec(it.get("moq")) is not None else None, conf),
                     ("lead_time_days", "زمان تحویل (روز)", it.get("lead_time_days"), conf)]
        for key, label, value, c in rows:
            if value is not None and value != "":
                fields.append({"path": f"{base}.{key}", "label": f"{i + 1}. {label}", "value": value, "confidence": c,
                               "source": src})
    terms = data.get("terms") or {}
    for key in ("currency", "incoterm", "incoterm_place", "valid_until", "payment_terms", "delivery"):
        if terms.get(key):
            fields.append({"path": f"terms.{key}", "label": f"شرایط / {key}", "value": terms[key], "confidence": "medium",
                           "source": {}})
    if data.get("column_mapping"):
        fields.append({"path": "column_mapping", "label": "نگاشت ستون‌ها / Column mapping", "value": data["column_mapping"],
                       "confidence": "medium", "source": {}})
    draft.sources = sources
    drafts.fill(db, draft, fields, payload={"items": len(items)}, checks=checks, call_id=outcome.call.id)


def _group(values: dict) -> tuple[dict[int, dict], dict]:
    items: dict[int, dict] = {}
    other: dict = {}
    for path, value in values.items():
        m = re.match(r"^items\[(\d+)\]\.(\w+)$", path)
        if m:
            items.setdefault(int(m.group(1)), {})[m.group(2)] = value
        else:
            other[path] = value
    return dict(sorted(items.items())), other


def _item_row(db: Session, it: dict) -> dict | None:
    from app.modules.catalog import nounmod

    if not it.get("name") and not it.get("canonical_en"):
        return None
    row: dict[str, Any] = {"name": (it.get("name") or it.get("canonical_en"))[:1000]}
    if it.get("quantity") is not None:
        row["quantity"] = _dec(it["quantity"])
    for key in ("unit_code", "unit_text", "hs_code"):
        if it.get(key):
            row[key] = it[key]
    if it.get("specs"):
        row["specs"] = [{"key": s["key"], "value": s["value"]} for s in it["specs"]]
    if it.get("template"):
        t = nounmod.template_by_key(db, it["template"])
        if t is not None:
            row["template_id"] = t.id
            row["attributes"] = it.get("attributes") or {}
    elif it.get("canonical_en") or it.get("canonical_fa"):
        row.update(canonical_override=True, canonical_en=it.get("canonical_en"), canonical_fa=it.get("canonical_fa"))
    if it.get("hs_reason"):
        row["notes"] = f"HS: {it['hs_reason']}"
    return row


def commit_items(db: Session, draft, values: dict, source: str, actor: str | None) -> dict:
    """Case / inquiry: line items through the sourcing service."""
    from app.modules.sourcing import items as sourcing_items

    grouped, _other = _group(values)
    rows = [r for r in (_item_row(db, it) for it in grouped.values()) if r]
    if not rows:
        raise AppError("nothing_accepted", "Accept at least one item name", status=422)
    inquiry_id = uuid.UUID(draft.target_id) if draft.target_type == "inquiry" else None
    case_id = uuid.UUID(draft.target_id) if draft.target_type == "case" else None
    created = sourcing_items.add_items(db, inquiry_id, case_id, rows, source, actor)
    return {"line_item_ids": [str(r.id) for r in created]}


def commit_offer(db: Session, draft, values: dict, source: str, actor: str | None) -> dict:
    """Supplier offer: an offer of the chosen supplier through the sourcing service, priced items matched to the case."""
    from app.core.time import utcnow
    from app.modules.sourcing import offers

    payload = db.execute(text("SELECT payload FROM sys.job WHERE id = :j"), {"j": draft.job_id}).scalar() or {}
    grouped, other = _group(values)
    rows = []
    for it in grouped.values():
        if not it.get("line_item"):
            continue
        row = {"line_item_id": uuid.UUID(it["line_item"]), "available": True}
        if it.get("unit_price") is not None:
            row["unit_price"] = _dec(it["unit_price"])
        if it.get("moq") is not None:
            row["moq"] = _dec(it["moq"])
        if it.get("lead_time_days") is not None:
            row["lead_time_days"] = int(it["lead_time_days"])
        for key in ("unit_code", "unit_text"):
            if it.get(key):
                row[key] = it[key]
        rows.append(row)
    if not rows:
        raise AppError("nothing_accepted", "Accept the case item of at least one offered line", status=422)
    currency = (other.get("terms.currency") or "").upper() or None
    if not currency:
        raise AppError("currency_required", "Accept or enter the offer currency", status=422)
    data = {"case_id": uuid.UUID(draft.target_id), "party_id": uuid.UUID(payload["party_id"]), "channel": "email",
            "currency": currency, "received_at": utcnow(), "items": rows, "no_followup_reason": "recorded from an AI draft",
            "incoterm": (other.get("terms.incoterm") or "")[:3].upper() or None,
            "incoterm_place": other.get("terms.incoterm_place"), "payment_terms": other.get("terms.payment_terms"),
            "document_ids": [uuid.UUID(d) for d in payload.get("document_ids") or []]}
    if other.get("terms.valid_until"):
        from datetime import date

        try:
            data["valid_until"] = date.fromisoformat(str(other["terms.valid_until"])[:10])
        except ValueError:
            pass
    offer = offers.record_offer(db, {k: v for k, v in data.items() if v is not None}, source, actor)
    return {"offer_id": str(offer.id)}


def commit_listing(db: Session, draft, values: dict, source: str, actor: str | None) -> dict:
    """Setad listing: nothing is written here; the accepted items prefill the conversion to an inquiry."""
    grouped, _other = _group(values)
    rows = [r for r in (_item_row(db, it) for it in grouped.values()) if r]
    from app.modules.sourcing.common import jsonable

    return {"items": jsonable([{**r, "position": i} for i, r in enumerate(rows, 1)])}


# ---- 2. paste to parse a party ---------------------------------------------------------------------------------------

def build_party(db: Session, draft, payload: dict, job_id) -> None:
    text_, images, desc, sources = prepare_inputs(db, payload.get("document_ids") or [], payload.get("text"))
    outcome = service.run(db, "party_parse", prompt_task="party_parse", text=text_, images=images, schema=PARTY_SCHEMA,
                          examples=drafts.examples(db, "parse_party"), input_desc=desc, job_id=job_id, max_tokens=2048)
    data = outcome.data or {}
    company, person = data.get("company") or {}, data.get("person") or {}
    fields = []
    for key in ("name", "name_fa", "legal_form", "country_iso2", "address", "website", "national_id", "economic_code"):
        if company.get(key):
            fields.append({"path": f"company.{key}", "label": key, "value": company[key], "confidence": "high"})
    for key in ("phones", "emails"):
        if company.get(key):
            fields.append({"path": f"company.{key}", "label": key, "value": company[key], "confidence": "medium"})
    for key in ("name", "title", "phones", "emails"):
        if person.get(key):
            fields.append({"path": f"person.{key}", "label": f"person {key}", "value": person[key], "confidence": "medium"})
    draft.sources = sources
    drafts.fill(db, draft, fields, call_id=outcome.call.id)


def commit_party(db: Session, draft, values: dict, source: str, actor: str | None) -> dict:
    from app.modules.parties import service as parties
    from app.modules.reference.models import LegalForm

    name = values.get("company.name")
    name_fa = values.get("company.name_fa")
    if not (name or name_fa):
        raise AppError("name_required", "Accept the company name", status=422)
    payload = db.execute(text("SELECT payload FROM sys.job WHERE id = :j"), {"j": draft.job_id}).scalar() or {}
    country = (values.get("company.country_iso2") or "").upper() or None
    legal_form_id = None
    if values.get("company.legal_form"):
        wanted = values["company.legal_form"].strip().lower()
        for lf in db.scalars(select(LegalForm).where(LegalForm.active.is_(True))):
            if wanted in [a.lower() for a in lf.abbreviations] + [lf.local_name.lower(), (lf.name_fa or "").lower()]:
                if not country or lf.country_iso2 == country:
                    legal_form_id = lf.id
                    break
    data = {"name_en": name, "name_fa": name_fa, "country_iso2": country, "website": values.get("company.website"),
            "national_id": values.get("company.national_id"), "economic_code": values.get("company.economic_code"),
            "legal_form_id": legal_form_id, "notes": values.get("company.address"), "roles": payload.get("roles") or [],
            "confirm_duplicate": bool(payload.get("confirm_duplicate"))}
    party, duplicates = parties.create_party(db, {k: v for k, v in data.items() if v not in (None, "")}, source, actor)
    if party is None:
        from app.core.errors import Conflict
        from app.modules.sourcing.common import jsonable

        raise Conflict("possible_duplicate", "Similar parties exist; open one of them or confirm",
                       {"possible_duplicates": jsonable(duplicates)})
    methods = [{"type": "email", "value": e} for e in values.get("person.emails") or values.get("company.emails") or []]
    methods += [{"type": "phone", "value": p} for p in values.get("person.phones") or values.get("company.phones") or []]
    contact_id = None
    if values.get("person.name") or methods:
        contact, _shared = parties.create_contact(db, {"party_id": party.id, "name_en": values.get("person.name") or name,
                                                       "job_title": values.get("person.title"), "methods": methods},
                                                  source, actor, confirm_shared=True)
        contact_id = contact.id if contact else None
    return {"party_id": str(party.id), "contact_id": str(contact_id) if contact_id else None}


# ---- 3. drafting -----------------------------------------------------------------------------------------------------

def _rfq_record(db: Session, recipient_id) -> tuple[str, dict, Any]:
    from app.modules.parties import service as parties
    from app.modules.sourcing import rfq as rfq_mod

    recipient = rfq_mod.get_recipient(db, recipient_id)
    r = rfq_mod.get_rfq(db, recipient.rfq_id)
    party = parties.get_party(db, recipient.party_id)
    rows = rfq_mod.table_rows(db, r.id, recipient.language, "latin")
    lines = "\n".join(f"- {row['name']}: {row['quantity'] or ''} {row['unit'] or ''}"
                      + "".join(f"; {s.get('key')}: {s.get('value')}" for s in row.get("specs") or [])
                      + (f"; packaging {row['packaging']}" if row.get("packaging") else "")
                      + (f"; {row['incoterm']}" if row.get("incoterm") else "")
                      + (f"; required by {row['required_by']}" if row.get("required_by") else "") for row in rows)
    record = (f"RFQ {r.code} for supplier {party.name_en or party.name_fa}\nReply by: {r.respond_by}\nItems:\n{lines}")
    return record, {"language": recipient.language}, r.case_id


def _po_record(db: Session, po_id) -> tuple[str, dict, Any]:
    from app.modules.execution.common import get_purchase_order
    from app.modules.execution.purchase_orders import items_of
    from app.modules.parties import service as parties

    po = get_purchase_order(db, po_id)
    party = parties.get_party(db, po.supplier_party_id)
    lines = "\n".join(f"- {i.description}: {i.quantity} {i.unit or ''} at {i.unit_price} {po.currency}" for i in items_of(db, po.id))
    record = (f"Purchase order {po.number} to {party.name_en or party.name_fa}\nTotal {po.total} {po.currency}\n"
              f"Incoterm {po.incoterm or ''} {po.incoterm_place or ''}\nPayment {po.payment_terms or ''}\n"
              f"Ready by {po.ready_due_on or ''}\nItems:\n{lines}")
    return record, {"language": po.language}, po.case_id


def start_drafting(db: Session, *, target_type: str, target_id, language: str | None, source: str, actor: str | None):
    from app.modules.system import settings

    if target_type not in ("rfq_recipient", "purchase_order"):
        raise AppError("invalid_target", "Drafts are written for an RFQ recipient or a purchase order", status=422)
    record, meta, case_id = (_rfq_record if target_type == "rfq_recipient" else _po_record)(db, target_id)
    lang = language or settings.get(db, "ai.correspondence_language") or meta.get("language") or "en"
    return tasks.start(db, "draft_message", target_type=target_type, target_id=target_id, case_id=case_id,
                       payload={"language": lang}, source=source, actor=actor)


def build_drafting(db: Session, draft, payload: dict, job_id) -> None:
    record, _meta, case_id = (_rfq_record if draft.target_type == "rfq_recipient" else _po_record)(db, draft.target_id)
    lang = payload.get("language") or "en"
    outcome = service.run(db, "drafting", prompt_task="drafting", text=record, schema=DRAFT_SCHEMA,
                          prompt_values={"kind": "RFQ message" if draft.target_type == "rfq_recipient" else "PO cover message",
                                         "language": {"en": "English", "fa": "Persian"}.get(lang, lang)},
                          examples=drafts.examples(db, "draft_message"), case_id=case_id, entity_type=draft.target_type,
                          entity_id=draft.target_id, input_desc={"record": draft.target_type}, job_id=job_id,
                          max_tokens=3000)
    data = outcome.data or {}
    fields = [{"path": "subject", "label": "موضوع / Subject", "value": data.get("subject"), "confidence": "medium"},
              {"path": "body", "label": "متن / Body", "value": data.get("body"), "confidence": "medium"},
              {"path": "back_translation_fa", "label": "ترجمهٔ برگشتی / Back-translation",
               "value": data.get("back_translation_fa"), "confidence": "low"}]
    drafts.fill(db, draft, [f for f in fields if f["value"]], payload={"language": lang}, call_id=outcome.call.id)


def commit_rfq_message(db: Session, draft, values: dict, source: str, actor: str | None) -> dict:
    """The RFQ recipient's draft message is replaced (the owner then sends it himself)."""
    from app.modules.sourcing import rfq as rfq_mod

    changes = {}
    if values.get("subject"):
        changes["subject"] = values["subject"]
    if values.get("body"):
        changes["message_text"] = values["body"]
    rfq_mod.update_recipient(db, uuid.UUID(draft.target_id), changes, source, actor)
    return {"recipient_id": draft.target_id, "updated": sorted(changes)}


def commit_po_message(db: Session, draft, values: dict, source: str, actor: str | None) -> dict:
    """The PO cover message is copied or opened in the mail client by the owner: nothing is stored or sent."""
    from urllib.parse import quote

    subject, body = values.get("subject") or "", values.get("body") or ""
    return {"subject": subject, "body": body, "mailto": f"mailto:?subject={quote(subject)}&body={quote(body)}"}


# ---- registration ----------------------------------------------------------------------------------------------------

def register() -> None:
    tasks.register("extract_items", "extraction", build_extraction)
    tasks.register("parse_party", "party_parse", build_party)
    tasks.register("draft_message", "drafting", build_drafting)
    drafts.register_committer("case", commit_items)
    drafts.register_committer("inquiry", commit_items)
    drafts.register_committer("offer", commit_offer)
    drafts.register_committer("listing", commit_listing)
    drafts.register_committer("party", commit_party)
    drafts.register_committer("rfq_recipient", commit_rfq_message)
    drafts.register_committer("purchase_order", commit_po_message)

