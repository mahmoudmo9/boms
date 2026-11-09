"""Defaults from history (v0.9.0 section 8.2): ``GET /api/suggest?context=…`` returns proposed values, each with the
record it comes from, so the UI can show it greyed with a source chip and accept it with Tab.

- ``party`` (as buyer or supplier): contact, language, currency, payment terms, Incoterm and place from the last deal
  with that party (sales order or quote for a buyer, purchase order or offer for a supplier).
- ``product`` (optionally with a party): canonical description, HS, unit, the last purchase price with its supplier and
  date, the last sale price.
- ``case``: its parties, and the currency and Incoterm for new documents."""
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.sourcing.common import jsonable


def _value(value, source: str | None, kind: str | None = None, record_id=None) -> dict | None:
    if value is None or value == "":
        return None
    return {"value": value, "source": source, "source_kind": kind, "source_id": str(record_id) if record_id else None}


def _pack(**values) -> dict:
    return {k: v for k, v in values.items() if v is not None}


def party(db: Session, party_id: uuid.UUID, role: str = "buyer") -> dict:
    if role == "supplier":
        row = db.execute(text(
            "SELECT * FROM (SELECT 'purchase_order' AS kind, id, number AS src, contact_id, language, currency, "
            "payment_terms, incoterm, incoterm_place, created_at AS at FROM ops.purchase_order "
            "WHERE supplier_party_id = :p AND status <> 'cancelled' "
            "UNION ALL SELECT 'offer', o.id, coalesce(c.code, 'offer'), o.contact_id, NULL, o.currency, o.payment_terms, "
            "o.incoterm, o.incoterm_place, o.received_at FROM ops.supplier_offer o "
            "LEFT JOIN ops.\"case\" c ON c.id = o.case_id WHERE o.party_id = :p) x "
            "ORDER BY (kind = 'purchase_order') DESC, at DESC LIMIT 1"), {"p": party_id}).mappings().first()
    else:
        row = db.execute(text(
            "SELECT * FROM (SELECT 'sales_order' AS kind, s.id, s.number AS src, s.contact_id, q.language, s.currency, "
            "s.payment_terms, s.incoterm, s.incoterm_place, s.created_at FROM ops.sales_order s "
            "LEFT JOIN ops.quote q ON q.id = s.quote_id WHERE s.customer_party_id = :p AND s.status <> 'cancelled' "
            "UNION ALL SELECT 'quote', id, number, contact_id, language, currency, payment_terms, incoterm, incoterm_place, "
            "created_at FROM ops.quote WHERE buyer_party_id = :p AND number IS NOT NULL) x "
            "ORDER BY (kind = 'sales_order') DESC, created_at DESC LIMIT 1"), {"p": party_id}).mappings().first()
    if row is None:
        lang = db.execute(text("SELECT CASE WHEN coalesce(country_iso2, 'IR') = 'IR' THEN 'fa' ELSE 'en' END "
                               "FROM core.party WHERE id = :p"), {"p": party_id}).scalar()
        return {"language": _value(lang, None, "rule")} if lang else {}
    src, kind, rid = row["src"], row["kind"], row["id"]
    return jsonable(_pack(contact_id=_value(row["contact_id"], src, kind, rid), language=_value(row["language"], src, kind, rid),
                          currency=_value(row["currency"], src, kind, rid),
                          payment_terms=_value(row["payment_terms"], src, kind, rid),
                          incoterm=_value(row["incoterm"], src, kind, rid),
                          incoterm_place=_value(row["incoterm_place"], src, kind, rid)))


def product(db: Session, product_id: uuid.UUID, party_id: uuid.UUID | None = None) -> dict:
    p = db.execute(text("SELECT code, canonical_fa, canonical_en, hs_code, default_unit_code FROM core.product "
                        "WHERE id = :i"), {"i": product_id}).mappings().first()
    if p is None:
        return {}
    out = _pack(canonical_fa=_value(p["canonical_fa"], p["code"], "product", product_id),
                canonical_en=_value(p["canonical_en"], p["code"], "product", product_id),
                hs_code=_value(p["hs_code"], p["code"], "product", product_id),
                unit_code=_value(p["default_unit_code"], p["code"], "product", product_id))
    buy = db.execute(text(
        "SELECT oi.unit_price, o.currency, o.received_at::date AS on_date, coalesce(pa.name_en, pa.name_fa) AS supplier, "
        "o.party_id, coalesce(c.code, 'offer') AS src, o.id FROM ops.offer_item oi "
        "JOIN ops.supplier_offer o ON o.id = oi.offer_id JOIN ops.line_item li ON li.id = oi.line_item_id "
        "JOIN core.party pa ON pa.id = o.party_id LEFT JOIN ops.\"case\" c ON c.id = o.case_id "
        "WHERE li.product_id = :i AND oi.unit_price IS NOT NULL AND (CAST(:party AS uuid) IS NULL OR o.party_id = :party) "
        "ORDER BY o.received_at DESC LIMIT 1"), {"i": product_id, "party": party_id}).mappings().first()
    if buy:
        out["last_purchase"] = _value({"unit_price": buy["unit_price"], "currency": buy["currency"],
                                       "supplier": buy["supplier"], "supplier_id": buy["party_id"], "date": buy["on_date"]},
                                      buy["src"], "offer", buy["id"])
    sale = db.execute(text(
        "SELECT qi.unit_price, q.currency, q.number, q.id, coalesce(q.approved_at, q.created_at)::date AS on_date "
        "FROM ops.quote_item qi JOIN ops.quote q ON q.id = qi.quote_id JOIN ops.line_item li ON li.id = qi.line_item_id "
        "WHERE li.product_id = :i AND q.number IS NOT NULL ORDER BY q.created_at DESC LIMIT 1"),
        {"i": product_id}).mappings().first()
    if sale:
        out["last_sale"] = _value({"unit_price": sale["unit_price"], "currency": sale["currency"], "date": sale["on_date"]},
                                  sale["number"], "quote", sale["id"])
    return jsonable(out)


def case(db: Session, case_id: uuid.UUID) -> dict:
    c = db.execute(text("SELECT code, party_id FROM ops.\"case\" WHERE id = :i"), {"i": case_id}).mappings().first()
    if c is None:
        return {}
    out = _pack(buyer_party_id=_value(c["party_id"], c["code"], "case", case_id))
    suppliers = db.execute(text("SELECT DISTINCT o.party_id FROM ops.line_item li JOIN ops.offer_item oi ON "
                                "oi.id = li.selected_offer_item_id JOIN ops.supplier_offer o ON o.id = oi.offer_id "
                                "WHERE li.case_id = :i"), {"i": case_id}).scalars().all()
    if suppliers:
        out["supplier_party_ids"] = _value([str(s) for s in suppliers], c["code"], "case", case_id)
    doc = db.execute(text(
        "SELECT * FROM (SELECT 'sales_order' AS kind, id, number, currency, incoterm, incoterm_place, created_at "
        "FROM ops.sales_order WHERE case_id = :i UNION ALL SELECT 'quote', id, number, currency, incoterm, incoterm_place, "
        "created_at FROM ops.quote WHERE case_id = :i AND number IS NOT NULL) x ORDER BY created_at DESC LIMIT 1"),
        {"i": case_id}).mappings().first()
    if doc:
        out.update(_pack(currency=_value(doc["currency"], doc["number"], doc["kind"], doc["id"]),
                         incoterm=_value(doc["incoterm"], doc["number"], doc["kind"], doc["id"]),
                         incoterm_place=_value(doc["incoterm_place"], doc["number"], doc["kind"], doc["id"])))
    return jsonable(out)
