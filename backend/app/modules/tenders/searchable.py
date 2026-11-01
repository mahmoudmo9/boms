"""Global search: tenders (number, organizer, case title), guarantees (number, bank, beneficiary), company documents
(title); Persian-normalized."""
from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _tenders(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT t.id, t.case_id, t.tender_no, t.stage, c.title, p.name_fa, p.name_en
        FROM ops.tender t JOIN ops."case" c ON c.id = t.case_id LEFT JOIN core.party p ON p.id = t.organizer_party_id
        WHERE coalesce(t.tender_no, '') LIKE :raw_like OR c.title_norm LIKE :like OR p.name_norm LIKE :like
        ORDER BY (coalesce(t.tender_no, '') LIKE :raw_like) DESC, t.created_at DESC LIMIT :limit
        """), {"like": _like(needle), "raw_like": _like((raw or "").strip()), "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=f"{r.tender_no or '—'} · {r.title}", subtitle=r.name_fa or r.name_en, score=1.0,
                      link=f"/cases/{r.case_id}?tab=tender", extra={"stage": r.stage}) for r in rows]


def _guarantees(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT g.id, g.case_id, g.number, g.bank_name, g.purpose, g.status, p.name_fa, p.name_en
        FROM ops.guarantee g LEFT JOIN core.party p ON p.id = g.beneficiary_party_id
        WHERE coalesce(g.number, '') LIKE :raw_like OR core.normalize_fa(coalesce(g.bank_name, '')) LIKE :like
           OR p.name_norm LIKE :like
        ORDER BY g.created_at DESC LIMIT :limit
        """), {"like": _like(needle), "raw_like": _like((raw or "").strip()), "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=f"{r.number or '—'} · {r.bank_name or ''}".strip(" ·"),
                      subtitle=r.name_fa or r.name_en, score=1.0, link=f"/cases/{r.case_id}?tab=tender&guarantee={r.id}",
                      extra={"status": r.status, "purpose": r.purpose}) for r in rows]


def _company_documents(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        "SELECT id, title, category, expires_on FROM ops.company_document WHERE core.normalize_fa(title) LIKE :like "
        "ORDER BY title LIMIT :limit"), {"like": _like(needle), "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=r.title, subtitle=r.expires_on.isoformat() if r.expires_on else None, score=1.0,
                      link=f"/settings/company-documents?doc={r.id}", extra={"category": r.category}) for r in rows]


register(SearchProvider(type="tender", label_key="search.type.tender", search=_tenders, order=41))
register(SearchProvider(type="guarantee", label_key="search.type.guarantee", search=_guarantees, order=42))
register(SearchProvider(type="company_document", label_key="search.type.company_document", search=_company_documents, order=43))
