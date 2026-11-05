"""Global search (v0.7.0): sales orders and POs (number, customer / supplier, customer ref, supplier ref), shipments
(transport document number, containers), process steps (references such as order registration and kotaj), claims."""
from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _params(needle, raw, limit):
    return {"like": _like(needle), "raw_like": _like((raw or "").strip()), "limit": limit}


def _sales_orders(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT s.id, s.case_id, s.number, s.customer_ref, s.status, p.name_fa, p.name_en
           FROM ops.sales_order s JOIN core.party p ON p.id = s.customer_party_id
           WHERE s.number ILIKE :raw_like OR coalesce(s.customer_ref, '') ILIKE :raw_like OR p.name_norm LIKE :like
           ORDER BY s.created_at DESC LIMIT :limit"""), _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=f"{r.number}{' · ' + r.customer_ref if r.customer_ref else ''}",
                      subtitle=r.name_fa or r.name_en, score=1.0, link=f"/cases/{r.case_id}?tab=order",
                      extra={"status": r.status}) for r in rows]


def _purchase_orders(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT o.id, o.case_id, o.number, o.supplier_ref, o.status, p.name_fa, p.name_en
           FROM ops.purchase_order o JOIN core.party p ON p.id = o.supplier_party_id
           WHERE o.number ILIKE :raw_like OR coalesce(o.supplier_ref, '') ILIKE :raw_like OR p.name_norm LIKE :like
           ORDER BY o.created_at DESC LIMIT :limit"""), _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=f"{r.number}{' · ' + r.supplier_ref if r.supplier_ref else ''}",
                      subtitle=r.name_fa or r.name_en, score=1.0, link=f"/cases/{r.case_id}?tab=purchase&po={r.id}",
                      extra={"status": r.status}) for r in rows]


def _shipments(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT id, case_id, transport_doc_kind, transport_doc_no, containers, status, eta FROM ops.shipment
           WHERE coalesce(transport_doc_no, '') ILIKE :raw_like OR array_to_string(containers, ' ') ILIKE :raw_like
           ORDER BY created_at DESC LIMIT :limit"""), _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=f"{(r.transport_doc_kind or '').upper()} {r.transport_doc_no or '—'}".strip(),
                      subtitle=" ".join(r.containers or []) or None, score=1.0,
                      link=f"/cases/{r.case_id}?tab=logistics&shipment={r.id}", extra={"status": r.status}) for r in rows]


def _steps(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT s.id, p.case_id, s.reference, s.label_fa, s.label_en, s.status FROM ops.process_step s
           JOIN ops.process p ON p.id = s.process_id
           WHERE s.reference IS NOT NULL AND s.reference ILIKE :raw_like ORDER BY s.updated_at DESC LIMIT :limit"""),
        _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=r.reference, subtitle=r.label_fa or r.label_en, score=1.0,
                      link=f"/cases/{r.case_id}?tab=logistics&step={r.id}", extra={"status": r.status}) for r in rows]


def _claims(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT c.id, c.case_id, c.kind, c.status, c.notes, p.name_fa, p.name_en FROM ops.claim c
           JOIN core.party p ON p.id = c.counterparty_id
           WHERE p.name_norm LIKE :like OR core.normalize_fa(coalesce(c.notes, '')) LIKE :like
           ORDER BY c.opened_on DESC LIMIT :limit"""), _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=f"{r.name_fa or r.name_en} · {r.kind}", subtitle=r.status, score=1.0,
                      link=f"/cases/{r.case_id}?tab=delivery&claim={r.id}", extra={"status": r.status}) for r in rows]


register(SearchProvider(type="sales_order", label_key="search.type.sales_order", search=_sales_orders, order=51))
register(SearchProvider(type="purchase_order", label_key="search.type.purchase_order", search=_purchase_orders, order=52))
register(SearchProvider(type="shipment", label_key="search.type.shipment", search=_shipments, order=53))
register(SearchProvider(type="process_step", label_key="search.type.process_step", search=_steps, order=54))
register(SearchProvider(type="claim", label_key="search.type.claim", search=_claims, order=55))
