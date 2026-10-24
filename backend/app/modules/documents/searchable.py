"""Documents in global search: full-text on title/filename/notes/text, fuzzy on title/filename."""

from sqlalchemy import select

from app.modules.documents import service
from app.modules.documents.models import Document
from app.modules.search.registry import SearchHit, SearchProvider, register


def _search(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    condition = service.match_condition(raw)
    if condition is None:
        return []
    rank = service.rank_expression(raw)
    rows = db.execute(
        select(Document.id, Document.title, Document.original_filename, rank.label("score"))
        .where(condition).order_by(rank.desc(), Document.uploaded_at.desc()).limit(limit)
    ).all()
    return [SearchHit(id=str(r.id), title=r.title, subtitle=r.original_filename, score=float(r.score or 0),
                      link=f"/documents/{r.id}") for r in rows]


register(SearchProvider(type="document", label_key="search.type.document", search=_search, order=10))
