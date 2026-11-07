"""Global search (v0.8.0): sales invoice numbers and Moadian tax IDs, supplier invoice numbers, payment references."""
from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _params(needle, raw, limit):
    return {"like": _like(needle), "raw_like": _like((raw or "").strip()), "limit": limit}


def _sales_invoices(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT i.id, i.case_id, i.number, i.kind, i.status, i.moadian_tax_id, p.name_fa, p.name_en
           FROM ops.sales_invoice i JOIN core.party p ON p.id = i.customer_party_id
           WHERE coalesce(i.number, '') ILIKE :raw_like OR coalesce(i.moadian_tax_id, '') ILIKE :raw_like
           ORDER BY i.created_at DESC LIMIT :limit"""), _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=f"{r.number or '—'}{' · ' + r.moadian_tax_id if r.moadian_tax_id else ''}",
                      subtitle=r.name_fa or r.name_en, score=1.0, link=f"/cases/{r.case_id}?tab=finance&invoice={r.id}",
                      extra={"status": r.status, "kind": r.kind}) for r in rows]


def _purchase_invoices(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT i.id, i.case_id, i.supplier_invoice_no, i.status, p.name_fa, p.name_en
           FROM ops.purchase_invoice i JOIN core.party p ON p.id = i.supplier_party_id
           WHERE i.supplier_invoice_no ILIKE :raw_like ORDER BY i.created_at DESC LIMIT :limit"""),
        _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=r.supplier_invoice_no, subtitle=r.name_fa or r.name_en, score=1.0,
                      link=f"/cases/{r.case_id}?tab=finance&purchase_invoice={r.id}", extra={"status": r.status}) for r in rows]


def _payments(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """SELECT r.id, m.case_id, r.reference, r.amount, r.amount_currency, r.paid_on, m.direction
           FROM ops.payment_record r JOIN ops.payment_milestone m ON m.id = r.milestone_id
           WHERE r.reference IS NOT NULL AND r.reference ILIKE :raw_like ORDER BY r.paid_on DESC LIMIT :limit"""),
        _params(needle, raw, limit)).all()
    return [SearchHit(id=str(r.id), title=r.reference, subtitle=f"{r.amount.normalize()} {r.amount_currency} · {r.paid_on}",
                      score=1.0, link=f"/cases/{r.case_id}?tab=finance&payment={r.id}", extra={"direction": r.direction})
            for r in rows]


register(SearchProvider(type="sales_invoice", label_key="search.type.sales_invoice", search=_sales_invoices, order=61))
register(SearchProvider(type="purchase_invoice", label_key="search.type.purchase_invoice", search=_purchase_invoices, order=62))
register(SearchProvider(type="payment", label_key="search.type.payment", search=_payments, order=63))
