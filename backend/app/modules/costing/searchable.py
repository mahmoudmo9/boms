"""Cost sheets in global search: by case title or sheet notes (Persian-normalized)."""

from sqlalchemy import text

from app.modules.search.registry import SearchHit, SearchProvider, register


def _like(needle: str) -> str:
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _sheets(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    rows = db.execute(text(
        """
        SELECT s.id, s.case_id, s.version, s.status, s.pricing_currency, c.title AS case_title
        FROM ops.cost_sheet s JOIN ops."case" c ON c.id = s.case_id
        WHERE c.title_norm LIKE :like OR c.title_norm %> :needle
           OR core.normalize_fa(coalesce(s.notes, '')) LIKE :like
        ORDER BY s.updated_at DESC LIMIT :limit
        """
    ), {"like": _like(needle), "needle": needle, "limit": limit}).all()
    return [SearchHit(id=str(r.id), title=f"{r.case_title} · v{r.version}", subtitle=r.pricing_currency, score=1.0,
                      link=f"/cases/{r.case_id}?tab=costing&sheet={r.id}", extra={"status": r.status}) for r in rows]


register(SearchProvider(type="cost_sheet", label_key="search.type.cost_sheet", search=_sheets, order=14))
