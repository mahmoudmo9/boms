"""Products in global search: names, aliases (grades, trade names, CAS numbers) and HS code."""

from sqlalchemy import select

from app.modules.catalog import service
from app.modules.catalog.models import Product
from app.modules.search.registry import SearchHit, SearchProvider, register


def _search(db, needle: str, raw: str, limit: int) -> list[SearchHit]:
    condition = service.match_condition(db, raw)
    if condition is None:
        return []
    rows = db.execute(select(Product.id, Product.name_fa, Product.name_en, Product.hs_code, Product.status)
                      .where(condition).order_by((Product.status == "active").desc(), Product.name_norm)
                      .limit(limit)).all()
    return [SearchHit(id=str(r.id), title=r.name_fa or r.name_en or "",
                      title_i18n={"fa": r.name_fa or r.name_en or "", "en": r.name_en or r.name_fa or ""},
                      subtitle=f"HS {r.hs_code}" if r.hs_code else None, score=1.0,
                      link=f"/sourcing/catalog/{r.id}", extra={"status": r.status}) for r in rows]


register(SearchProvider(type="product", label_key="search.type.product", search=_search, order=14))
