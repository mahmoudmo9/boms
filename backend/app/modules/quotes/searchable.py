"""Quotes in global search: by number, buyer or item names (Persian-normalized)."""

from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _quotes(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT q.id, q.number, q.version, q.status, q.case_id, q.currency, q.created_at, p.name_fa, p.name_en
        FROM ops.quote q
        LEFT JOIN core.party p ON p.id = q.buyer_party_id
        WHERE lower(q.number) LIKE lower(:raw_like) OR p.name_norm LIKE :like OR p.name_norm %> :needle
           OR EXISTS (SELECT 1 FROM ops.quote_item qi JOIN ops.line_item li ON li.id = qi.line_item_id
                      WHERE qi.quote_id = q.id AND (li.name_norm LIKE :like
                            OR core.normalize_fa(coalesce(qi.description_override, '')) LIKE :like))
        ORDER BY (lower(q.number) LIKE lower(:raw_like)) DESC, (p.name_norm LIKE :like) DESC, q.created_at DESC
        LIMIT :limit
        """
    ), {"like": _like(needle), "raw_like": _like((raw or "").strip()), "needle": needle, "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=f"{r.number} (v{r.version})", subtitle=r.name_fa or r.name_en,
                      score=1.0, link=f"/cases/{r.case_id}?tab=quotes&quote={r.id}", extra={"status": r.status})
            for r in rows]


register(SearchProvider(type="quote", label_key="search.type.quote", search=_quotes, order=15))
