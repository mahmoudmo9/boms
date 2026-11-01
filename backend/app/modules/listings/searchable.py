"""Setad listings in global search: number, title, organization (Persian-normalized). Converted listings link to
their inquiry."""

from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _listings(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT l.id, l.source, l.external_no, l.title, l.organization, s.status, s.inquiry_id
        FROM ext.listing l LEFT JOIN ext.listing_screening s ON s.listing_id = l.id
        WHERE l.external_no LIKE :raw_like OR l.search_norm LIKE :like
        ORDER BY (l.external_no LIKE :raw_like) DESC, l.last_seen DESC
        LIMIT :limit
        """
    ), {"like": _like(needle), "raw_like": _like((raw or "").strip()), "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=f"{r.external_no} · {r.title}", subtitle=r.organization, score=1.0,
                      link=(f"/sourcing/inquiries/{r.inquiry_id}" if r.inquiry_id
                            else f"/tenders?source={r.source}&include_old=1&listing={r.id}"),
                      extra={"status": r.status or "new", "source": r.source})
            for r in rows]


register(SearchProvider(type="listing", label_key="search.type.listing", search=_listings, order=40))
