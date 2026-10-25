"""Inquiries, cases, line items, RFQs and offers in global search (Persian-normalized, Arabic yeh/kaf folded)."""

from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _words(needle: str) -> str | None:
    import re

    words = re.findall(r"\w+", needle)
    return " & ".join(f"{w}:*" for w in words) if words else None


def _inquiries(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    tsq = _words(needle)
    rows = db.execute(text(
        """
        SELECT i.id, i.subject, i.status, i.received_at, p.name_fa, p.name_en, left(i.raw_text, 120) AS snippet
        FROM ops.inquiry i LEFT JOIN core.party p ON p.id = i.party_id
        WHERE core.normalize_fa(coalesce(i.subject, '')) LIKE :like
           OR core.normalize_fa(coalesce(i.subject, '')) %> :needle
           OR (CAST(:tsq AS text) IS NOT NULL
               AND to_tsvector('simple', left(i.search_norm, 300000)) @@ to_tsquery('simple', :tsq))
        ORDER BY i.received_at DESC LIMIT :limit
        """
    ), {"like": _like(needle), "needle": needle, "tsq": tsq, "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=r.subject or ((r.snippet or "").strip().splitlines() or ["—"])[0],
                      subtitle=r.name_fa or r.name_en, score=1.0, link=f"/sourcing/inquiries/{r.id}",
                      extra={"status": r.status}) for r in rows]


def _cases(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT c.id, c.title, c.status, p.name_fa, p.name_en, word_similarity(:needle, c.title_norm) AS score
        FROM ops."case" c LEFT JOIN core.party p ON p.id = c.party_id
        WHERE c.title_norm LIKE :like OR c.title_norm %> :needle
        ORDER BY (c.status = 'open') DESC, score DESC LIMIT :limit
        """
    ), {"like": _like(needle), "needle": needle, "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=r.title, subtitle=r.name_fa or r.name_en, score=float(r.score),
                      link=f"/cases/{r.id}", extra={"status": r.status}) for r in rows]


def _items(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT li.id, li.name, li.status, li.case_id, li.inquiry_id, c.title AS case_title, i.subject,
               word_similarity(:needle, li.name_norm) AS score
        FROM ops.line_item li
        LEFT JOIN ops."case" c ON c.id = li.case_id
        LEFT JOIN ops.inquiry i ON i.id = li.inquiry_id
        WHERE li.name_norm LIKE :like OR li.name_norm %> :needle OR li.hs_code LIKE :prefix
        ORDER BY score DESC, li.created_at DESC LIMIT :limit
        """
    ), {"like": _like(needle), "needle": needle, "prefix": needle.replace(" ", "") + "%", "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=r.name, subtitle=r.case_title or r.subject, score=float(r.score),
                      link=(f"/cases/{r.case_id}?tab=items&item={r.id}" if r.case_id
                            else f"/sourcing/inquiries/{r.inquiry_id}?item={r.id}"),
                      extra={"status": r.status}) for r in rows]


def _rfqs(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT DISTINCT q.id, q.title, q.status, q.case_id, c.title AS case_title, q.created_at
        FROM ops.rfq q JOIN ops."case" c ON c.id = q.case_id
        LEFT JOIN ops.rfq_recipient r ON r.rfq_id = q.id LEFT JOIN core.party p ON p.id = r.party_id
        WHERE q.title_norm LIKE :like OR q.title_norm %> :needle OR p.name_norm LIKE :like
        ORDER BY q.created_at DESC LIMIT :limit
        """
    ), {"like": _like(needle), "needle": needle, "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=r.title, subtitle=r.case_title, score=1.0,
                      link=f"/cases/{r.case_id}?tab=rfqs&rfq={r.id}", extra={"status": r.status}) for r in rows]


def _offers(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    tsq = _words(needle)
    rows = db.execute(text(
        """
        SELECT o.id, o.case_id, o.currency, o.status, o.received_at, c.title AS case_title, p.name_fa, p.name_en
        FROM ops.supplier_offer o JOIN ops."case" c ON c.id = o.case_id JOIN core.party p ON p.id = o.party_id
        WHERE p.name_norm LIKE :like OR p.name_norm %> :needle OR c.title_norm LIKE :like
           OR (CAST(:tsq AS text) IS NOT NULL
               AND to_tsvector('simple', left(coalesce(o.raw_norm, ''), 300000)) @@ to_tsquery('simple', :tsq))
        ORDER BY o.received_at DESC LIMIT :limit
        """
    ), {"like": _like(needle), "needle": needle, "tsq": tsq, "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=r.name_fa or r.name_en or "", title_i18n={
        "fa": r.name_fa or r.name_en or "", "en": r.name_en or r.name_fa or ""}, subtitle=f"{r.case_title} · {r.currency}",
        score=1.0, link=f"/cases/{r.case_id}?tab=offers&offer={r.id}", extra={"status": r.status}) for r in rows]


register(SearchProvider(type="inquiry", label_key="search.type.inquiry", search=_inquiries, order=8))
register(SearchProvider(type="case", label_key="search.type.case", search=_cases, order=9))
register(SearchProvider(type="line_item", label_key="search.type.line_item", search=_items, order=11))
register(SearchProvider(type="rfq", label_key="search.type.rfq", search=_rfqs, order=12))
register(SearchProvider(type="offer", label_key="search.type.offer", search=_offers, order=13))
