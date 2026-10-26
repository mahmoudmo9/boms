"""Public service of the catalog module: products, aliases, categories, and the product page's price and demand
memory (computed from line items and offer items; nothing extra is stored)."""

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import Integer, column, func, or_, select, text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, NotFound
from app.core.text import WORD_SIMILARITY, normalize_fa
from app.modules.catalog.models import Product, ProductAlias, ProductCategory
from app.modules.events import service as events
from app.modules.parties.service import jsonable

DUPLICATE_SIMILARITY = 0.6
FIELDS = ("name_fa", "name_en", "kind_note", "default_unit_code", "hs_code", "category_id", "notes")


def _flush(db: Session, code: str) -> None:
    """Constraint errors -> stable codes; the database message is never copied into the API error."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        diag = getattr(exc.orig, "diag", None)
        detail = (getattr(diag, "message_detail", None) or "") if diag else ""
        constraint = getattr(diag, "constraint_name", None) if diag else None
        info = {"constraint": constraint} if constraint else {}
        if getattr(exc.orig, "sqlstate", None) == "23503":
            if "still referenced" in detail:
                raise Conflict("in_use", "The record is still referenced by other records", info) from None
            if 'table "unit"' in detail:
                raise AppError("unknown_unit", "Unknown unit", info, status=422) from None
            if "category" in detail:
                raise AppError("unknown_category", "Unknown category", info, status=422) from None
            raise AppError("unknown_reference", "A referenced record does not exist", info, status=422) from None
        if getattr(exc.orig, "sqlstate", None) == "23514":
            raise AppError(code, "The data violates a rule", info, status=422) from None
        raise Conflict(code, "The data conflicts with an existing record", info) from None


def _diff(obj, changes: dict) -> dict:
    out = {}
    for key, value in changes.items():
        if getattr(obj, key) != value:
            out[key] = {"old": getattr(obj, key), "new": value}
            setattr(obj, key, value)
    return out


def snapshot(obj) -> dict:
    return jsonable({c.key: getattr(obj, c.key) for c in obj.__table__.columns if not c.computed})


def _clean(data: dict) -> dict:
    for key in ("name_fa", "name_en", "kind_note", "hs_code"):
        if isinstance(data.get(key), str):
            data[key] = data[key].strip() or None
    if data.get("hs_code"):
        data["hs_code"] = data["hs_code"].replace(".", "").replace(" ", "")
    return data


# ---- products --------------------------------------------------------------------------------

def get_product(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFound("not_found", "Product not found")
    return product


def aliases_of(db: Session, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ProductAlias]]:
    out: dict[uuid.UUID, list[ProductAlias]] = {pid: [] for pid in product_ids}
    if product_ids:
        for alias in db.scalars(select(ProductAlias).where(ProductAlias.product_id.in_(product_ids))
                                .order_by(ProductAlias.created_at)):
            out[alias.product_id].append(alias)
    return out


def find_duplicates(db: Session, names: list[str], exclude: uuid.UUID | None = None) -> list[dict]:
    """Active products similar (pg_trgm) to any of ``names``.

    Each provided name is compared SEPARATELY with the stored Persian name, the English name and every alias
    (all through ``core.normalize_fa``); the greatest similarity counts. Exact normalized equality with any of
    them is always a duplicate (score 1).
    """
    found: dict[uuid.UUID, dict] = {}
    for name in names:
        needle = normalize_fa(name or "") or ""
        if not needle:
            continue
        rows = db.execute(text(
            """
            WITH c AS (
                SELECT p.id, p.name_fa, p.name_en,
                       coalesce(similarity(core.normalize_fa(p.name_fa), :n), 0) AS s_fa,
                       coalesce(similarity(core.normalize_fa(p.name_en), :n), 0) AS s_en,
                       coalesce(a.score, 0) AS s_alias,
                       (core.normalize_fa(p.name_fa) = :n OR core.normalize_fa(p.name_en) = :n
                        OR coalesce(a.exact, false)) AS exact
                FROM core.product p
                LEFT JOIN LATERAL (SELECT max(similarity(alias_norm, :n)) AS score, bool_or(alias_norm = :n) AS exact
                                   FROM core.product_alias WHERE product_id = p.id) a ON true
                WHERE p.status = 'active' AND (CAST(:ex AS uuid) IS NULL OR p.id <> CAST(:ex AS uuid))
            )
            SELECT id, name_fa, name_en,
                   CASE WHEN exact THEN 1 ELSE greatest(s_fa, s_en, s_alias) END AS score,
                   CASE WHEN s_alias > greatest(s_fa, s_en) THEN 'alias' ELSE 'name' END AS reason
            FROM c WHERE exact OR greatest(s_fa, s_en, s_alias) >= :t
            ORDER BY score DESC LIMIT 10
            """
        ), {"n": needle, "t": DUPLICATE_SIMILARITY, "ex": str(exclude) if exclude else None}).all()
        for r in rows:
            if r.id not in found or found[r.id]["score"] < float(r.score):
                found[r.id] = {"id": r.id, "name_fa": r.name_fa, "name_en": r.name_en, "score": round(float(r.score), 3),
                               "reason": r.reason}
    return sorted(found.values(), key=lambda d: -d["score"])


def create_product(db: Session, data: dict, source: str, actor: str | None = None) -> tuple[Product | None, list[dict]]:
    """(product, possible_duplicates); (None, duplicates) when similar products exist and it is not confirmed."""
    aliases = [a.strip() for a in data.pop("aliases", []) if a and a.strip()]
    confirm = data.pop("confirm_duplicate", False)
    data = _clean(data)
    if not (data.get("name_fa") or data.get("name_en")):
        raise AppError("name_required", "A Persian or English name is required", status=422)
    duplicates = find_duplicates(db, [data.get("name_fa"), data.get("name_en"), *aliases])
    if duplicates and not confirm:
        return None, duplicates
    product = Product(**{k: data.get(k) for k in FIELDS})
    db.add(product)
    _flush(db, "invalid_product")
    for alias in dict.fromkeys(aliases):
        db.add(ProductAlias(product_id=product.id, alias=alias))
    _flush(db, "duplicate_alias")
    events.record(db, "product", product.id, "create", jsonable({**{k: data.get(k) for k in FIELDS},
                                                                 "aliases": aliases,
                                                                 "confirmed_duplicates": [d["id"] for d in duplicates]}),
                  source, actor=actor)
    return product, duplicates


def update_product(db: Session, product_id: uuid.UUID, changes: dict, source: str, actor: str | None = None) -> Product:
    product = get_product(db, product_id)
    confirm_duplicate = changes.pop("confirm_duplicate", False)
    changes = _clean({k: v for k, v in changes.items() if k in FIELDS})
    name_fa = changes.get("name_fa", product.name_fa) if "name_fa" in changes else product.name_fa
    name_en = changes.get("name_en", product.name_en) if "name_en" in changes else product.name_en
    if not (name_fa or name_en):
        raise AppError("name_required", "A Persian or English name is required", status=422)
    renamed = [changes[k] for k in ("name_fa", "name_en") if k in changes and changes[k] != getattr(product, k)]
    if renamed and not confirm_duplicate:
        duplicates = find_duplicates(db, renamed, exclude=product.id)
        if duplicates:
            raise Conflict("possible_duplicate", "Similar products exist; confirm to save anyway",
                           {"possible_duplicates": jsonable(duplicates)})
    changed = _diff(product, changes)
    if changed:
        _flush(db, "invalid_product")
        events.record(db, "product", product.id, "update", jsonable({"changes": changed}), source, actor=actor)
    return product


def set_status(db: Session, product_id: uuid.UUID, status: str, source: str, actor: str | None = None) -> Product:
    product = get_product(db, product_id)
    if product.status != status:
        product.status = status
        _flush(db, "invalid_product")
        events.record(db, "product", product.id, "archive" if status == "archived" else "unarchive", {}, source,
                      actor=actor)
    return product


def add_alias(db: Session, product_id: uuid.UUID, alias: str, source: str, actor: str | None = None) -> ProductAlias:
    product = get_product(db, product_id)
    alias = alias.strip()
    if not alias:
        raise AppError("alias_required", "The alias is empty", status=422)
    row = ProductAlias(product_id=product.id, alias=alias)
    db.add(row)
    _flush(db, "duplicate_alias")
    events.record(db, "product", product.id, "alias_add", {"alias": alias}, source, actor=actor)
    return row


def remove_alias(db: Session, alias_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = db.get(ProductAlias, alias_id)
    if row is None:
        raise NotFound("not_found", "Alias not found")
    db.delete(row)
    _flush(db, "in_use")
    events.record(db, "product", row.product_id, "alias_remove", {"alias": row.alias}, source, actor=actor)


def usage_counts(db: Session, product_id: uuid.UUID) -> dict[str, int]:
    return {"line_items": db.execute(text("SELECT count(*) FROM ops.line_item WHERE product_id = :p"),
                                     {"p": product_id}).scalar() or 0}


def delete_product(db: Session, product_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    product = get_product(db, product_id)
    counts = usage_counts(db, product_id)
    if any(counts.values()):
        raise Conflict("in_use", "Line items refer to this product; archive it instead", counts)
    aliases = aliases_of(db, [product.id])[product.id]
    deleted = {"product": snapshot(product), "aliases": [a.alias for a in aliases]}
    for alias in aliases:
        db.delete(alias)
    db.flush()
    db.delete(product)
    _flush(db, "in_use")
    events.record(db, "product", product_id, "delete", {"deleted": deleted}, source, actor=actor)


def match_condition(db: Session, q: str | None):
    """Name, alias (Persian-normalized, Arabic yeh/kaf folded) or HS code prefix."""
    needle = normalize_fa(q or "") or ""
    if not needle:
        return None
    db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :v, true)"), {"v": str(WORD_SIMILARITY)})
    like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    digits = needle.replace(".", "").replace(" ", "")
    alias_match = select(ProductAlias.product_id).where(or_(
        ProductAlias.alias_norm.like(like), text("core.product_alias.alias_norm %> :pq_alias").bindparams(pq_alias=needle)))
    conditions = [Product.name_norm.like(like), text("core.product.name_norm %> :pq_name").bindparams(pq_name=needle),
                  Product.id.in_(alias_match)]
    if digits.isdigit():
        conditions.append(Product.hs_code.like(digits + "%"))
    return or_(*conditions)


def list_products(db: Session, *, q: str | None = None, category_id: uuid.UUID | None = None,
                  status: str | None = "active", sort: str = "name", page: int = 1,
                  page_size: int = 50) -> tuple[list[dict], int]:
    query = select(Product)
    if status:
        query = query.where(Product.status == status)
    if category_id:
        query = query.where(Product.category_id == category_id)
    condition = match_condition(db, q)
    if condition is not None:
        query = query.where(condition)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    stats = text(
        """
        SELECT li.product_id, max(coalesce(i.received_at, li.created_at)) AS last_requested,
               count(DISTINCT oi.id) AS offers
        FROM ops.line_item li
        LEFT JOIN ops.inquiry i ON i.id = li.inquiry_id
        LEFT JOIN ops.offer_item oi ON oi.line_item_id = li.id
        WHERE li.product_id IS NOT NULL GROUP BY li.product_id
        """
    ).columns(column("product_id", UUID), column("last_requested", TIMESTAMP(timezone=True)),
              column("offers", Integer)).subquery("stats")
    query = query.add_columns(stats.c.last_requested, stats.c.offers).outerjoin(stats, stats.c.product_id == Product.id)
    order = {"name": [Product.name_norm], "last_requested": [stats.c.last_requested.desc().nulls_last(), Product.name_norm],
             "offers": [stats.c.offers.desc().nulls_last(), Product.name_norm]}[sort]
    rows = db.execute(query.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    aliases = aliases_of(db, [r[0].id for r in rows])
    return [{**snapshot(p), "aliases": [{"id": str(a.id), "alias": a.alias} for a in aliases[p.id]],
             "last_requested": last.isoformat() if last else None, "offers": offers or 0}
            for p, last, offers in rows], total


# ---- categories --------------------------------------------------------------------------------

def categories(db: Session) -> list[ProductCategory]:
    return list(db.scalars(select(ProductCategory).where(ProductCategory.status == "active")
                           .order_by(ProductCategory.name_en, ProductCategory.name_fa)))


def create_category(db: Session, data: dict, source: str, actor: str | None = None) -> ProductCategory:
    if not ((data.get("name_fa") or "").strip() or (data.get("name_en") or "").strip()):
        raise AppError("name_required", "A Persian or English name is required", status=422)
    row = ProductCategory(**data)
    db.add(row)
    _flush(db, "invalid_category")
    events.record(db, "product_category", row.id, "create", jsonable(data), source, actor=actor)
    return row


def delete_category(db: Session, category_id: uuid.UUID, source: str, actor: str | None = None) -> None:
    row = db.get(ProductCategory, category_id)
    if row is None:
        raise NotFound("not_found", "Category not found")
    counts = {"products": db.scalar(select(func.count()).select_from(Product).where(Product.category_id == row.id)) or 0,
              "children": db.scalar(select(func.count()).select_from(ProductCategory)
                                    .where(ProductCategory.parent_id == row.id)) or 0}
    if any(counts.values()):
        raise Conflict("in_use", "The category has products or sub-categories", counts)
    deleted = snapshot(row)
    db.delete(row)
    _flush(db, "in_use")
    events.record(db, "product_category", category_id, "delete", {"deleted": deleted}, source, actor=actor)


# ---- product page (view only) ---------------------------------------------------------------------

def _stats(values: list[Decimal]) -> dict:
    return {"count": len(values), "min": min(values), "median": median(values), "max": max(values)} if values else \
        {"count": 0, "min": None, "median": None, "max": None}


def price_memory(db: Session, product_id: uuid.UUID, today: date | None = None) -> dict:
    """Every offer row for this product, plus min/median/max per (currency, unit group): all time and last
    12 months. No currency conversion; prices are normalized per base unit only inside a convertible unit kind."""
    from app.modules.sourcing.coverage import normalized_price, unit_group, unit_index

    today = today or date.today()
    units = unit_index(db)
    rows = db.execute(text(
        """
        SELECT oi.id, oi.unit_price, oi.price_per_quantity, oi.unit_code, oi.unit_text, oi.moq, oi.moq_unit,
               o.id AS offer_id, o.received_at, o.currency, o.incoterm, o.incoterm_place, o.valid_until, o.status,
               o.party_id, p.name_fa AS party_fa, p.name_en AS party_en, li.quantity, li.unit_code AS item_unit,
               li.case_id, o.contact_id, ct.name_fa AS contact_fa, ct.name_en AS contact_en
        FROM ops.offer_item oi
        JOIN ops.line_item li ON li.id = oi.line_item_id
        JOIN ops.supplier_offer o ON o.id = oi.offer_id
        JOIN core.party p ON p.id = o.party_id
        LEFT JOIN core.contact ct ON ct.id = o.contact_id
        WHERE li.product_id = :p AND oi.available AND oi.unit_price IS NOT NULL
        ORDER BY o.received_at DESC
        """
    ), {"p": product_id}).mappings().all()
    since = datetime.combine(today - timedelta(days=365), datetime.min.time()).date()
    groups: dict[tuple[str, str], dict] = {}
    entries = []
    for r in rows:
        key, factor = unit_group(r["unit_code"], r["unit_text"], units)
        price = normalized_price(r["unit_price"], r["price_per_quantity"], factor)
        entries.append({**dict(r), "unit_group": key, "normalized_price": price})
        group = groups.setdefault((r["currency"], key), {"currency": r["currency"], "unit_group": key, "all": [],
                                                          "last_12_months": []})
        group["all"].append(price)
        if r["received_at"].date() >= since:
            group["last_12_months"].append(price)
    summary = [{"currency": g["currency"], "unit_group": g["unit_group"], "all_time": _stats(g["all"]),
                "last_12_months": _stats(g["last_12_months"])} for g in groups.values()]
    summary.sort(key=lambda g: (g["currency"], g["unit_group"]))
    return jsonable({"offers": entries, "summary": summary})


def demand(db: Session, product_id: uuid.UUID) -> dict:
    from app.modules.sourcing.coverage import unit_group, unit_index

    units = unit_index(db)
    rows = db.execute(text(
        """
        SELECT li.id, li.quantity, li.unit_code, li.unit_text, li.inquiry_id, li.case_id,
               coalesce(i.received_at, li.created_at) AS requested_at, coalesce(c.party_id, i.party_id) AS buyer_id,
               p.name_fa, p.name_en
        FROM ops.line_item li
        LEFT JOIN ops.inquiry i ON i.id = li.inquiry_id
        LEFT JOIN ops."case" c ON c.id = li.case_id
        LEFT JOIN core.party p ON p.id = coalesce(c.party_id, i.party_id)
        WHERE li.product_id = :p
        ORDER BY requested_at DESC
        """
    ), {"p": product_id}).mappings().all()
    monthly: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    buyers: dict[str, dict] = {}
    for r in rows:
        if r["quantity"] is not None:
            key, factor = unit_group(r["unit_code"], r["unit_text"], units)
            monthly[(r["requested_at"].strftime("%Y-%m"), key)] += r["quantity"] * factor
        if r["buyer_id"]:
            entry = buyers.setdefault(str(r["buyer_id"]), {"party_id": r["buyer_id"], "name_fa": r["name_fa"],
                                                           "name_en": r["name_en"], "requests": 0})
            entry["requests"] += 1
    return jsonable({
        "inquiries": len({r["inquiry_id"] for r in rows if r["inquiry_id"]}),
        "cases": len({r["case_id"] for r in rows if r["case_id"]}),
        "last_requested": rows[0]["requested_at"] if rows else None,
        "quantity_by_month": [{"month": m, "unit_group": g, "quantity": q} for (m, g), q in sorted(monthly.items())],
        "buyers": sorted(buyers.values(), key=lambda b: -b["requests"]),
    })


def suppliers_by_offers(db: Session, product_id: uuid.UUID) -> list[dict]:
    rows = db.execute(text(
        """
        SELECT DISTINCT ON (o.party_id) o.party_id, p.name_fa, p.name_en, count(*) OVER (PARTITION BY o.party_id) AS offers,
               oi.unit_price AS last_price, oi.price_per_quantity, oi.unit_code, oi.unit_text, o.currency,
               o.received_at AS last_at
        FROM ops.offer_item oi
        JOIN ops.line_item li ON li.id = oi.line_item_id
        JOIN ops.supplier_offer o ON o.id = oi.offer_id
        JOIN core.party p ON p.id = o.party_id
        WHERE li.product_id = :p
        ORDER BY o.party_id, o.received_at DESC
        """
    ), {"p": product_id}).mappings().all()
    return jsonable(sorted((dict(r) for r in rows), key=lambda r: -r["offers"]))
